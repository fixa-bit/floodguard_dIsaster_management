"""Elevation-band samples and identical physical forecast errors for controls."""
import hashlib
import json

import numpy as np
import torch

from data import DataStore, StreamflowDataset, load_config, normalize, resolve


def load_spatial_config(path):
    cfg = load_config(path)
    metadata_path = resolve(cfg, cfg['spatial']['metadata_file'])
    metadata = json.loads(metadata_path.read_text())
    weights = np.asarray(metadata['area_fractions'], dtype=float)
    if len(weights) != len(cfg['spatial']['band_ids']) or (weights <= 0).any() or not np.isclose(weights.sum(), 1):
        raise ValueError('Invalid elevation-band area weights')
    cfg['spatial']['area_weights'] = weights.tolist()
    cfg['spatial']['metadata_sha256'] = hashlib.sha256(metadata_path.read_bytes()).hexdigest()
    return cfg


class SpatialDataset(StreamflowDataset):
    def __getitem__(self, index):
        item = super().__getitem__(index)
        if self.d['forecast_mode'] == 'archived_forecast':
            return item
        options = self.cfg['spatial']
        basin, position = self.samples[index]
        horizon = self.d['forecast_horizon']
        variables = options['forecast_variables']
        columns = [f'{band}_{variable}' for band in options['band_ids'] for variable in variables]
        frame = self.store.frames[basin]
        raw = frame[columns].iloc[position + 1:position + 1 + horizon].to_numpy(float).reshape(horizon, len(options['band_ids']), len(variables))
        # One physical error per lead/variable is shared by the elevation bands.
        # Averaging these same forecasts gives the control exactly matching errors.
        noise = options['forecast_noise']
        parts = [self.seed, self.epoch, index] if self.training_noise else [self.d['noise']['evaluation_seed'], index]
        rng = np.random.default_rng(np.random.SeedSequence(parts))
        std = np.asarray(noise['std_at_lead_1']) + np.arange(horizon)[:, None] * np.asarray(noise['std_growth_per_lead'])
        errors = rng.normal(size=(horizon, len(variables))) * std
        raw = raw + errors[:, None, :]
        if noise['clip_precipitation_at_zero']:
            raw[:, :, variables.index('precipitation_mm')] = np.maximum(0, raw[:, :, variables.index('precipitation_mm')])
        if options['mode'] == 'catchment_mean':
            # np.sum retains NaN if any required band is absent; no partial renormalization.
            raw = np.sum(raw * np.asarray(options['area_weights'])[None, :, None], axis=1)
        else:
            raw = raw.reshape(horizon, -1)
        item['future'] = torch.tensor(normalize(raw, self.stats['forecast']), dtype=torch.float32)
        return item
