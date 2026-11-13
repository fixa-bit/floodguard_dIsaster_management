"""Correctness tests only; real accuracy is measured on observed held-out days."""
import copy
import hashlib
import sys
import unittest
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from data import DataStore, DeltaDataset, fit_statistics, load_config, sha256
from model import DeltaHBV, masked_loss


class DeltaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)
        cls.cfg = load_config(ROOT / 'config.yaml')
        cls.store = DataStore(cls.cfg)
        cls.stats = fit_statistics(cls.store)

    def test_shapes_alignment_and_future_targets_never_used(self):
        dataset = DeltaDataset(self.store, 'train', self.stats)
        before = dataset[0]
        basin, pos = dataset.samples[0]
        raw = self.store.frames[basin].iloc[pos - 364:pos + 1]
        np.testing.assert_allclose(before['forcing'][:365], raw[['rain_era5_mm', 'temperature_c', 'pet_mm']], rtol=1e-5, atol=1e-5)
        self.assertEqual(tuple(before['forcing'].shape), (375, 3))
        self.assertEqual(tuple(before['neural'].shape), (375, 8))
        self.assertEqual(tuple(before['target'].shape), (10,))
        changed = copy.deepcopy(self.store)
        target_dates = changed.frames[basin].index[pos + 1:pos + 11]
        observed_dates = target_dates[changed.frames[basin].loc[target_dates, 'q_cumecs'].notna()]
        changed.frames[basin].loc[observed_dates, 'q_cumecs'] = 999999.
        changed_dataset = DeltaDataset(changed, 'train', self.stats)
        after = changed_dataset[changed_dataset.samples.index((basin, pos))]
        torch.testing.assert_close(before['neural'], after['neural'])
        torch.testing.assert_close(before['forcing'], after['forcing'])

    def test_masked_loss_ignores_nan_targets(self):
        prediction = torch.tensor([[100., 200.]], requires_grad=True)
        target = torch.tensor([[0.5, float('nan')]])
        mask = torch.tensor([[True, False]])
        a = masked_loss(prediction, target, mask, self.stats, self.cfg['training'])
        target[0, 1] = 1e9
        b = masked_loss(prediction, target, mask, self.stats, self.cfg['training'])
        torch.testing.assert_close(a, b)
        a.backward()
        self.assertEqual(float(prediction.grad[0, 1]), 0.)

    def test_physical_model_is_differentiable_and_checkpoint_loads(self):
        torch.manual_seed(42)
        model = DeltaHBV(self.cfg)
        item = DeltaDataset(self.store, 'train', self.stats)[100]
        inputs = {k: v.unsqueeze(0) for k, v in item.items() if isinstance(v, torch.Tensor)}
        original = {k: v.detach().clone() for k, v in model.state_dict().items()}
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
        prediction = model(inputs['neural'], inputs['forcing'])
        self.assertEqual(tuple(prediction.shape), (1, 10))
        self.assertTrue(torch.isfinite(prediction).all())
        self.assertTrue((prediction >= 0).all())
        loss = masked_loss(prediction, inputs['target'], inputs['mask'], self.stats, self.cfg['training'])
        loss.backward()
        self.assertGreater(float(model.static_logits.grad.abs().sum()), 0.)
        self.assertGreater(float(model.parameter_head.weight.grad.abs().sum()), 0.)
        self.assertGreater(float(model.parameter_lstm.weight_ih_l0.grad.abs().sum()), 0.)
        optimizer.step()
        self.assertFalse(torch.equal(model.static_logits.detach(), original['static_logits']))
        restored = DeltaHBV(self.cfg)
        restored.load_state_dict(model.state_dict())
        model.eval()
        restored.eval()
        torch.testing.assert_close(model(inputs['neural'], inputs['forcing']), restored(inputs['neural'], inputs['forcing']))

    def test_training_statistics_and_pet_exclude_test_years(self):
        changed = copy.deepcopy(self.store)
        for frame in changed.frames.values():
            mask = frame.index.year >= 2021
            frame.loc[mask, ['rain_era5_mm', 'temperature_c', 'pet_mm', 'q_cumecs']] = 1e8
        self.assertEqual(self.stats, fit_statistics(changed))

    def test_upstream_source_bytes_and_observations_preserved(self):
        import json
        provenance = json.loads((ROOT / 'source_reference/provenance.json').read_text())
        for item in provenance['files']:
            if item['path'].startswith('src/'):
                bundled = ROOT / '_vendor' / item['path'].removeprefix('src/')
                self.assertEqual(sha256(bundled), item['sha256'])
        source = ROOT.parents[2] / 'evaluation comparison/common/data/marala_daily.csv'
        self.assertEqual(sha256(ROOT / 'data/marala_daily.csv'), sha256(source))
        frame = self.store.frames['marala']
        dataset = DeltaDataset(self.store, 'train', self.stats)
        q_before = frame.q_cumecs.copy()
        _ = dataset[0]
        np.testing.assert_array_equal(q_before.to_numpy(), frame.q_cumecs.to_numpy())


if __name__ == '__main__':
    unittest.main()
