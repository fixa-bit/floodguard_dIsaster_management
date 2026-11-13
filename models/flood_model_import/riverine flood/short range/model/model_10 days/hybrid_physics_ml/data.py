"""Shared observed-only samples, with explicit physics feature mappings."""
# Model workspace import path.
import sys as _layout_sys
from pathlib import Path as _LayoutPath
for _layout_parent in _LayoutPath(__file__).resolve().parents:
    if (_layout_parent / 'evaluation comparison' / 'common').is_dir():
        _layout_sys.path.insert(0, str(_layout_parent / 'model' / 'model_15 days'))
        _layout_sys.path.insert(0, str(_layout_parent / 'model' / 'model_10 days'))
        _layout_sys.path.insert(0, str(_layout_parent / 'evaluation comparison' / 'common'))
        break

from data import DataStore, StreamflowDataset, fit_statistics, load_config, resolve


def validate_physics_inputs(cfg):
    d, p = cfg['data'], cfg['physics']
    for name in ('precipitation', 'temperature', 'swe'):
        if p['history_columns'][name] not in d['dynamic_columns']:
            raise ValueError(f'Physics history {name} is not a configured input')
    for name in ('precipitation', 'temperature'):
        if p['forecast_columns'][name] not in d['forecast_columns']:
            raise ValueError(f'Physics forecast {name} is not a configured input')
    if p['phase_transition_width_c'] <= 0:
        raise ValueError('Snow/rain transition width must be positive')
    if min(p['initial_soil_mm'], p['initial_groundwater_mm']) < 0:
        raise ValueError('Initial water stores cannot be negative')
    if p['gradient_history_days'] < 1:
        raise ValueError('At least one differentiable history day is required')
