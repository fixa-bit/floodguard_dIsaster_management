"""Implementation checks only; benchmark accuracy is evaluated separately."""
import copy
import json
import sys
import unittest
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from data import DataStore, ResidualDataset, fit_statistics, load_config, resolve
from metrics import sha
from model import ResidualLSTM, objective
from postprocess import fit_postprocessing, apply_postprocessing


class ResidualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)
        cls.cfg = load_config(ROOT / 'config.yaml')
        cls.store = DataStore(cls.cfg)
        cls.stats = fit_statistics(cls.store)
        cls.dataset = ResidualDataset(cls.store, 'train', cls.stats)
        cls.parent = torch.load(resolve(cls.cfg, cls.cfg['model']['parent_checkpoint']), map_location='cpu', weights_only=True)

    def sample(self):
        item = self.dataset[500]
        return {k: v.unsqueeze(0) if isinstance(v, torch.Tensor) else v for k, v in item.items()}

    def test_initial_mean_equals_smooth_climatology_and_ordered_quantiles(self):
        model = ResidualLSTM(self.cfg, self.dataset.dimensions(), self.stats).eval()
        model.initialize_from_parent(self.parent)
        item = self.sample()
        point, quantiles = model(item['history'], item['future'], item['smooth_climatology'])
        self.assertEqual(tuple(point.shape), (1, 30))
        self.assertEqual(tuple(quantiles.shape), (1, 30, 5))
        torch.testing.assert_close(point, item['smooth_climatology'], rtol=0, atol=0)
        self.assertTrue(bool((quantiles.diff(dim=-1) >= 0).all()))
        self.assertTrue(bool((quantiles >= 0).all()))

    def test_parent_transfer_preserves_old_columns_and_zeros_new_column(self):
        model = ResidualLSTM(self.cfg, self.dataset.dimensions(), self.stats)
        model.initialize_from_parent(self.parent)
        torch.testing.assert_close(model.hindcast.weight_ih_l0, self.parent['model_state']['hindcast.weight_ih_l0'])
        source = self.parent['model_state']['forecast.weight_ih_l0']
        torch.testing.assert_close(model.forecast.weight_ih_l0[:, :source.shape[1]], source)
        self.assertEqual(int(torch.count_nonzero(model.forecast.weight_ih_l0[:, source.shape[1]:])), 0)

    def test_climatology_and_statistics_exclude_validation_and_test(self):
        changed = copy.deepcopy(self.store)
        for frame in changed.frames.values():
            frame.loc[frame.index.year >= 2021, self.cfg['data']['dynamic_columns'] + ['q_cumecs']] = 1e8
        self.assertEqual(self.stats, fit_statistics(changed))

    def test_training_anchor_excludes_own_target_year(self):
        changed = copy.deepcopy(self.store)
        for frame in changed.frames.values():
            frame.loc[frame.index.year == 2019, 'q_cumecs'] *= 3
        revised = fit_statistics(changed)
        self.assertEqual(self.stats['climatology']['marala']['leave_year_out']['2019'],
                         revised['climatology']['marala']['leave_year_out']['2019'])

    def test_future_targets_never_change_inputs_or_calendar_anchors(self):
        test = ResidualDataset(self.store, 'test', self.stats)
        before = test[0]
        basin, position = test.samples[0]
        changed = copy.deepcopy(self.store)
        frame = changed.frames[basin]
        dates = frame.index[position + 1:position + 31]
        known = dates[frame.loc[dates, 'q_cumecs'].notna()]
        frame.loc[known, 'q_cumecs'] = 1e9
        after = ResidualDataset(changed, 'test', self.stats)[0]
        for key in ('history', 'future', 'climatology', 'smooth_climatology'):
            torch.testing.assert_close(before[key], after[key], rtol=0, atol=0)

    def test_missing_targets_have_no_loss_or_gradient(self):
        item = self.sample()
        item['mask'][:, 4] = False
        item['target_q'][:, 4] = float('nan')
        point = item['smooth_climatology'].clone().requires_grad_()
        q = point.detach().unsqueeze(-1).repeat(1, 1, 5).requires_grad_()
        a = objective(point, q, item, self.stats['flow_std_cumecs'], self.cfg)
        item['target_q'][:, 4] = 1e8
        b = objective(point, q, item, self.stats['flow_std_cumecs'], self.cfg)
        torch.testing.assert_close(a, b)
        a.backward()
        self.assertEqual(float(point.grad[:, 4].abs().sum()), 0.)
        self.assertEqual(float(q.grad[:, 4].abs().sum()), 0.)

    def test_training_updates_head_and_encoder(self):
        torch.manual_seed(42)
        model = ResidualLSTM(self.cfg, self.dataset.dimensions(), self.stats)
        model.initialize_from_parent(self.parent)
        optimizer = torch.optim.Adam(model.parameters(), lr=.001)
        item = self.sample()
        for _ in range(2):
            optimizer.zero_grad()
            point, q = model(item['history'], item['future'], item['smooth_climatology'])
            loss = objective(point, q, item, model.flow_scale, self.cfg)
            loss.backward()
            optimizer.step()
        self.assertGreater(float(model.mean_head.weight.grad.abs().sum()), 0.)
        self.assertGreater(float(model.hindcast.weight_ih_l0.grad.abs().sum()), 0.)

    def test_validation_blend_never_worsens_its_fit_and_intervals_order(self):
        rng = np.random.default_rng(42)
        baseline = rng.uniform(100, 800, (80, 30))
        target = baseline + rng.normal(0, 100, baseline.shape)
        point = baseline + .7 * (target - baseline) + rng.normal(0, 50, baseline.shape)
        quantiles = point[:, :, None] + np.array([-150, -50, 0, 50, 150])
        mask = np.ones_like(target, bool)
        options = fit_postprocessing(point, quantiles, baseline, target, mask, self.cfg)
        for group in options['lead_groups']:
            self.assertLessEqual(group['validation_blended_mse'], group['validation_climatology_mse'] + 1e-8)
        _, q = apply_postprocessing(point, quantiles, baseline, options)
        self.assertTrue((np.diff(q, axis=-1) >= 0).all())

    def test_reference_artifacts_and_original_observations_unchanged(self):
        protected = json.loads((ROOT / 'reference_artifacts_before.json').read_text())
        for item in protected:
            self.assertEqual(sha(item['path']), item['sha256'])
        source = ROOT.parent / 'past_discharge/data/marala_daily.csv'
        self.assertEqual(sha(source), sha(ROOT / 'data/marala_daily.csv'))


if __name__ == '__main__':
    unittest.main()
