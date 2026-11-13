"""Mean-flow residual LSTM with a separate ordered quantile head."""
import torch
from torch import nn
from torch.nn import functional as F


class ResidualLSTM(nn.Module):
    def __init__(self, cfg, dimensions, statistics):
        super().__init__()
        self.cfg = cfg
        self.quantiles = cfg['model']['quantiles']
        history_size, future_size, static_size = dimensions
        if static_size or cfg['data']['use_static']:
            raise ValueError('This single-basin experiment has no static embedding')
        m = cfg['model']
        hidden = m['hidden_size']
        self.hindcast = nn.LSTM(history_size, hidden, batch_first=True)
        self.forecast = nn.LSTM(future_size + m['lead_embedding_size'] + 1, hidden, batch_first=True)
        self.lead = nn.Embedding(cfg['data']['forecast_horizon'], m['lead_embedding_size'])
        self.dropout = nn.Dropout(m['dropout'])
        self.mean_head = nn.Linear(hidden, 1)
        self.quantile_head = nn.Linear(hidden, len(self.quantiles))
        nn.init.zeros_(self.mean_head.weight)
        nn.init.zeros_(self.mean_head.bias)
        nn.init.zeros_(self.quantile_head.weight)
        with torch.no_grad():
            self.quantile_head.bias[0] = -.8
            self.quantile_head.bias[1:] = torch.log(torch.expm1(torch.full((len(self.quantiles) - 1,), .4)))
        self.register_buffer('flow_scale', torch.tensor(statistics['flow_std_cumecs']))

    def initialize_from_parent(self, parent):
        source = parent['model_state']
        with torch.no_grad():
            for name, value in self.state_dict().items():
                if name.startswith(('hindcast.', 'lead.')):
                    value.copy_(source[name])
                elif name.startswith('forecast.'):
                    if name == 'forecast.weight_ih_l0':
                        value.zero_()
                        value[:, :source[name].shape[1]].copy_(source[name])
                    else:
                        value.copy_(source[name])

    def forward(self, history, future, smooth_climatology):
        _, state = self.hindcast(self.dropout(history))
        embedding = self.lead(torch.arange(future.size(1), device=future.device))[None].expand(future.size(0), -1, -1)
        anchor = (smooth_climatology / self.flow_scale).unsqueeze(-1)
        decoded, _ = self.forecast(self.dropout(torch.cat([future, embedding, anchor], -1)), state)
        decoded = self.dropout(decoded)
        mean = (smooth_climatology + self.flow_scale * self.mean_head(decoded).squeeze(-1)).clamp_min(0)
        raw = self.quantile_head(decoded)
        residual_quantiles = torch.cat([raw[..., :1], raw[..., :1] + torch.cumsum(F.softplus(raw[..., 1:]), -1)], -1)
        quantiles = (smooth_climatology.unsqueeze(-1) + self.flow_scale * residual_quantiles).clamp_min(0)
        return mean, quantiles


def objective(mean, quantiles, batch, scale, cfg):
    valid = batch['mask'] & torch.isfinite(batch['target_q'])
    if not valid.any():
        return mean.sum() * 0
    weights = torch.ones_like(mean)
    start = cfg['training']['selection_leads'][0] - 1
    weights[:, start:] = cfg['training']['late_lead_weight']
    weights = weights[valid]
    y = batch['target_q'][valid]
    point = ((mean[valid] - y) / scale).square()
    error = (y.unsqueeze(-1) - quantiles[valid]) / scale
    levels = quantiles.new_tensor(cfg['model']['quantiles'])
    pinball = torch.maximum(levels * error, (levels - 1) * error).mean(-1)
    penalty = ((mean[valid] - batch['smooth_climatology'][valid]) / scale).square()
    options = cfg['training']
    losses = options['point_mse_weight'] * point + options['quantile_loss_weight'] * pinball + options['residual_penalty'] * penalty
    return (weights * losses).sum() / weights.sum()
