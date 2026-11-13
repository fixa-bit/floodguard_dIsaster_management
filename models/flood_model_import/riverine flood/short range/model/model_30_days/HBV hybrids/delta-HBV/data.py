"""Observed-only samples, training statistics, and issued-weather branches."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from _core_data import (DataStore, StreamflowDataset, fit_statistics as core_statistics,
                        inverse_flow, load_config, normalize, public_config, resolve, years)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fit_statistics(store):
    stats = core_statistics(store)
    selected = []
    for basin, frame in store.frames.items():
        training = frame.loc[frame.index.year.isin(years(store.cfg['splits']['train']))]
        pet = training.groupby(training.index.month)['pet_mm'].mean()
        if len(pet) != 12 or not np.isfinite(pet).all():
            raise ValueError('Training-period PET is required in every month')
        stats.setdefault('pet_climatology', {})[basin] = {str(k): float(v) for k, v in pet.items()}
        selected.extend(training.q_cumecs.dropna().tolist())
    stats['flow_mse_scale'] = max(float(np.std(selected)), 1.0)
    stats['flood_threshold_cumecs'] = float(np.quantile(selected, store.cfg['evaluation']['flood_percentile']))
    return stats


class DeltaDataset(StreamflowDataset):
    def __getitem__(self, index):
        item = super().__getitem__(index)
        basin, issue = self.metadata(index)
        n = len(self.d['dynamic_columns'])
        if self.d['dynamic_columns'] != ['rain_era5_mm', 'temperature_c', 'pet_mm']:
            raise ValueError('HBV forcing order must remain precipitation, temperature, PET')
        h = item['history'].numpy()
        f = item['future'].numpy()
        historical = h[:, :n] * np.asarray(self.stats['dynamic']['scale']) + np.asarray(self.stats['dynamic']['center'])
        forecast_pt = f[:, :2] * np.asarray(self.stats['forecast']['scale']) + np.asarray(self.stats['forecast']['center'])
        dates = pd.date_range(issue + pd.Timedelta(days=1), periods=self.d['forecast_horizon'])
        # No future observed PET: use a climatology fitted on training years only.
        pet = np.array([self.stats['pet_climatology'][basin][str(day.month)] for day in dates])
        future = np.column_stack([forecast_pt, pet])
        future[:, [0, 2]] = np.maximum(future[:, [0, 2]], 0)
        forcing = np.concatenate([historical, future]).astype(np.float32)
        forcing[:, [0, 2]] = np.maximum(forcing[:, [0, 2]], 0)
        normalized_future = normalize(future, self.stats['dynamic'])
        # Retain missing indicators from the forecast archive, if present.
        normalized_future[:, n:n + 2] = f[:, 2:4]
        angle = 2 * np.pi * dates.day_of_year.to_numpy() / 365.25
        normalized_future = np.column_stack([normalized_future, np.sin(angle), np.cos(angle)])
        neural = np.concatenate([h, normalized_future]).astype(np.float32)
        return {'forcing': torch.from_numpy(forcing), 'neural': torch.from_numpy(neural),
                'target': item['target'], 'mask': item['mask'], 'index': index}


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
