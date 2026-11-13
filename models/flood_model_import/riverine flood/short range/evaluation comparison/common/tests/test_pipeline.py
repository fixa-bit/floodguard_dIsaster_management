"""Synthetic correctness tests only. These are NOT evidence of real accuracy."""
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
from data import DataStore, StreamflowDataset, fit_statistics, load_config, normalize
from model import HindcastForecastLSTM, masked_pinball
from train import check_evaluation_years, load_checkpoint, run_training
from ensemble.model import ConvexEnsemble
from evaluate import metrics
from pretrained_multibasin_lstm.train import run_stage


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        cfg = yaml.safe_load((ROOT / 'config.yaml').read_text())
        dates = pd.date_range('1999-12-20', '2003-12-31')
        x = np.arange(len(dates), dtype=float)
        q = 20 + 5 * np.sin(x / 30)
        q[::33] = np.nan
        q[20] = 0
        z = np.cos(x / 20)
        z[::17] = np.nan
        pd.DataFrame({'date': dates, 'basin_id': 'a', 'x': x, 'z': z, 'q_cumecs': q}).to_csv(self.root / 'daily.csv', index=False)
        cfg['data'].update(daily_file='daily.csv', default_basin_id='a', dynamic_columns=['x', 'z'],
                           hindcast_length=8, forecast_horizon=3, forecast_columns=['forecast_x'],
                           reanalysis_columns=['x'], calendar_features=False)
        cfg['data']['noise'].update(std_at_lead_1=0, std_growth_per_lead=0)
        cfg['splits'] = {'train': [2000, 2000], 'validation': [2001, 2001], 'test': [2002, 2002]}
        cfg['model'].update(hidden_size=4, lead_embedding_size=2, dropout=0)
        cfg['training'].update(output_dir='run', epochs=1, patience=1, batch_size=128, cpu_threads=1)
        cfg['finetuning'].update(output_dir='fine', epochs=1)
        (self.root / 'config.yaml').write_text(yaml.safe_dump(cfg))
        self.cfg = load_config(self.root / 'config.yaml')

    def dataset(self, split='train'):
        store = DataStore(self.cfg)
        return store, StreamflowDataset(store, split, fit_statistics(store))

    def test_window_shapes_alignment_and_split_boundaries(self):
        store, dataset = self.dataset()
        sample_index = next(i for i in range(len(dataset)) if dataset.metadata(i)[1] == pd.Timestamp('2000-06-01'))
        item = dataset[sample_index]
        self.assertEqual(tuple(item['history'].shape), (8, 4))
        self.assertEqual(tuple(item['future'].shape), (3, 2))
        self.assertEqual(tuple(item['target'].shape), (3,))
        basin, position = dataset.samples[sample_index]
        frame = store.frames[basin]
        stats = dataset.stats['dynamic']
        recovered = item['history'][:, 0].numpy() * stats['scale'][0] + stats['center'][0]
        np.testing.assert_allclose(recovered, frame['x'].iloc[position - 7:position + 1], atol=1e-4)
        future = item['future'][:, 0].numpy() * dataset.stats['forecast']['scale'][0] + dataset.stats['forecast']['center'][0]
        np.testing.assert_allclose(future, frame['x'].iloc[position + 1:position + 4], atol=1e-4)
        for _, position in dataset.samples:
            self.assertTrue((frame.index[position + 1:position + 4].year == 2000).all())

    def test_masked_loss_ignores_missing_targets_and_has_finite_gradient(self):
        pred = torch.zeros(1, 3, 3, requires_grad=True)
        target = torch.tensor([[1.0, float('nan'), 3.0]])
        mask = torch.isfinite(target)
        loss = masked_pinball(pred, target, mask, [0.1, 0.5, 0.9])
        self.assertAlmostEqual(float(loss.detach()), 1.0)
        changed = pred.detach().clone(); changed[:, 1] = 1e9
        self.assertEqual(float(masked_pinball(changed, target, mask, [0.1, 0.5, 0.9])), float(loss.detach()))
        loss.backward()
        self.assertTrue(torch.isfinite(pred.grad).all())
        self.assertEqual(float(pred.grad[:, 1].abs().sum()), 0)

    def test_quantiles_never_cross(self):
        model = HindcastForecastLSTM(self.cfg, 4, 2)
        prediction = model(torch.randn(4, 8, 4), torch.randn(4, 3, 2), torch.empty(4, 0))
        self.assertEqual(tuple(prediction.shape), (4, 3, 5))
        self.assertTrue((prediction.diff(dim=-1) >= 0).all())

    def test_observations_and_files_never_modified(self):
        path = self.root / 'daily.csv'
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        store, dataset = self.dataset()
        original = store.frames['a']['q_cumecs'].copy(deep=True)
        for index in range(len(dataset)):
            dataset[index]
        pd.testing.assert_series_equal(original, store.frames['a']['q_cumecs'])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        self.assertTrue(original.eq(0).any())

    def test_training_statistics_ignore_test_and_validation(self):
        store = DataStore(self.cfg)
        before = fit_statistics(store)
        later = store.frames['a'].index.year >= 2001
        store.frames['a'].loc[later, ['x', 'z', 'q_cumecs']] = 1e12
        after = fit_statistics(store)
        self.assertEqual(before, after)

    def test_missing_inputs_do_not_remove_observed_target_samples(self):
        store = DataStore(self.cfg)
        index = store.frames['a'].index.get_loc(pd.Timestamp('2000-06-01'))
        store.frames['a'].iloc[index - 7:index + 1, store.frames['a'].columns.get_indexer(['x', 'z'])] = np.nan
        dataset = StreamflowDataset(store, 'train', fit_statistics(store))
        sample = next(i for i, (_, pos) in enumerate(dataset.samples) if pos == index)
        self.assertTrue(dataset[sample]['history'][:, 2:].eq(1).all())
        self.assertTrue(dataset[sample]['history'][:, :2].eq(0).all())

    def test_all_missing_targets_skipped_individual_nan_retained(self):
        store = DataStore(self.cfg)
        i = store.frames['a'].index.get_loc(pd.Timestamp('2000-06-01'))
        col = store.frames['a'].columns.get_loc('q_cumecs')
        store.frames['a'].iloc[i + 1:i + 4, col] = np.nan
        stats = fit_statistics(store)
        dataset = StreamflowDataset(store, 'train', stats)
        self.assertNotIn(('a', i), dataset.samples)
        store.frames['a'].iloc[i + 2, col] = 12.0
        dataset = StreamflowDataset(store, 'train', stats)
        index = dataset.samples.index(('a', i))
        self.assertEqual(dataset[index]['mask'].tolist(), [False, True, False])
        self.assertTrue(torch.isnan(dataset[index]['target'][0]))

    def test_archived_forecasts_align_by_issue_and_lead(self):
        pd.DataFrame({'date': ['2000-06-01'] * 2, 'basin_id': ['a'] * 2, 'lead_day': [1, 2],
                      'forecast_x': [101.0, 202.0]}).to_csv(self.root / 'forecast.csv', index=False)
        self.cfg['data'].update(forecast_mode='archived_forecast', forecast_file='forecast.csv')
        store, dataset = self.dataset()
        index = next(i for i in range(len(dataset)) if dataset.metadata(i)[1] == pd.Timestamp('2000-06-01'))
        item = dataset[index]
        stats = dataset.stats['forecast']
        restored = item['future'][:2, 0].numpy() * stats['scale'][0] + stats['center'][0]
        np.testing.assert_allclose(restored, [101, 202])
        self.assertEqual(item['future'][:, 1].tolist(), [0, 0, 1])
        self.assertTrue(dataset[0]['future'][:, 1].eq(1).all())

    def test_reanalysis_noise_is_reproducible(self):
        store, dataset = self.dataset()
        self.cfg['data']['noise'].update(std_at_lead_1=0.2, std_growth_per_lead=0.1)
        train = StreamflowDataset(store, 'train', dataset.stats, training_noise=True, seed=42)
        first = train[0]['future'].clone()
        self.assertTrue(torch.equal(first, train[0]['future']))
        train.epoch = 1
        self.assertFalse(torch.equal(first, train[0]['future']))
        self.assertTrue(torch.equal(dataset[0]['future'], dataset[0]['future']))

    def test_finetuning_loads_and_changes_weights(self):
        original = run_training(self.cfg, 42)
        before = load_checkpoint(original)
        fine_cfg = copy.deepcopy(self.cfg)
        fine_cfg['splits'] = {'train': [2000, 2001], 'validation': [2002, 2002], 'test': [2003, 2003]}
        fine_cfg['finetuning']['freeze_hindcast'] = True
        updated = run_training(fine_cfg, 42, original)
        after = load_checkpoint(updated)
        self.assertEqual(before['statistics'], after['statistics'])
        self.assertEqual(after['training_years'], [2000, 2001])
        self.assertTrue(any(not torch.equal(v, after['model_state'][k]) for k, v in before['model_state'].items()))
        self.assertTrue(all(torch.equal(v, after['model_state'][k]) for k, v in before['model_state'].items() if k.startswith('hindcast.')))
        invalid = copy.deepcopy(fine_cfg); invalid['splits']['test'] = [2000, 2000]
        with self.assertRaises(ValueError):
            check_evaluation_years(invalid, after)

    def test_multiple_basins_never_mix_windows(self):
        path = self.root / 'daily.csv'
        frame = pd.read_csv(path)
        second = frame.copy(); second['basin_id'] = 'b'; second['x'] += 100000
        pd.concat([frame, second]).to_csv(path, index=False)
        store, dataset = self.dataset()
        self.assertEqual(set(store.frames), {'a', 'b'})
        self.assertTrue(any(b == 'a' for b, _ in dataset.samples))
        self.assertTrue(any(b == 'b' for b, _ in dataset.samples))

    def test_numeric_basin_ids_keep_leading_zeros(self):
        path = self.root / 'daily.csv'
        frame = pd.read_csv(path)
        frame['basin_id'] = '01022500'
        frame.to_csv(path, index=False)
        store, dataset = self.dataset()
        self.assertEqual(set(store.frames), {'01022500'})
        self.assertEqual(dataset.metadata(0)[0], '01022500')

    def test_multibasin_pretraining_rejects_single_basin(self):
        workflow = {'_root': self.root, 'stages': {'pretrain_config': 'config.yaml'}}
        with self.assertRaisesRegex(ValueError, 'at least two observed donor basins'):
            run_stage(workflow, 'pretrain')

    def test_ensemble_weights_are_convex_and_ignore_missing_targets(self):
        target = np.arange(1, 13, dtype=float).reshape(6, 2)
        target[0, 0] = np.nan
        predictions = {'a': np.arange(1, 13, dtype=float).reshape(6, 2),
                       'b': np.arange(1, 13, dtype=float).reshape(6, 2) * 2}
        blend = ConvexEnsemble({'members': ['a', 'b'], 'fit_validation_weights': True}).fit(predictions, target)
        weights = np.asarray(blend.weights)
        self.assertTrue((weights >= 0).all())
        np.testing.assert_allclose(weights.sum(axis=1), 1)
        before = weights.copy()
        result = blend.predict({'a': predictions['a'] * 3, 'b': predictions['b'] * 4})
        np.testing.assert_array_equal(blend.weights, before)
        self.assertEqual(result.shape, target.shape)

    def test_metric_values_for_perfect_forecast(self):
        result = metrics([1, 2, 3, 4], [1, 2, 3, 4], 3, 3)
        self.assertEqual(result['NSE'], 1)
        self.assertEqual(result['KGE'], 1)
        self.assertEqual(result['PBIAS_pct'], 0)
        self.assertEqual(result['peak_MAPE_pct'], 0)
        self.assertEqual(result['flood_hit_rate'], 1)
        self.assertEqual(result['false_alarm_rate'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
