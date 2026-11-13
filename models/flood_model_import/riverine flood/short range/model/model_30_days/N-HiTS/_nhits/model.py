"""Published residual blocks with project masks and ordered quantile forecasts."""
import torch
from torch import nn

from _nhits.blocks import (
    _IdentityBasis, NHITSBlock, NBEATSBlock, IdentityBasis, TrendBasis, SeasonalityBasis,
)
from .core.lstm_model import HindcastForecastLSTM


class BasisForecaster(nn.Module):
    def __init__(self, cfg, dimensions):
        super().__init__()
        d, a = cfg['data'], cfg['architecture']
        self.quantiles = cfg['model']['quantiles']
        if sorted(set(self.quantiles)) != self.quantiles or .5 not in self.quantiles:
            raise ValueError('Use increasing unique quantiles including the median')
        self.horizon = int(d['forecast_horizon']); self.length = int(d['hindcast_length'])
        self.q_index = 2 * len(d['dynamic_columns']); self.q_missing_index = self.q_index + 1
        self.future_size = dimensions[1]
        self.base_history_size = dimensions[0] - self.future_size
        hist_size = self.base_history_size - 1  # Q uses the backcast residual; keep its missing flag.
        stat_size = dimensions[2]
        units = int(a['hidden_units']); layers = int(a['hidden_layers'])
        if layers < 2:
            raise ValueError('Use at least two hidden layers for these published blocks')
        mlp = [[units, units] for _ in range(layers - 1)]
        blocks = []
        if a['name'] == 'nhits':
            if len(a['pooling_kernels']) != len(a['frequency_downsample']):
                raise ValueError('One downsampling rate is required per pooling stack')
            for kernel, downsample in zip(a['pooling_kernels'], a['frequency_downsample']):
                if kernel < 1 or downsample < 1:
                    raise ValueError('Pooling and downsampling values must be positive')
                for _ in range(a['blocks_per_stack']):
                    theta = self.length + len(self.quantiles) * max(self.horizon // downsample, 1)
                    basis = _IdentityBasis(self.length, self.horizon, 'linear', len(self.quantiles))
                    blocks.append(NHITSBlock(self.length, self.horizon, theta, mlp, basis,
                                             self.future_size, hist_size, stat_size, kernel,
                                             'MaxPool1d', cfg['model']['dropout'], 'ReLU'))
        elif a['name'] == 'nbeatsx':
            for kind in a['stack_types']:
                for _ in range(a['blocks_per_stack']):
                    if kind == 'identity':
                        basis = IdentityBasis(self.length, self.horizon, len(self.quantiles))
                        theta = self.length + self.horizon * len(self.quantiles)
                    elif kind == 'trend':
                        basis = TrendBasis(a['polynomial_degree'], self.length, self.horizon, len(self.quantiles))
                        theta = (a['polynomial_degree'] + 1) * (1 + len(self.quantiles))
                    elif kind == 'seasonality':
                        basis = SeasonalityBasis(a['harmonics'], self.length, self.horizon, len(self.quantiles))
                        theta = basis.forecast_basis.shape[0] * (1 + len(self.quantiles))
                    else:
                        raise ValueError('Use identity, trend or seasonality stacks')
                    blocks.append(NBEATSBlock(self.length, self.horizon, self.future_size, hist_size,
                                             stat_size, theta, mlp, basis, cfg['model']['dropout'], 'ReLU'))
        else:
            raise ValueError('Unknown basis architecture')
        self.blocks = nn.ModuleList(blocks)

    def forward(self, history, future, static):
        if history.shape[1] != self.length or future.shape[1] != self.horizon:
            raise ValueError('Input windows differ from the saved configuration')
        past_q = history[..., self.q_index]
        observed = 1 - history[..., self.q_missing_index]
        residual = past_q.flip(-1) * observed.flip(-1)
        hist = torch.cat([history[..., :self.q_index], history[..., self.q_index + 1:self.base_history_size]], dim=-1)
        future_covariates = torch.cat([history[..., self.base_history_size:], future], dim=1)
        # Published Naive1 level initialization; missing issue-day Q uses the training mean.
        forecast = past_q[:, -1:, None]
        for block in self.blocks:
            backcast, addition = block(residual, future_covariates, hist, static)
            residual = (residual - backcast) * observed.flip(-1)
            forecast = forecast + addition
        # Project output channels onto ordered quantiles; targets are never transformed here.
        return torch.sort(forecast, dim=-1).values


def build_model(cfg, dimensions, statistics=None):
    if cfg['architecture']['name'] == 'lstm_control':
        return HindcastForecastLSTM(cfg, *dimensions)
    return BasisForecaster(cfg, dimensions)
