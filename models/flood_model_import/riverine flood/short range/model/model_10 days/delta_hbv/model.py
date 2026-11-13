"""LSTM parameter learning through the authors' differentiable HBV 1.0."""
import sys
from pathlib import Path

import numpy as np
import torch
from torch import nn

sys.path.insert(0, str(Path(__file__).resolve().parent / '_vendor'))
from hydrodl2.models.hbv.hbv import Hbv


class DeltaHBV(nn.Module):
    def __init__(self, cfg, input_size=8):
        super().__init__()
        self.cfg = cfg
        options = cfg['model']
        self.warmup = options['warmup_without_gradients']
        if not 15 <= cfg['data']['hindcast_length'] - self.warmup:
            raise ValueError('Retain at least 15 routed history days after no-gradient warmup')
        self.physics = Hbv({
            'warmup': self.warmup, 'warmup_states': True, 'routing': True,
            'dynamic_params': {'Hbv': options['dynamic_parameters']},
            'nmul': options['components'], 'cache_states': False, 'dy_drop': 0.0,
        }, device=torch.device(cfg['training']['device']))
        hidden = options['hidden_size']
        self.parameter_lstm = nn.LSTM(input_size, hidden, batch_first=True)
        self.dropout = nn.Dropout(options['dropout'])
        self.parameter_head = nn.Linear(hidden, self.physics.learnable_param_count)
        nn.init.normal_(self.parameter_head.weight, std=0.01)
        nn.init.zeros_(self.parameter_head.bias)
        names = list(self.physics.parameter_bounds)
        initial = {'parBETA': 2., 'parFC': 300., 'parK0': .3, 'parK1': .1,
                   'parK2': .02, 'parLP': .7, 'parPERC': 2., 'parUZL': 20.,
                   'parTT': 0., 'parCFMAX': 3., 'parCFR': .05, 'parCWH': .1}
        logits, dynamic_mask = [], []
        for name, (low, high) in self.physics.parameter_bounds.items():
            fraction = (initial[name] - low) / (high - low)
            for component in range(options['components']):
                # Break otherwise identical parallel components deterministically.
                offset = .15 * (component - (options['components'] - 1) / 2)
                logits.append(float(np.log(fraction / (1 - fraction))) + offset)
                dynamic_mask.append(float(name in options['dynamic_parameters']))
        for name, (low, high) in self.physics.routing_parameter_bounds.items():
            initial_value = {'route_a': 1.2, 'route_b': 1.5}[name]
            fraction = (initial_value - low) / (high - low)
            logits.append(float(np.log(fraction / (1 - fraction))))
            dynamic_mask.append(0.)
        self.static_logits = nn.Parameter(torch.tensor(logits, dtype=torch.float32))
        self.register_buffer('dynamic_mask', torch.tensor(dynamic_mask))
        self.conversion = options['area_km2'] / 86.4

    def parameter_logits(self, neural):
        # Truncated gradient history matches the physical model's warmup.
        if self.warmup:
            with torch.no_grad():
                prefix, state = self.parameter_lstm(neural[:, :self.warmup])
            tail, _ = self.parameter_lstm(neural[:, self.warmup:], state)
            output = torch.cat([prefix, tail], dim=1)
        else:
            output, _ = self.parameter_lstm(neural)
        learned = self.parameter_head(self.dropout(output))
        return self.static_logits + self.dynamic_mask * self.cfg['model']['dynamic_logit_scale'] * torch.tanh(learned)

    def forward(self, neural, forcing):
        logits = self.parameter_logits(neural).transpose(0, 1)
        fluxes = self.physics({'x_phy': forcing.transpose(0, 1)}, logits)
        horizon = self.cfg['data']['forecast_horizon']
        # The prediction is physical routed runoff; there is no residual output head.
        return fluxes['streamflow'][-horizon:, :, 0].transpose(0, 1) * self.conversion


def masked_loss(prediction, target, mask, statistics, options):
    valid = mask & torch.isfinite(target)
    if not valid.any():
        return prediction.sum() * 0
    pred = prediction[valid]
    logarithm = target[valid] * statistics['flow']['std'] + statistics['flow']['mean']
    observed = torch.expm1(logarithm) * statistics['flow']['scale']
    flow = ((pred - observed) / statistics['flow_mse_scale']).square().mean()
    log_pred = (torch.log1p(pred / statistics['flow']['scale']) - statistics['flow']['mean']) / statistics['flow']['std']
    log_loss = (log_pred - target[valid]).square().mean()
    return options['flow_mse_weight'] * flow + options['log_mse_weight'] * log_loss
