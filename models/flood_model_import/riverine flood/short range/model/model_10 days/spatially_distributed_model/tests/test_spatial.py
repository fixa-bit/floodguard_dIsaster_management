"""Synthetic code checks only; never evidence of forecasting accuracy."""
# Horizon-group test imports.
import sys as _test_sys
from pathlib import Path as _TestPath
for _test_parent in _TestPath(__file__).resolve().parents:
    if (_test_parent / 'evaluation comparison' / 'common').is_dir():
        _test_sys.path.insert(0, str(_test_parent / 'model' / 'model_15 days'))
        _test_sys.path.insert(0, str(_test_parent / 'model' / 'model_10 days'))
        _test_sys.path.insert(0, str(_test_parent / 'evaluation comparison' / 'common'))
        break

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from data import DataStore, fit_statistics
from lstm.train import load_checkpoint, run_training
from spatially_distributed_model.data import load_spatial_config, SpatialDataset
from spatially_distributed_model.model import build_model


class SpatialTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        cfg = yaml.safe_load((ROOT / 'spatially_distributed_model/config.yaml').read_text())
        dates = pd.date_range('1999-12-20', '2003-12-31')
        x = np.arange(len(dates), dtype=float)
        frame = pd.DataFrame({'date': dates, 'basin_id': 'marala', 'q_cumecs': 100 + 10 * np.sin(x / 30)})
        frame.loc[::33, 'q_cumecs'] = np.nan
        weights = [.1, .2, .3, .4]
        for i, band in enumerate(cfg['spatial']['band_ids']):
            for j, variable in enumerate(cfg['spatial']['history_variables']):
                frame[f'{band}_{variable}'] = i + j + 1 + .1 * np.sin(x / 30)
        for variable in cfg['spatial']['history_variables']:
            frame[f'mean_{variable}'] = sum(weights[i] * frame[f'{band}_{variable}'] for i, band in enumerate(cfg['spatial']['band_ids']))
        frame.to_csv(self.root / 'daily.csv', index=False)
        (self.root / 'metadata.json').write_text(json.dumps({'area_fractions': weights}))
        cfg['data'].update(daily_file='daily.csv', hindcast_length=8, forecast_horizon=3)
        cfg['spatial']['metadata_file'] = 'metadata.json'
        cfg['splits'] = {'train': [2000, 2000], 'validation': [2001, 2001], 'test': [2002, 2002]}
        cfg['model'].update(hidden_size=4, dropout=0)
        cfg['training'].update(output_dir='run', epochs=1, batch_size=128, cpu_threads=1)
        (self.root / 'config.yaml').write_text(yaml.safe_dump(cfg))
        mean = copy.deepcopy(cfg)
        mean['spatial']['mode'] = 'catchment_mean'
        mean['data'].update(dynamic_columns=[f'mean_{v}' for v in cfg['spatial']['history_variables']],
                            forecast_columns=[f'mean_{v}' for v in cfg['spatial']['forecast_variables']],
                            reanalysis_columns=[f'mean_{v}' for v in cfg['spatial']['forecast_variables']])
        (self.root / 'mean.yaml').write_text(yaml.safe_dump(mean))
        self.cfg = load_spatial_config(self.root / 'config.yaml')
        self.mean_cfg = load_spatial_config(self.root / 'mean.yaml')

    def dataset(self, cfg=None):
        store = DataStore(cfg or self.cfg)
        return SpatialDataset(store, 'train', fit_statistics(store))

    def test_shapes_and_historical_alignment(self):
        ds = self.dataset(); item = ds[0]
        self.assertEqual(tuple(item['history'].shape), (8, 34))
        self.assertEqual(tuple(item['future'].shape), (3, 16))
        self.assertEqual(tuple(item['target'].shape), (3,))
        basin, position = ds.samples[0]
        recovered = item['history'][:, 0].numpy() * ds.stats['dynamic']['scale'][0] + ds.stats['dynamic']['center'][0]
        np.testing.assert_allclose(recovered, ds.store.frames[basin].iloc[position - 7:position + 1]['b0_precipitation_mm'], atol=1e-5)

    def test_mean_control_has_identical_physical_forecast_errors(self):
        spatial, mean = self.dataset(), self.dataset(self.mean_cfg)
        self.assertEqual(spatial.samples, mean.samples)
        for index in [0, 50, 200]:
            a, b = spatial[index]['future'].numpy(), mean[index]['future'].numpy()
            a = a[:, :8] * np.asarray(spatial.stats['forecast']['scale']) + np.asarray(spatial.stats['forecast']['center'])
            b = b[:, :2] * np.asarray(mean.stats['forecast']['scale']) + np.asarray(mean.stats['forecast']['center'])
            averaged = np.sum(a.reshape(3, 4, 2) * np.asarray(self.cfg['spatial']['area_weights'])[None, :, None], axis=1)
            np.testing.assert_allclose(averaged, b, atol=1e-5)

    def test_distinct_bands_affect_predictions_and_quantiles_do_not_cross(self):
        torch.manual_seed(42)
        ds = self.dataset(); item = ds[0]
        model = build_model(self.cfg, ds.dimensions(), ds.stats).eval()
        history, future, static = (item[k][None] for k in ('history', 'future', 'static'))
        first = model(history, future, static)
        changed = history.clone(); changed[:, :, 0] += 2
        second = model(changed, future, static)
        self.assertFalse(torch.allclose(first, second))
        self.assertTrue((first.diff(dim=-1) >= 0).all())
        self.assertEqual(tuple(first.shape), (1, 3, 5))

    def test_future_does_not_change_historical_encoder_states(self):
        ds = self.dataset(); item = ds[0]
        model = build_model(self.cfg, ds.dimensions(), ds.stats).eval()
        states = []
        hook = model.hindcast[0].register_forward_hook(lambda module, inputs, output: states.append(output[1][0].detach().clone()))
        h, f, s = (item[k][None] for k in ('history', 'future', 'static'))
        model(h, f, s); model(h, f + 10, s); hook.remove()
        torch.testing.assert_close(states[0], states[1], atol=0, rtol=0)

    def test_missing_bands_are_flagged_and_target_source_is_unchanged(self):
        path = self.root / 'daily.csv'; digest = hashlib.sha256(path.read_bytes()).hexdigest()
        spatial, mean = self.dataset(), self.dataset(self.mean_cfg)
        basin, position = spatial.samples[0]
        for ds in [spatial, mean]:
            frame = ds.store.frames[basin]
            frame.iloc[position + 1, frame.columns.get_loc('b0_precipitation_mm')] = np.nan
        self.assertEqual(float(spatial[0]['future'][0, 8]), 1)
        self.assertEqual(float(mean[0]['future'][0, 2]), 1)
        self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())
        torch.testing.assert_close(spatial[0]['target'], mean[0]['target'], equal_nan=True)

    def test_shared_trainer_saves_and_loads_spatial_checkpoint(self):
        path = run_training(self.cfg, 42, model_factory=build_model, dataset_factory=SpatialDataset)
        checkpoint = load_checkpoint(path)
        ds = self.dataset()
        model = build_model(self.cfg, ds.dimensions(), checkpoint['statistics'])
        model.load_state_dict(checkpoint['model_state'])
        self.assertEqual(checkpoint['model_family'], 'elevation_band_lstm')
        self.assertEqual(checkpoint['training_years'], [2000])


if __name__ == '__main__':
    unittest.main(verbosity=2)
