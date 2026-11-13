"""Water-conserving conceptual buckets augment an unconstrained LSTM head."""
# Model workspace import path.
import sys as _layout_sys
from pathlib import Path as _LayoutPath
for _layout_parent in _LayoutPath(__file__).resolve().parents:
    if (_layout_parent / 'evaluation comparison' / 'common').is_dir():
        _layout_sys.path.insert(0, str(_layout_parent / 'model' / 'model_15 days'))
        _layout_sys.path.insert(0, str(_layout_parent / 'model' / 'model_10 days'))
        _layout_sys.path.insert(0, str(_layout_parent / 'evaluation comparison' / 'common'))
        break

import math
from typing import List, Tuple

import torch
from torch import Tensor, nn

from lstm.model import HindcastForecastLSTM, masked_pinball
from hybrid_physics_ml.data import validate_physics_inputs


def bucket_scan(precipitation: Tensor, temperature: Tensor, initial_state: Tensor,
                parameters: Tensor) -> Tuple[Tensor, Tensor, Tensor]:
    state = initial_state
    values: List[Tensor] = []
    residuals: List[Tensor] = []
    threshold, degree_day, capacity, percolation, recession, evaporation, width, offset = parameters.unbind()
    for day in range(precipitation.size(1)):
        p = precipitation[:, day].clamp_min(0)
        t = temperature[:, day]
        snow, soil, groundwater = state.unbind(dim=-1)
        snow_fraction = torch.sigmoid((threshold - t) / width)
        snowfall = p * snow_fraction
        rainfall = p - snowfall
        snow_available = snow + snowfall
        melt = torch.minimum(snow_available, degree_day * torch.relu(t - threshold))
        snow_next = snow_available - melt
        soil_available = soil + rainfall + melt
        quickflow = torch.relu(soil_available - capacity)
        soil_available = soil_available - quickflow
        et = torch.minimum(soil_available, evaporation * torch.relu(t + offset))
        soil_after_et = soil_available - et
        recharge = percolation * soil_after_et
        soil_next = soil_after_et - recharge
        groundwater_available = groundwater + recharge
        baseflow = recession * groundwater_available
        groundwater_next = groundwater_available - baseflow
        runoff = quickflow + baseflow
        state = torch.stack([snow_next, soil_next, groundwater_next], dim=-1)
        residuals.append(snow + soil + groundwater + p - state.sum(dim=-1) - et - runoff)
        values.append(torch.stack([snow_next, soil_next, groundwater_next, melt, runoff, et], dim=-1))
    return torch.stack(values, dim=1), state, torch.stack(residuals, dim=1)


class SnowWaterBucket(nn.Module):
    names = ['rain_snow_threshold_c', 'degree_day_mm_per_c_day', 'soil_capacity_mm',
             'recharge_fraction', 'groundwater_recession', 'evaporation_mm_per_c_day']

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.raw = nn.ParameterDict()
        for name in self.names:
            low, high, initial = cfg['parameters'][name]
            if not low < initial < high:
                raise ValueError(f'{name}: require low < initial < high')
            if name != 'rain_snow_threshold_c' and low < 0:
                raise ValueError('Physical coefficient lower bounds must be nonnegative')
            if name in ('recharge_fraction', 'groundwater_recession') and high > 1:
                raise ValueError('Water-release fractions cannot exceed one')
            fraction = (initial - low) / (high - low)
            self.raw[name] = nn.Parameter(torch.tensor(math.log(fraction / (1 - fraction)), dtype=torch.float32))

    def parameters_physical(self):
        values = []
        for name in self.names:
            low, high, _ = self.cfg['parameters'][name]
            values.append(low + (high - low) * torch.sigmoid(self.raw[name]))
        return torch.stack(values + [values[0].new_tensor(self.cfg['phase_transition_width_c']),
                                     values[0].new_tensor(self.cfg['evaporation_temperature_offset_c'])])

    def forward(self, precipitation, temperature, state):
        return bucket_scan(precipitation, temperature, state, self.parameters_physical())


class HybridPhysicsLSTM(nn.Module):
    def __init__(self, cfg, hindcast_features, forecast_features, static_features, statistics):
        super().__init__()
        validate_physics_inputs(cfg)
        self.cfg = cfg
        self.quantiles = cfg['model']['quantiles']
        self.bucket = SnowWaterBucket(cfg['physics'])
        self.lstm = HindcastForecastLSTM(cfg, hindcast_features + 6, forecast_features + 6, static_features)
        for kind in ('dynamic', 'forecast'):
            for field in ('center', 'scale'):
                self.register_buffer(f'{kind}_{field}', torch.tensor(statistics[kind][field], dtype=torch.float32))
        self.register_buffer('feature_scale', torch.tensor(cfg['physics']['feature_scales_mm'], dtype=torch.float32))
        if self.feature_scale.shape != (6,) or (self.feature_scale <= 0).any():
            raise ValueError('Provide six positive physical feature scales')
        d, p = cfg['data'], cfg['physics']
        self.history_index = {k: d['dynamic_columns'].index(v) for k, v in p['history_columns'].items()}
        self.future_index = {k: d['forecast_columns'].index(v) for k, v in p['forecast_columns'].items()}

    @property
    def hindcast(self):
        return self.lstm.hindcast

    def set_input_statistics(self, statistics):
        # Fine-tuning may intentionally recompute input scaling.
        with torch.no_grad():
            for kind in ('dynamic', 'forecast'):
                for field in ('center', 'scale'):
                    buffer = getattr(self, f'{kind}_{field}')
                    buffer.copy_(buffer.new_tensor(statistics[kind][field]))

    def physics_features(self, history, future):
        def raw(array, kind, index):
            return array[..., index] * getattr(self, f'{kind}_scale')[index] + getattr(self, f'{kind}_center')[index]
        h, f = self.history_index, self.future_index
        p_history = raw(history, 'dynamic', h['precipitation'])
        t_history = raw(history, 'dynamic', h['temperature'])
        p_future = raw(future, 'forecast', f['precipitation'])
        t_future = raw(future, 'forecast', f['temperature'])
        initial_snow = raw(history[:, :1], 'dynamic', h['swe'])[:, 0].clamp_min(0)
        initial = torch.stack([initial_snow,
                               torch.full_like(initial_snow, self.cfg['physics']['initial_soil_mm']),
                               torch.full_like(initial_snow, self.cfg['physics']['initial_groundwater_mm'])], dim=-1)
        span = self.cfg['physics']['gradient_history_days']
        warmup = max(0, history.size(1) - span) if self.training else 0
        if warmup:
            # Truncate parameter gradients, while retaining the full state spin-up.
            with torch.no_grad():
                prefix, state, prefix_residual = self.bucket(p_history[:, :warmup], t_history[:, :warmup], initial)
            tail, state_at_issue, tail_residual = self.bucket(p_history[:, warmup:], t_history[:, warmup:], state)
            past = torch.cat([prefix, tail], dim=1)
            past_residual = torch.cat([prefix_residual, tail_residual], dim=1)
        else:
            past, state_at_issue, past_residual = self.bucket(p_history, t_history, initial)
        forecast, final_state, forecast_residual = self.bucket(p_future, t_future, state_at_issue)
        return past, forecast, {'initial_state': initial, 'state_at_issue': state_at_issue,
                                'final_state': final_state, 'history_residual_mm': past_residual,
                                'forecast_residual_mm': forecast_residual}

    def forward(self, history, future, static):
        past, forecast, _ = self.physics_features(history, future)
        # Fixed unit scales use no validation/test statistics.
        past = torch.log1p(past.clamp_min(0) / self.feature_scale)
        forecast = torch.log1p(forecast.clamp_min(0) / self.feature_scale)
        return self.lstm(torch.cat([history, past], -1), torch.cat([future, forecast], -1), static)


def build_model(cfg, dimensions, statistics):
    return HybridPhysicsLSTM(cfg, *dimensions, statistics)
