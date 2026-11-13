"""Correctness tests only; synthetic data provide no accuracy evidence."""
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
from fine_tuned_global_pretrained_lstm.data import GlobalDataset, inverse_flow, load_config, resolve, schema
from fine_tuned_global_pretrained_lstm.finetune import KEYS, check_years, configure_seed, run_finetuning
from fine_tuned_global_pretrained_lstm.model import GlobalPretrainedLSTM, masked_mse
from lstm.train import load_checkpoint


class GlobalTests(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config(ROOT / 'fine_tuned_global_pretrained_lstm/config.yaml')
        configure_seed(self.cfg); self.norm = schema(self.cfg)
        self.parent_path = resolve(self.cfg, self.cfg['pretrained']['checkpoint'])
        self.weights = torch.load(self.parent_path, map_location='cpu', weights_only=True)
        self.reference = load_checkpoint(resolve(self.cfg, self.cfg['reference']['checkpoint']))

    def model(self):
        model = GlobalPretrainedLSTM(self.norm['source_config'])
        model.load_published_weights(self.weights)
        return model

    def test_every_published_tensor_is_loaded_exactly(self):
        model = self.model()
        self.assertEqual(len(self.weights), 8)
        for name, value in self.weights.items():
            self.assertTrue(torch.equal(model.state_dict()[name], value))
        self.assertEqual(int(torch.count_nonzero(model.dynamic_missing.weight)), 0)
        self.assertEqual(int(torch.count_nonzero(model.static_missing.weight)), 0)

    def test_feature_order_matches_neuralhydrology(self):
        self.assertEqual(self.norm['static_names'], sorted(self.norm['source_config']['static_attributes']))
        self.assertEqual(self.norm['dynamic_names'], self.norm['source_config']['dynamic_inputs'])
        self.assertEqual(len(self.norm['static_names']), 51)

    def test_full_sequence_and_state_continuation_agree(self):
        model = self.model().eval()
        past, future, static = torch.randn(2, 8, 14), torch.randn(2, 3, 14), torch.randn(2, 51)
        with torch.no_grad():
            actual = model(past, future, static, torch.zeros_like(past), torch.zeros_like(future), torch.zeros_like(static))
            embedding = model.embedding_net.statics_embedding(static)
            sequence = torch.cat([torch.cat([past, future], dim=1), embedding[:, None].expand(-1, 11, -1)], dim=-1)
            hidden, _ = model.lstm(sequence)
            expected = model.head(hidden[:, -3:]).squeeze(-1)
        torch.testing.assert_close(actual, expected, atol=2e-6, rtol=2e-5)

    def test_nan_targets_are_masked_before_arithmetic(self):
        p = torch.tensor([[2., 99., 4.]], requires_grad=True)
        q = torch.tensor([[1., float('nan'), 2.]])
        loss = masked_mse(p, q, torch.isfinite(q)); self.assertEqual(float(loss.detach()), 2.5)
        loss.backward()
        self.assertTrue(torch.isfinite(p.grad).all()); self.assertEqual(float(p.grad[0, 1]), 0)
        self.assertEqual(float(masked_mse(p, q, torch.zeros_like(q, dtype=torch.bool)).detach()), 0)

    def test_shapes_alignment_and_no_future_soil_or_snow(self):
        ds = GlobalDataset(self.cfg, 'test', self.norm, self.reference['statistics'])
        item = ds[100]; position = ds.samples[100]
        self.assertEqual(tuple(item['history'].shape), (365, 14))
        self.assertEqual(tuple(item['future'].shape), (10, 14))
        raw_past = item['history'].numpy() * np.array(self.norm['dynamic_scale']) + np.array(self.norm['dynamic_center'])
        np.testing.assert_allclose(raw_past, ds.x[position - 364:position + 1], atol=3e-5, rtol=1e-5)
        other = [i for i in range(14) if i not in ds.forecast_indices]
        np.testing.assert_allclose(item['future'][:, other], item['history'][-1:, other].expand(10, -1), atol=1e-6)
        future_before = item['future'].clone()
        ds.x[position + 1:position + 11, other] = 1e8
        torch.testing.assert_close(ds[100]['future'], future_before)
        self.assertTrue((ds.dates[position + 1:position + 11].year == 2022).all())

    def test_real_observations_and_nan_locations_preserved(self):
        original_path = resolve(self.cfg, self.cfg['preparation']['observed_daily_source'])
        digest = hashlib.sha256(original_path.read_bytes()).hexdigest()
        ds = GlobalDataset(self.cfg, 'test', self.norm, self.reference['statistics'])
        original = pd.read_csv(original_path, parse_dates=['date']).set_index('date')['q_cumecs']
        np.testing.assert_array_equal(ds.q, original.reindex(ds.dates).to_numpy())
        for index in [0, 300, len(ds) - 1]:
            item = ds[index]; position = ds.samples[index]
            actual_q = ds.q[position + 1:position + 11]
            np.testing.assert_array_equal(item['mask'], np.isfinite(actual_q))
            restored = inverse_flow(item['target'].numpy(), self.norm, ds.area_km2)
            np.testing.assert_allclose(restored, actual_q, atol=1e-3, rtol=1e-6, equal_nan=True)
        self.assertEqual(hashlib.sha256(original_path.read_bytes()).hexdigest(), digest)

    def test_pretraining_years_cannot_be_called_unseen_test(self):
        cfg = copy.deepcopy(self.cfg); cfg['splits']['test'] = [2020, 2020]
        with self.assertRaisesRegex(ValueError, 'pretraining'):
            check_years(cfg, self.norm['source_config'])

    def test_synthetic_finetune_changes_original_weights_and_saves_checkpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            cfg = copy.deepcopy(self.cfg); folder = Path(temporary)
            dates = pd.date_range('2019-12-20', '2023-12-31')
            values = np.tile(np.array(self.norm['dynamic_center']), (len(dates), 1))
            values += np.sin(np.arange(len(dates))[:, None] / 30) * np.array(self.norm['dynamic_scale']) * .1
            frame = pd.DataFrame(values, columns=self.norm['dynamic_names'])
            frame['date'] = dates; frame['basin_id'] = 'synthetic'
            frame['q_cumecs'] = 1000 + 100 * np.sin(np.arange(len(dates)) / 30)
            frame.loc[::33, 'q_cumecs'] = np.nan
            frame.to_csv(folder / 'daily.csv', index=False, na_rep='NaN')
            static = dict(zip(self.norm['static_names'], self.norm['static_center']))
            static.update(basin_id='synthetic', area=28000)
            pd.DataFrame([static]).to_csv(folder / 'static.csv', index=False)
            for group, keys in [('pretrained', ['checkpoint', 'config', 'scaler']), ('reference', ['checkpoint', 'config'])]:
                for key in keys:
                    cfg[group][key] = str(resolve(self.cfg, cfg[group][key]))
            cfg['_root'] = temporary
            cfg['data'].update(daily_file='daily.csv', static_file='static.csv', basin_id='synthetic', hindcast_length=8, forecast_horizon=3)
            cfg['splits'] = {'train': [2020, 2020], 'validation': [2021, 2021], 'test': [2022, 2022]}
            cfg['training'].update(output_dir='run', epochs=1, batch_size=128)
            path = run_finetuning(cfg); checkpoint = load_checkpoint(path)
            self.assertTrue(any(not torch.equal(value, checkpoint['model_state'][name]) for name, value in self.weights.items()))
            loaded = self.model(); loaded.load_state_dict(checkpoint['model_state'])
            self.assertEqual(checkpoint['local_training_years'], [2020])
            saved = pd.read_csv(folder / 'daily.csv')['q_cumecs']
            np.testing.assert_array_equal(saved.to_numpy(), frame.q_cumecs.to_numpy())
            cfg['training'].update(initial_checkpoint=str(path), output_dir='continued')
            cfg['splits'] = {'train': [2021, 2021], 'validation': [2022, 2022], 'test': [2023, 2023]}
            continued_path = run_finetuning(cfg)
            continued = load_checkpoint(continued_path)
            self.assertEqual(continued['local_training_years'], [2020, 2021])
            self.assertTrue(any(not torch.equal(value, continued['model_state'][name]) for name, value in checkpoint['model_state'].items()))
            cfg['training']['initial_checkpoint'] = str(continued_path)
            cfg['splits'] = {'train': [2020, 2020], 'validation': [2021, 2021], 'test': [2023, 2023]}
            with self.assertRaisesRegex(ValueError, 'earlier checkpoint'):
                run_finetuning(cfg)


if __name__ == '__main__':
    unittest.main()
