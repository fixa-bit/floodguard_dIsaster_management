"""Same observed-only windows, with historical forecast covariates for basis models."""
import numpy as np
import torch

from .core.data import StreamflowDataset, normalize


class BasisDataset(StreamflowDataset):
    def __init__(self, store, split, stats, training_noise=False, seed=42):
        super().__init__(store, split, stats, training_noise, seed)
        if not self.d['past_discharge']:
            raise ValueError('These autoregressive experiments require past_discharge: true')
        self.forecast_history = {}
        for basin, frame in store.frames.items():
            # All values are at/before the issue day, using training-only statistics.
            raw = frame[self.d['reanalysis_columns']].to_numpy(float)
            self.forecast_history[basin] = normalize(raw, stats['forecast'])

    def __getitem__(self, index):
        item = super().__getitem__(index)
        basin, position = self.samples[index]
        start = position - self.d['hindcast_length'] + 1
        past_weather = self.forecast_history[basin][start:position + 1]
        item['history'] = torch.cat([item['history'], torch.tensor(past_weather, dtype=torch.float32)], dim=-1)
        return item

