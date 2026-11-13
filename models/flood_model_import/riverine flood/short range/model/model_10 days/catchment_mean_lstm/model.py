"""Independent encoder/forecast LSTMs per actual elevation band."""
# Model workspace import path.
import sys as _layout_sys
from pathlib import Path as _LayoutPath
for _layout_parent in _LayoutPath(__file__).resolve().parents:
    if (_layout_parent / 'evaluation comparison' / 'common').is_dir():
        _layout_sys.path.insert(0, str(_layout_parent / 'model' / 'model_15 days'))
        _layout_sys.path.insert(0, str(_layout_parent / 'model' / 'model_10 days'))
        _layout_sys.path.insert(0, str(_layout_parent / 'evaluation comparison' / 'common'))
        break

import torch
from torch import nn
from torch.nn import functional as F

from lstm.model import masked_pinball


class ElevationBandLSTM(nn.Module):
    def __init__(self, cfg, hindcast_features, forecast_features, static_features=0):
        super().__init__()
        d, m, options = cfg['data'], cfg['model'], cfg['spatial']
        self.quantiles = m['quantiles']
        if sorted(set(self.quantiles)) != self.quantiles or not all(0 < q < 1 for q in self.quantiles) or .5 not in self.quantiles:
            raise ValueError('Provide increasing quantiles in (0,1), including the median')
        self.register_buffer('area_weights', torch.tensor(options['area_weights'], dtype=torch.float32))
        self.history_indices, self.future_indices = [], []
        extra = list(range(2 * len(d['dynamic_columns']), hindcast_features))
        for band in options['band_ids']:
            h = [d['dynamic_columns'].index(f'{band}_{v}') for v in options['history_variables']]
            f = [d['forecast_columns'].index(f'{band}_{v}') for v in options['forecast_variables']]
            self.history_indices.append(h + [i + len(d['dynamic_columns']) for i in h] + extra)
            self.future_indices.append(f + [i + len(d['forecast_columns']) for i in f])
        static_size = m['static_embedding_size'] if d['use_static'] else 0
        self.static = nn.Sequential(nn.Linear(static_features, static_size), nn.Tanh()) if static_size else None
        self.lead = nn.Embedding(d['forecast_horizon'], m['lead_embedding_size'])
        dropout = m['dropout'] if m['num_layers'] > 1 else 0
        self.hindcast = nn.ModuleList([nn.LSTM(len(indices) + static_size, m['hidden_size'], m['num_layers'],
                                             batch_first=True, dropout=dropout) for indices in self.history_indices])
        self.forecast = nn.ModuleList([nn.LSTM(len(indices) + static_size + m['lead_embedding_size'], m['hidden_size'], m['num_layers'],
                                             batch_first=True, dropout=dropout) for indices in self.future_indices])
        self.dropout = nn.Dropout(m['dropout'])
        self.head = nn.Linear(len(self.area_weights) * m['hidden_size'], len(self.quantiles))

    def forward(self, history, future, static):
        lead = self.lead(torch.arange(future.size(1), device=future.device))[None].expand(future.size(0), -1, -1)
        embedding = self.static(static) if self.static is not None else None
        outputs = []
        for i, (encoder, decoder) in enumerate(zip(self.hindcast, self.forecast)):
            past = history[:, :, self.history_indices[i]]
            parts = [future[:, :, self.future_indices[i]], lead]
            if embedding is not None:
                past = torch.cat([past, embedding[:, None].expand(-1, past.size(1), -1)], dim=-1)
                parts.append(embedding[:, None].expand(-1, future.size(1), -1))
            _, state = encoder(self.dropout(past))
            output, _ = decoder(self.dropout(torch.cat(parts, dim=-1)), state)
            outputs.append(output * self.area_weights[i])
        raw = self.head(self.dropout(torch.cat(outputs, dim=-1)))
        return torch.cat([raw[..., :1], raw[..., :1] + torch.cumsum(F.softplus(raw[..., 1:]), dim=-1)], dim=-1)


def build_model(cfg, dimensions, statistics):
    return ElevationBandLSTM(cfg, *dimensions)
