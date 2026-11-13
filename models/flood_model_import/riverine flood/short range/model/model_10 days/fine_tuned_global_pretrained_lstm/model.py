"""Exact published Caravan core plus zero-initialized missing-indicator adapters."""
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


class FC(nn.Module):
    def __init__(self, inputs, outputs):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(inputs, outputs))

    def forward(self, values):
        return self.net(values)


class Embedding(nn.Module):
    def __init__(self, static_size):
        super().__init__()
        self.statics_embedding = FC(static_size, 10)


class GlobalPretrainedLSTM(nn.Module):
    def __init__(self, source_config, gradient_history_days=60):
        super().__init__()
        self.embedding_net = Embedding(len(source_config['static_attributes']))
        self.lstm = nn.LSTM(len(source_config['dynamic_inputs']) + 10, source_config['hidden_size'], batch_first=True)
        self.dropout = nn.Dropout(source_config['output_dropout'])
        self.head = FC(source_config['hidden_size'], 1)
        self.gradient_history_days = gradient_history_days
        self.dynamic_missing = nn.Linear(len(source_config['dynamic_inputs']), len(source_config['dynamic_inputs']), bias=False)
        self.static_missing = nn.Linear(len(source_config['static_attributes']), 10, bias=False)
        nn.init.zeros_(self.dynamic_missing.weight); nn.init.zeros_(self.static_missing.weight)

    def load_published_weights(self, weights):
        result = self.load_state_dict(weights, strict=False)
        if set(result.missing_keys) != {'dynamic_missing.weight', 'static_missing.weight'} or result.unexpected_keys:
            raise ValueError('Checkpoint does not exactly match the published core architecture')
        for key, value in weights.items():
            if not torch.equal(self.state_dict()[key], value):
                raise AssertionError(f'A published tensor was not preserved: {key}')

    def forward(self, history, future, static, history_missing, future_missing, static_missing):
        embedding = self.embedding_net.statics_embedding(static) + self.static_missing(static_missing)
        past = history + self.dynamic_missing(history_missing)
        forecasts = future + self.dynamic_missing(future_missing)
        past = torch.cat([past, embedding[:, None].expand(-1, past.size(1), -1)], dim=-1)
        forecasts = torch.cat([forecasts, embedding[:, None].expand(-1, forecasts.size(1), -1)], dim=-1)
        warmup = max(0, past.size(1) - self.gradient_history_days) if self.training else 0
        if warmup:
            with torch.no_grad():
                _, state = self.lstm(past[:, :warmup])
            _, state = self.lstm(past[:, warmup:], state)
        else:
            _, state = self.lstm(past)
        decoded, _ = self.lstm(forecasts, state)
        return self.head(self.dropout(decoded)).squeeze(-1)


def masked_mse(prediction, target, mask):
    valid = mask.bool() & torch.isfinite(target)
    return ((prediction[valid] - target[valid]) ** 2).mean() if valid.any() else prediction.sum() * 0
