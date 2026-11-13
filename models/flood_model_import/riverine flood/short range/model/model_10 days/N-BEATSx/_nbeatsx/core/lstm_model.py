"""Small encoder/decoder LSTM and observed-only quantile loss."""
import torch
from torch import nn
from torch.nn import functional as F


def masked_pinball(prediction, target, mask, quantiles):
    valid = mask.bool() & torch.isfinite(target)
    if not valid.any():
        return prediction.sum() * 0
    error = target[valid].unsqueeze(-1) - prediction[valid]
    tau = prediction.new_tensor(quantiles)
    return torch.maximum(tau * error, (tau - 1) * error).mean()


class HindcastForecastLSTM(nn.Module):
    def __init__(self, config, hindcast_features, forecast_features, static_features=0):
        super().__init__()
        m, d = config['model'], config['data']
        self.quantiles = m['quantiles']
        if sorted(set(self.quantiles)) != self.quantiles or not all(0 < x < 1 for x in self.quantiles) or 0.5 not in self.quantiles:
            raise ValueError('Quantiles must be sorted, unique, in (0,1), and include 0.5')
        static_size = m['static_embedding_size'] if d['use_static'] else 0
        self.static = nn.Sequential(nn.Linear(static_features, static_size), nn.Tanh()) if static_size else None
        self.lead = nn.Embedding(d['forecast_horizon'], m['lead_embedding_size'])
        recurrent_dropout = m['dropout'] if m['num_layers'] > 1 else 0
        self.hindcast = nn.LSTM(hindcast_features + static_size, m['hidden_size'], m['num_layers'], batch_first=True, dropout=recurrent_dropout)
        self.forecast = nn.LSTM(forecast_features + static_size + m['lead_embedding_size'], m['hidden_size'], m['num_layers'], batch_first=True, dropout=recurrent_dropout)
        self.dropout = nn.Dropout(m['dropout'])
        self.head = nn.Linear(m['hidden_size'], len(self.quantiles))

    def forward(self, history, future, static):
        static_embedding = self.static(static) if self.static is not None else None
        if static_embedding is not None:
            history = torch.cat([history, static_embedding[:, None].expand(-1, history.size(1), -1)], -1)
        _, state = self.hindcast(self.dropout(history))
        leads = self.lead(torch.arange(future.size(1), device=future.device))[None].expand(future.size(0), -1, -1)
        parts = [future, leads]
        if static_embedding is not None:
            parts.append(static_embedding[:, None].expand(-1, future.size(1), -1))
        decoded, _ = self.forecast(self.dropout(torch.cat(parts, -1)), state)
        raw = self.head(self.dropout(decoded))
        # Ordered positive increments prevent crossing in log space and flow space.
        return torch.cat([raw[..., :1], raw[..., :1] + torch.cumsum(F.softplus(raw[..., 1:]), -1)], -1)
