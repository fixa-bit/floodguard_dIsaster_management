"""Global normalization and ten-day rollouts with no future hydrological states."""
# Model workspace import path.
import sys as _layout_sys
from pathlib import Path as _LayoutPath
for _layout_parent in _LayoutPath(__file__).resolve().parents:
    if (_layout_parent / 'evaluation comparison' / 'common').is_dir():
        _layout_sys.path.insert(0, str(_layout_parent / 'model' / 'model_15 days'))
        _layout_sys.path.insert(0, str(_layout_parent / 'model' / 'model_10 days'))
        _layout_sys.path.insert(0, str(_layout_parent / 'evaluation comparison' / 'common'))
        break

import copy
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset
import yaml


def load_config(path):
    path = Path(path).resolve()
    cfg = yaml.safe_load(path.read_text()); cfg['_root'] = str(path.parent)
    ranges = [set(range(int(cfg['splits'][key][0]), int(cfg['splits'][key][1]) + 1)) for key in ['train', 'validation', 'test']]
    if not all(ranges) or max(ranges[0]) >= min(ranges[1]) or max(ranges[1]) >= min(ranges[2]):
        raise ValueError('Use chronological, disjoint year ranges')
    return cfg


def resolve(cfg, path):
    return (Path(cfg['_root']) / path).resolve()


def schema(cfg):
    original = yaml.safe_load(resolve(cfg, cfg['pretrained']['config']).read_text())
    scale = yaml.safe_load(resolve(cfg, cfg['pretrained']['scaler']).read_text())
    # NeuralHydrology v1.11 preserves dynamic config order and sorts statics.
    dynamic, static = original['dynamic_inputs'], sorted(original['static_attributes'])
    center = [scale['xarray_feature_center']['data_vars'][name]['data'] for name in dynamic]
    std = [scale['xarray_feature_scale']['data_vars'][name]['data'] for name in dynamic]
    result = {'source_config': original, 'dynamic_names': dynamic, 'static_names': static,
              'dynamic_center': center, 'dynamic_scale': std,
              'static_center': [scale['attribute_means'][name] for name in static],
              'static_scale': [scale['attribute_stds'][name] for name in static],
              'flow_center_mm_day': scale['xarray_feature_center']['data_vars']['streamflow']['data'],
              'flow_scale_mm_day': scale['xarray_feature_scale']['data_vars']['streamflow']['data']}
    return result


def normalize(values, center, scale):
    a = np.array(values, dtype=np.float32, copy=True)
    missing = ~np.isfinite(a)
    normalized = (a - np.asarray(center, np.float32)) / np.asarray(scale, np.float32)
    return np.where(missing, 0, normalized).astype(np.float32), missing.astype(np.float32)


def inverse_flow(prediction, normalization, area_km2):
    runoff = np.asarray(prediction) * normalization['flow_scale_mm_day'] + normalization['flow_center_mm_day']
    return np.maximum(0, runoff) * area_km2 / 86.4


class GlobalDataset(Dataset):
    def __init__(self, cfg, split, normalization, reference_statistics, training_noise=False, seed=42):
        self.cfg, self.norm = cfg, normalization
        self.training_noise, self.seed, self.epoch = training_noise, seed, 0
        d = cfg['data']
        if d['other_future_inputs'] != 'persist_issue_day':
            raise ValueError('Other future hydrological states must be persisted from the issue day')
        date_column, basin_column = d['date_column'], d['basin_column']
        frame = pd.read_csv(resolve(cfg, d['daily_file']), parse_dates=[date_column], dtype={basin_column: str})
        frame = frame.rename(columns={date_column: 'date', basin_column: 'basin_id'})
        if frame.date.isna().any() or not frame.date.equals(frame.date.dt.normalize()):
            raise ValueError('Use valid daily date labels')
        frame = frame[frame.basin_id.eq(cfg['data']['basin_id'])].set_index('date').sort_index()
        if frame.index.has_duplicates or frame.empty:
            raise ValueError('Duplicate dates or absent basin')
        self.frame = frame.reindex(pd.date_range(frame.index.min(), frame.index.max()))
        self.dates = self.frame.index
        self.x = self.frame[normalization['dynamic_names']].to_numpy(float)
        self.q = self.frame[cfg['data']['target_column']].to_numpy(float)
        if np.isinf(self.x).any() or np.isinf(self.q).any() or np.any(self.q < 0):
            raise ValueError('Inputs must be finite or NaN; observed discharge must be nonnegative or NaN')
        statics = pd.read_csv(resolve(cfg, d['static_file']), dtype={basin_column: str}).set_index(basin_column)
        if statics.index.has_duplicates:
            raise ValueError('Duplicate static basin IDs')
        self.static_raw = statics.loc[cfg['data']['basin_id'], normalization['static_names']].to_numpy(float)
        self.area_km2 = float(statics.loc[cfg['data']['basin_id'], 'area'])
        if not np.isfinite(self.area_km2) or self.area_km2 <= 0:
            raise ValueError('A known positive catchment area is required for runoff conversion')
        self.static, self.static_mask = normalize(self.static_raw, normalization['static_center'], normalization['static_scale'])
        self.reference_scale = np.asarray(reference_statistics['forecast']['scale'], dtype=float)
        self.forecast_indices = [normalization['dynamic_names'].index(name) for name in cfg['data']['forecast_dynamic_inputs']]
        if cfg['data']['forecast_dynamic_inputs'] != ['total_precipitation_sum', 'temperature_2m_mean']:
            raise ValueError('Reference weather comparison requires rain followed by temperature')
        self.samples = []
        first, last = cfg['splits'][split]
        h, n = cfg['data']['hindcast_length'], cfg['data']['forecast_horizon']
        for position in range(h - 1, len(self.frame) - n):
            dates = self.dates[position + 1:position + n + 1]
            if dates.year.min() >= first and dates.year.max() <= last and np.isfinite(self.q[position + 1:position + n + 1]).any():
                self.samples.append(position)
        if not self.samples:
            raise ValueError(f'No usable {split} target windows')
        self.reference_noise = copy.deepcopy(yaml.safe_load(resolve(cfg, cfg['reference']['config']).read_text())['data']['noise'])

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, index):
        position = self.samples[index]
        h, n = self.cfg['data']['hindcast_length'], self.cfg['data']['forecast_horizon']
        history = self.x[position - h + 1:position + 1]
        future = np.repeat(self.x[position:position + 1], n, axis=0)
        parts = [self.seed, self.epoch, index] if self.training_noise else [self.reference_noise['evaluation_seed'], index]
        rng = np.random.default_rng(np.random.SeedSequence(parts))
        std = self.reference_noise['std_at_lead_1'] + np.arange(n) * self.reference_noise['std_growth_per_lead']
        errors = rng.normal(size=(n, 2)) * std[:, None] * self.reference_scale[None]
        future[:, self.forecast_indices] = self.x[position + 1:position + n + 1, self.forecast_indices] + errors
        history, history_mask = normalize(history, self.norm['dynamic_center'], self.norm['dynamic_scale'])
        future, future_mask = normalize(future, self.norm['dynamic_center'], self.norm['dynamic_scale'])
        q = self.q[position + 1:position + n + 1].copy()
        target = (q * 86.4 / self.area_km2 - self.norm['flow_center_mm_day']) / self.norm['flow_scale_mm_day']
        values = {'history': history, 'future': future, 'static': self.static, 'history_missing': history_mask,
                  'future_missing': future_mask, 'static_missing': self.static_mask, 'target': target}
        result = {name: torch.tensor(value, dtype=torch.float32) for name, value in values.items()}
        result['mask'] = torch.tensor(np.isfinite(q))
        result['index'] = index
        return result

    def issue_date(self, index):
        return self.dates[self.samples[index]]
