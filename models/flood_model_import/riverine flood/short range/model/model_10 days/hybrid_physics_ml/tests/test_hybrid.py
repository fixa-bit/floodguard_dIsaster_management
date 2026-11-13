"""Synthetic correctness checks, not forecasting-accuracy evidence."""
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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from data import load_config
from hybrid_physics_ml.model import HybridPhysicsLSTM, SnowWaterBucket, build_model
from lstm.model import masked_pinball
from lstm.train import load_checkpoint, run_training


class HybridTests(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config(ROOT / 'hybrid_physics_ml/config.yaml')
        self.cfg['model']['dropout'] = 0
        self.cfg['model']['hidden_size'] = 4
        self.stats = {'dynamic': {'center': [0.] * 8, 'scale': [1.] * 8},
                      'forecast': {'center': [0., 0.], 'scale': [1., 1.]}}

    def inputs(self):
        history = torch.zeros(2, 8, 18)
        history[:, :, 0] = 3
        history[:, :, 1] = torch.linspace(-3, 6, 8)
        history[:, :, 2] = 30
        future = torch.zeros(2, 10, 4)
        future[:, :, 0] = 2
        future[:, :, 1] = torch.linspace(0, 6, 10)
        return history, future, torch.empty(2, 0)

    def test_internal_water_balance_and_nonnegative_stores(self):
        bucket = SnowWaterBucket(self.cfg['physics']).double()
        p = torch.tensor([[4., 0., 2., 0., 3.]], dtype=torch.float64)
        t = torch.tensor([[-5., -1., 5., 15., 3.]], dtype=torch.float64)
        initial = torch.tensor([[20., 100., 25.]], dtype=torch.float64)
        values, final, residual = bucket(p, t, initial)
        self.assertTrue((values >= 0).all())
        self.assertTrue((final >= 0).all())
        self.assertLess(float(residual.detach().abs().max()), 1e-10)
        difference = initial.sum() + p.sum() - final.sum() - values[:, :, 4:6].sum()
        self.assertAlmostEqual(float(difference.detach()), 0, places=10)

    def test_no_water_produces_no_runoff(self):
        bucket = SnowWaterBucket(self.cfg['physics'])
        values, final, residual = bucket(torch.zeros(2, 10), torch.full((2, 10), 10.), torch.zeros(2, 3))
        self.assertEqual(float(values.abs().sum().detach()), 0)
        self.assertEqual(float(final.abs().sum().detach()), 0)
        self.assertEqual(float(residual.abs().sum().detach()), 0)

    def test_physics_is_differentiable_and_quantiles_do_not_cross(self):
        model = HybridPhysicsLSTM(self.cfg, 18, 4, 0, self.stats)
        output = model(*self.inputs())
        self.assertEqual(tuple(output.shape), (2, 10, 5))
        self.assertTrue((output.diff(dim=-1) >= 0).all())
        target = torch.ones(2, 10); target[:, 2] = torch.nan
        loss = masked_pinball(output, target, torch.isfinite(target), model.quantiles)
        loss.backward()
        grads = [p.grad for p in model.bucket.parameters()]
        self.assertTrue(all(g is not None and torch.isfinite(g).all() for g in grads))
        self.assertTrue(any(float(g.abs().sum()) > 0 for g in grads))

    def test_future_does_not_change_past_and_carries_issue_state(self):
        model = HybridPhysicsLSTM(self.cfg, 18, 4, 0, self.stats)
        history, future, _ = self.inputs()
        original_history, original_future = history.clone(), future.clone()
        past, prediction, audit = model.physics_features(history, future)
        changed = future.clone(); changed[:, :, 1] += 50
        other_past, _, other_audit = model.physics_features(history, changed)
        torch.testing.assert_close(past, other_past, atol=0, rtol=0)
        torch.testing.assert_close(audit['state_at_issue'], other_audit['state_at_issue'], atol=0, rtol=0)
        direct, _, _ = model.bucket(future[:, :1, 0], future[:, :1, 1], audit['state_at_issue'])
        torch.testing.assert_close(prediction[:, :1], direct)
        torch.testing.assert_close(history, original_history, atol=0, rtol=0)
        torch.testing.assert_close(future, original_future, atol=0, rtol=0)

    def test_checkpoint_training_finetuning_and_observation_preservation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cfg = copy.deepcopy(self.cfg)
            cfg['_root'] = str(root)
            cfg['data'].update(daily_file='daily.csv', hindcast_length=8)
            cfg['splits'] = {'train': [2000, 2000], 'validation': [2001, 2001], 'test': [2002, 2002]}
            cfg['training'].update(epochs=1, batch_size=256, output_dir='train', cpu_threads=1)
            cfg['finetuning'].update(epochs=1, output_dir='fine', freeze_hindcast=True)
            dates = pd.date_range('1999-12-20', '2003-12-31')
            x = np.arange(len(dates), dtype=float)
            frame = pd.DataFrame({c: 2 + np.sin(x / 30) for c in cfg['data']['dynamic_columns']})
            frame['temperature_c'] = 5 * np.sin(x / 30)
            frame['rain_era5_mm'] = frame['rain_chirps_mm']
            frame['q_cumecs'] = 100 + 10 * np.sin(x / 30)
            frame.loc[::33, 'q_cumecs'] = np.nan
            frame['basin_id'] = 'marala'; frame['date'] = dates
            frame.to_csv(root / 'daily.csv', index=False)
            digest = hashlib.sha256((root / 'daily.csv').read_bytes()).hexdigest()
            parent = run_training(cfg, 42, model_factory=build_model)
            first = load_checkpoint(parent)
            fine_cfg = copy.deepcopy(cfg)
            fine_cfg['splits'] = {'train': [2000, 2001], 'validation': [2002, 2002], 'test': [2003, 2003]}
            fine_cfg['finetuning']['recompute_normalization'] = True
            child = run_training(fine_cfg, 42, initial_checkpoint=parent, model_factory=build_model)
            second = load_checkpoint(child)
            self.assertEqual(second['model_family'], 'hybrid_physics_ml')
            torch.testing.assert_close(second['model_state']['dynamic_center'],
                                       torch.tensor(second['statistics']['dynamic']['center'], dtype=torch.float32))
            self.assertTrue(any(not torch.equal(v, second['model_state'][k]) for k, v in first['model_state'].items()))
            self.assertTrue(all(torch.equal(v, second['model_state'][k]) for k, v in first['model_state'].items() if k.startswith('lstm.hindcast.')))
            self.assertEqual(digest, hashlib.sha256((root / 'daily.csv').read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main(verbosity=2)
