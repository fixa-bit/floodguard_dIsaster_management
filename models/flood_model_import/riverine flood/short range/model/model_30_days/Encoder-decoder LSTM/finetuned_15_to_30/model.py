"""Extend the pretrained 15-day encoder/decoder and fine-tune all 30 leads."""
import torch
from torch import nn
from torch.nn import functional as F


class EncoderDecoderLSTM(nn.Module):
    def __init__(self, cfg, dimensions, statistics):
        super().__init__()
        self.cfg = cfg
        self.quantiles = cfg['model']['quantiles']
        h, f, static = dimensions
        if static or cfg['data']['use_static'] or cfg['model']['num_layers'] != 1:
            raise ValueError('This transferred variant uses the parent single-layer, non-static architecture')
        hidden = cfg['model']['hidden_size']
        self.hindcast = nn.LSTM(h, hidden, batch_first=True)
        self.forecast = nn.LSTM(f + cfg['model']['lead_embedding_size'] + 1, hidden, batch_first=True)
        self.lead = nn.Embedding(cfg['data']['forecast_horizon'], cfg['model']['lead_embedding_size'])
        self.dropout = nn.Dropout(cfg['model']['dropout'])
        self.mean_head = nn.Linear(hidden, 1)
        self.quantile_head = nn.Linear(hidden, len(self.quantiles))
        nn.init.zeros_(self.mean_head.weight)
        nn.init.zeros_(self.mean_head.bias)
        self.register_buffer('flow_scale', torch.tensor(statistics['flow_std_cumecs']))
        self.register_buffer('flow_log_mean', torch.tensor(statistics['flow']['mean']))
        self.register_buffer('flow_log_std', torch.tensor(statistics['flow']['std']))
        self.register_buffer('flow_log_scale', torch.tensor(statistics['flow']['scale']))

    def initialize_from_parent(self, parent):
        source = parent['model_state']
        if source['lead.weight'].shape[0] != 15 or self.lead.num_embeddings != 30:
            raise ValueError('Expected an explicit 15-to-30-day transfer')
        if parent['config']['model']['quantiles'] != self.quantiles:
            raise ValueError('Quantile levels differ from parent')
        with torch.no_grad():
            for name, value in self.state_dict().items():
                if name.startswith('hindcast.'):
                    value.copy_(source[name])
                elif name == 'lead.weight':
                    value[:15].copy_(source[name])
                    value[15:].copy_(source[name][-1:].expand(15, -1))
                elif name.startswith('forecast.'):
                    if name == 'forecast.weight_ih_l0':
                        value.zero_()
                        value[:, :source[name].shape[1]].copy_(source[name])
                    else:
                        value.copy_(source[name])
                elif name.startswith('quantile_head.'):
                    value.copy_(source[name.replace('quantile_head.', 'head.')])

    def decode(self, history, future, smooth_climatology):
        _, state = self.hindcast(self.dropout(history))
        leads = self.lead(torch.arange(future.size(1), device=future.device))[None].expand(future.size(0), -1, -1)
        anchor = (smooth_climatology / self.flow_scale).unsqueeze(-1)
        decoded, _ = self.forecast(self.dropout(torch.cat([future, leads, anchor], -1)), state)
        return self.dropout(decoded)

    def ordered_log_quantiles(self, decoded):
        raw = self.quantile_head(decoded)
        return torch.cat([raw[..., :1], raw[..., :1] + torch.cumsum(F.softplus(raw[..., 1:]), -1)], -1)

    def forward(self, history, future, smooth_climatology):
        decoded = self.decode(history, future, smooth_climatology)
        mean = (smooth_climatology + self.flow_scale * self.mean_head(decoded).squeeze(-1)).clamp_min(0)
        log_quantiles = self.ordered_log_quantiles(decoded)
        quantiles = (torch.expm1(log_quantiles * self.flow_log_std + self.flow_log_mean) * self.flow_log_scale).clamp_min(0)
        return mean, quantiles


def objective(mean, quantiles, batch, scale, cfg):
    valid = batch['mask'] & torch.isfinite(batch['target_q'])
    if not valid.any():
        return mean.sum() * 0
    weights = torch.ones_like(mean)
    weights[:, cfg['training']['selection_leads'][0] - 1:] = cfg['training']['late_lead_weight']
    weights = weights[valid]
    y = batch['target_q'][valid]
    squared = ((mean[valid] - y) / scale).square()
    error = (y.unsqueeze(-1) - quantiles[valid]) / scale
    levels = quantiles.new_tensor(cfg['model']['quantiles'])
    pinball = torch.maximum(levels * error, (levels - 1) * error).mean(-1)
    penalty = ((mean[valid] - batch['smooth_climatology'][valid]) / scale).square()
    options = cfg['training']
    total = options['point_mse_weight'] * squared + options['quantile_loss_weight'] * pinball + options['residual_penalty'] * penalty
    return (total * weights).sum() / weights.sum()
