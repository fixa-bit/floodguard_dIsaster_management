"""Synthetic implementation checks only; accuracy uses real observed test flow."""
import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from data import DataStore, StreamflowDataset, fit_statistics, load_config
from model import HindcastForecastLSTM, masked_pinball
from _training import run_training, load_checkpoint


class PipelineTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        dates = pd.date_range('2015-01-01', '2024-12-31')
        rng = np.random.default_rng(42)
        frame = pd.DataFrame({'date': dates, 'basin_id': 'marala'})
        cfg = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8'))
        for column in set(cfg['data']['dynamic_columns'] + cfg['data']['reanalysis_columns']):
            frame[column] = rng.uniform(1, 10, len(dates))
        frame['q_cumecs'] = 100 + 50 * np.sin(np.arange(len(dates)) / 80) + rng.uniform(0, 20, len(dates))
        frame.loc[dates.isin(pd.to_datetime(['2018-08-10', '2023-06-15'])), 'q_cumecs'] = np.nan
        self.path = self.root / 'daily.csv'
        frame.to_csv(self.path, index=False)
        cfg['data']['daily_file'] = 'daily.csv'
        cfg['training'].update(output_dir='run', epochs=1, batch_size=128, patience=1)
        cfg['finetuning'].update(output_dir='fine', epochs=1, recompute_normalization=False)
        cfg['model'].update(hidden_size=8, lead_embedding_size=2)
        self.config_path = self.root / 'config.yaml'
        self.config_path.write_text(yaml.safe_dump(cfg), encoding='utf-8')
        self.cfg = load_config(self.config_path)
        self.store = DataStore(self.cfg)
        self.stats = fit_statistics(self.store)

    def test_thirty_lead_shapes_and_window_alignment(self):
        dataset = StreamflowDataset(self.store, 'test', self.stats)
        item = dataset[0]
        self.assertEqual(tuple(item['history'].shape), (365, 20))
        self.assertEqual(tuple(item['future'].shape), (30, 4))
        self.assertEqual(tuple(item['target'].shape), (30,))
        basin, issue = dataset.metadata(0)
        first = self.store.frames[basin].loc[issue - pd.Timedelta(days=364), self.cfg['data']['dynamic_columns'][0]]
        expected = (first - self.stats['dynamic']['center'][0]) / self.stats['dynamic']['scale'][0]
        self.assertAlmostEqual(float(item['history'][0, 0]), expected, places=5)
        target_date = issue + pd.Timedelta(days=30)
        q = self.store.frames[basin].loc[target_date, 'q_cumecs']
        expected_target = (np.log1p(q) - self.stats['flow']['mean']) / self.stats['flow']['std']
        self.assertAlmostEqual(float(item['target'][29]), expected_target, places=5)

    def test_masked_loss_ignores_missing_targets(self):
        pred = torch.zeros(1, 30, 5, requires_grad=True)
        target = torch.zeros(1, 30)
        target[0, 3] = float('nan')
        mask = torch.isfinite(target)
        a = masked_pinball(pred, target, mask, self.cfg['model']['quantiles'])
        target[0, 3] = 1e9
        b = masked_pinball(pred, target, mask, self.cfg['model']['quantiles'])
        torch.testing.assert_close(a, b)
        a.backward()
        self.assertEqual(float(pred.grad[0, 3].abs().sum()), 0.)

    def test_quantiles_never_cross(self):
        dataset = StreamflowDataset(self.store, 'test', self.stats)
        model = HindcastForecastLSTM(self.cfg, *dataset.dimensions())
        item = dataset[0]
        result = model(*(item[k].unsqueeze(0) for k in ('history', 'future', 'static')))
        self.assertEqual(tuple(result.shape), (1, 30, 5))
        self.assertTrue(bool((result.diff(dim=-1) >= 0).all()))

    def test_past_discharge_uses_issue_day_and_missing_indicator(self):
        dataset = StreamflowDataset(self.store, 'train', self.stats)
        frame = self.store.frames['marala']
        position = frame.index.get_loc(pd.Timestamp('2018-08-10'))
        item = dataset[dataset.samples.index(('marala', position))]
        column = 2 * len(self.cfg['data']['dynamic_columns'])
        self.assertEqual(float(item['history'][-1, column + 1]), 1.)
        expected_fill = (self.stats['flow']['training_log_mean'] - self.stats['flow']['mean']) / self.stats['flow']['std']
        self.assertAlmostEqual(float(item['history'][-1, column]), expected_fill, places=5)
        previous = frame.q_cumecs.iloc[position - 1]
        expected = (np.log1p(previous) - self.stats['flow']['mean']) / self.stats['flow']['std']
        self.assertAlmostEqual(float(item['history'][-2, column]), expected, places=5)
        self.assertEqual(float(item['history'][-2, column + 1]), 0.)

    def test_future_observed_discharge_never_enters_inputs(self):
        dataset = StreamflowDataset(self.store, 'test', self.stats)
        before = dataset[0]
        basin, position = dataset.samples[0]
        changed = copy.deepcopy(self.store)
        dates = changed.frames[basin].index[position + 1:position + 31]
        observed_dates = dates[changed.frames[basin].loc[dates, 'q_cumecs'].notna()]
        changed.frames[basin].loc[observed_dates, 'q_cumecs'] = 1e9
        after_dataset = StreamflowDataset(changed, 'test', self.stats)
        self.assertEqual(dataset.samples, after_dataset.samples)
        after = after_dataset[0]
        torch.testing.assert_close(before['history'], after['history'])
        torch.testing.assert_close(before['future'], after['future'])
        self.assertFalse(torch.equal(before['target'], after['target']))

    def test_weather_noise_and_targets_match_weather_only_variant(self):
        reference_cfg = copy.deepcopy(self.cfg)
        reference_cfg['data']['past_discharge'] = False
        reference_store = DataStore(reference_cfg)
        reference_stats = fit_statistics(reference_store)
        reference = StreamflowDataset(reference_store, 'test', reference_stats)
        current = StreamflowDataset(self.store, 'test', self.stats)
        self.assertEqual(reference.samples, current.samples)
        count = 2 * len(self.cfg['data']['dynamic_columns'])
        for index in (0, len(current) // 2, len(current) - 1):
            before, after = reference[index], current[index]
            projected = torch.cat([after['history'][:, :count], after['history'][:, -2:]], dim=-1)
            torch.testing.assert_close(before['history'], projected)
            torch.testing.assert_close(before['future'], after['future'])
            torch.testing.assert_close(before['target'], after['target'], equal_nan=True)
            torch.testing.assert_close(before['mask'], after['mask'])

    def test_statistics_ignore_validation_and_test(self):
        changed = copy.deepcopy(self.store)
        for frame in changed.frames.values():
            frame.loc[frame.index.year >= 2021, self.cfg['data']['dynamic_columns'] + ['q_cumecs']] = 1e8
        self.assertEqual(self.stats, fit_statistics(changed))

    def test_observations_and_source_bytes_never_modified(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        q = self.store.frames['marala'].q_cumecs.to_numpy(copy=True)
        dataset = StreamflowDataset(self.store, 'test', self.stats)
        _ = dataset[0]
        np.testing.assert_array_equal(q, self.store.frames['marala'].q_cumecs.to_numpy())
        self.assertEqual(before, hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_training_and_finetuning_checkpoint_changes_weights(self):
        cfg = copy.deepcopy(self.cfg)
        cfg['data']['hindcast_length'] = 7
        cfg['splits'] = {'train': [2018, 2018], 'validation': [2021, 2021], 'test': [2022, 2024]}
        first = run_training(cfg, 42)
        before = load_checkpoint(first)
        second = run_training(cfg, 42, initial_checkpoint=first)
        after = load_checkpoint(second)
        self.assertTrue(any(not torch.equal(before['model_state'][k], after['model_state'][k]) for k in before['model_state']))
        self.assertEqual(after['config']['data']['forecast_horizon'], 30)


if __name__ == '__main__':
    unittest.main()
