"""Synthetic correctness checks, never evidence of real forecast accuracy."""
import ast
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.nn import functional as F
import yaml

from .core.data import DataStore, fit_statistics, load_config, normalize
from .core.lstm_model import masked_pinball
from .core.training import load_checkpoint, run_training, seed_everything
from _nhits.data import BasisDataset
from _nhits.model import build_model


ROOT = Path(__file__).resolve().parents[2]
MODEL_ROOT = Path(__file__).resolve().parents[1]


class BasisTests(unittest.TestCase):
    family = None

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        cfg = yaml.safe_load((MODEL_ROOT / 'config.yaml').read_text())
        dates = pd.date_range('2019-12-15', '2022-12-31'); index = np.arange(len(dates), dtype=float)
        q = 50 + 10 * np.sin(index / 30); q[::23] = np.nan; q[20] = 0
        x = np.cos(index / 50); x[::19] = np.nan
        frame = pd.DataFrame({'date': dates, 'basin_id': 'a', 'x': x, 'z': index / 100, 'q_cumecs': q})
        frame.to_csv(self.root / 'daily.csv', index=False, na_rep='NaN')
        cfg['data'].update(daily_file='daily.csv', default_basin_id='a', dynamic_columns=['x', 'z'],
                           reanalysis_columns=['x', 'z'], forecast_columns=['forecast_x', 'forecast_z'],
                           hindcast_length=8, forecast_horizon=3)
        cfg['splits'] = {'train': [2020, 2020], 'validation': [2021, 2021], 'test': [2022, 2022]}
        cfg['architecture'].update(hidden_units=8, pooling_kernels=[4, 2, 1])
        cfg['model']['dropout'] = 0
        cfg['training'].update(output_dir='run', epochs=1, batch_size=128, cpu_threads=1)
        (self.root / 'config.yaml').write_text(yaml.safe_dump(cfg))
        self.cfg = load_config(self.root / 'config.yaml')
        seed_everything(42, 1)
        self.store = DataStore(self.cfg); self.stats = fit_statistics(self.store)
        self.dataset = BasisDataset(self.store, 'test', self.stats)

    def test_shapes_alignment_and_future_weather(self):
        ds = self.dataset; item = ds[120]; basin, position = ds.samples[120]
        self.assertEqual(tuple(item['history'].shape), (8, 12))
        self.assertEqual(tuple(item['future'].shape), (3, 4))
        frame = self.store.frames[basin]
        expected = normalize(frame[['x', 'z']].iloc[position - 7:position + 1].to_numpy(), self.stats['forecast'])
        np.testing.assert_allclose(item['history'][:, -4:], expected, atol=1e-6)
        self.assertTrue((frame.index[position + 1:position + 4].year == 2022).all())

    def test_quantiles_ordered_with_finite_masked_gradients(self):
        items = [self.dataset[i] for i in [0, 40, 100]]
        batch = {key: torch.stack([r[key] for r in items]) for key in ['history', 'future', 'static', 'target', 'mask']}
        model = build_model(self.cfg, self.dataset.dimensions(), self.stats)
        prediction = model(*(batch[k] for k in ['history', 'future', 'static']))
        self.assertEqual(tuple(prediction.shape), (3, 3, 5))
        self.assertTrue((prediction.diff(dim=-1) >= 0).all())
        batch['target'][0, 0] = float('nan'); batch['mask'][0, 0] = False
        loss = masked_pinball(prediction, batch['target'], batch['mask'], model.quantiles)
        loss.backward()
        self.assertTrue(torch.isfinite(loss))
        self.assertTrue(all(torch.isfinite(p.grad).all() for p in model.parameters() if p.grad is not None))

    def test_missing_targets_have_no_loss_effect(self):
        target = torch.tensor([[1., float('nan'), 2.]])
        prediction = torch.zeros(1, 3, 5, requires_grad=True)
        mask = torch.isfinite(target)
        a = masked_pinball(prediction, target, mask, [.05, .25, .5, .75, .95])
        changed = prediction.detach().clone(); changed[:, 1] = 1e20
        b = masked_pinball(changed, target, mask, [.05, .25, .5, .75, .95])
        self.assertEqual(float(a.detach()), float(b))
        a.backward(); self.assertEqual(float(prediction.grad[:, 1].abs().sum()), 0)

    def test_future_discharge_never_enters_predictors(self):
        ds = self.dataset; index = 100; before = ds[index]
        basin, position = ds.samples[index]
        ds.arrays[basin]['q'][position + 1:position + 4] = 1e8
        after = ds[index]
        torch.testing.assert_close(before['history'], after['history'])
        torch.testing.assert_close(before['future'], after['future'])

    def test_observations_nan_locations_and_source_bytes_preserved(self):
        path = self.root / 'daily.csv'; digest = hashlib.sha256(path.read_bytes()).hexdigest()
        before = self.store.frames['a'].q_cumecs.copy(deep=True)
        for index in range(len(self.dataset)):
            self.dataset[index]
        pd.testing.assert_series_equal(before, self.store.frames['a'].q_cumecs)
        self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())
        actual = MODEL_ROOT / 'data/marala_daily.csv'
        parent = ROOT / 'data/marala_daily.csv'
        expected = json.loads((MODEL_ROOT / "data/provenance.json").read_text())["source_sha256"]
        self.assertEqual(hashlib.sha256(actual.read_bytes()).hexdigest(), expected)
        if parent.exists():
            self.assertEqual(hashlib.sha256(actual.read_bytes()).hexdigest(), hashlib.sha256(parent.read_bytes()).hexdigest())

    def test_training_statistics_ignore_other_years(self):
        original = copy.deepcopy(self.stats)
        frame = self.store.frames['a']; holdout = frame.index.year >= 2021
        frame.loc[holdout, ['x', 'z', 'q_cumecs']] = 1e8
        self.assertEqual(original, fit_statistics(self.store))

    def test_published_block_matches_pinned_source(self):
        module = MODEL_ROOT / 'source_reference' / ('nhits.py' if self.family == 'nhits' else 'nbeatsx.py')
        tree = ast.parse(module.read_text(encoding='utf-8-sig'))
        classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name not in ['NHITS', 'NBEATSx']]
        scope = {'torch': torch, 'nn': nn, 'F': F, 'np': np, 'Tuple': Tuple,
                 'ACTIVATIONS': ['ReLU'], 'POOLING': ['MaxPool1d']}
        exec(compile(ast.Module(body=classes, type_ignores=[]), str(module), 'exec'), scope)
        actual = build_model(self.cfg, self.dataset.dimensions(), self.stats).blocks[0]
        if self.family == 'nhits':
            basis = scope['_IdentityBasis'](8, 3, 'linear', 5)
            expected = scope['NHITSBlock'](8, 3, 13, [[8, 8]], basis, 4, 7, 0, 4, 'MaxPool1d', 0, 'ReLU')
        else:
            basis = scope['IdentityBasis'](8, 3, 5)
            expected = scope['NBEATSBlock'](8, 3, 4, 7, 0, 23, [[8, 8]], basis, 0, 'ReLU')
        expected.load_state_dict(actual.state_dict())
        args = (torch.randn(2, 8), torch.randn(2, 11, 4), torch.randn(2, 8, 7), torch.empty(2, 0))
        actual.eval(); expected.eval()
        for a, b in zip(actual(*args), expected(*args)):
            torch.testing.assert_close(a, b, atol=0, rtol=0)

    def test_training_checkpoint_loads_and_changes_weights(self):
        seed_everything(42, 1)
        initial_model = build_model(self.cfg, self.dataset.dimensions(), self.stats)
        initial = {k: v.clone() for k, v in initial_model.state_dict().items()}
        path = run_training(self.cfg, 42, model_factory=build_model, dataset_factory=BasisDataset)
        checkpoint = load_checkpoint(path)
        model = build_model(self.cfg, self.dataset.dimensions(), self.stats)
        model.load_state_dict(checkpoint['model_state'])
        self.assertTrue(any(not torch.equal(value, initial[key]) for key, value in model.state_dict().items()))
        self.assertEqual(checkpoint['model_family'], self.family)
        self.assertEqual(checkpoint['training_years'], [2020])
