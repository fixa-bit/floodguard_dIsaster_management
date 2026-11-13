"""Transfer, masking and causal-input checks; tests do not establish accuracy."""
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
from model import EncoderDecoderLSTM, objective
from _parent_model import HindcastForecastLSTM
from postprocess import fit_postprocessing, apply_postprocessing


class EncoderDecoderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)
        cls.cfg = load_config(ROOT / 'config.yaml')
        cls.store = DataStore(cls.cfg)
        cls.stats = fit_statistics(cls.store)
        cls.dataset = ResidualDataset(cls.store, 'train', cls.stats)
        cls.parent = torch.load(resolve(cls.cfg, cls.cfg['model']['parent_checkpoint']), map_location='cpu', weights_only=True)

    def batch(self):
        item = self.dataset[500]
        return {k: v.unsqueeze(0) if isinstance(v, torch.Tensor) else v for k, v in item.items()}

    def model(self):
        model = EncoderDecoderLSTM(self.cfg, self.dataset.dimensions(), self.stats)
        model.initialize_from_parent(self.parent)
        return model

    def test_shapes_all_thirty_leads_and_ordered_physical_quantiles(self):
        model = self.model().eval()
        batch = self.batch()
        self.assertEqual(tuple(batch['history'].shape), (1, 365, 8))
        self.assertEqual(tuple(batch['future'].shape), (1, 30, 4))
        mean, q = model(batch['history'], batch['future'], batch['smooth_climatology'])
        self.assertEqual(tuple(mean.shape), (1, 30))
        self.assertEqual(tuple(q.shape), (1, 30, 5))
        self.assertTrue(bool(torch.isfinite(q).all()))
        self.assertTrue(bool((q.diff(dim=-1) >= 0).all()))
        torch.testing.assert_close(mean, batch['smooth_climatology'], rtol=0, atol=0)

    def test_first_fifteen_parent_quantiles_preserved_before_finetuning(self):
        parent = HindcastForecastLSTM(self.parent['config'], *self.parent['dimensions']).eval()
        parent.load_state_dict(self.parent['model_state'])
        new = self.model().eval()
        batch = self.batch()
        with torch.no_grad():
            old = parent(batch['history'], batch['future'][:, :15], batch['static'])
            decoded = new.decode(batch['history'], batch['future'], batch['smooth_climatology'])
            extended = new.ordered_log_quantiles(decoded)
        torch.testing.assert_close(old, extended[:, :15], rtol=1e-5, atol=1e-5)
        torch.testing.assert_close(new.lead.weight[:15], self.parent['model_state']['lead.weight'])
        torch.testing.assert_close(new.lead.weight[15:], self.parent['model_state']['lead.weight'][-1:].expand(15, -1))
        self.assertEqual(int(torch.count_nonzero(new.forecast.weight_ih_l0[:, -1:])), 0)

    def test_late_lead_embeddings_train_and_mean_head_updates(self):
        torch.manual_seed(42)
        model = self.model()
        batch = self.batch()
        before = model.lead.weight.detach().clone()
        optimizer = torch.optim.Adam(model.parameters(), lr=.0003)
        mean, q = model(batch['history'], batch['future'], batch['smooth_climatology'])
        objective(mean, q, batch, model.flow_scale, self.cfg).backward()
        self.assertGreater(float(model.mean_head.weight.grad.abs().sum()), 0.)
        self.assertGreater(float(model.lead.weight.grad[29].abs().sum()), 0.)
        optimizer.step()
        self.assertFalse(torch.equal(model.lead.weight[29].detach(), before[29]))

    def test_missing_targets_do_not_affect_loss_or_gradient(self):
        batch = self.batch()
        batch['target_q'][:, 5] = float('nan')
        batch['mask'][:, 5] = False
        mean = batch['smooth_climatology'].clone().requires_grad_()
        q = mean.detach().unsqueeze(-1).repeat(1, 1, 5).requires_grad_()
        a = objective(mean, q, batch, self.stats['flow_std_cumecs'], self.cfg)
        batch['target_q'][:, 5] = 1e8
        b = objective(mean, q, batch, self.stats['flow_std_cumecs'], self.cfg)
        torch.testing.assert_close(a, b)
        a.backward()
        self.assertEqual(float(mean.grad[:, 5].abs().sum()), 0.)
        self.assertEqual(float(q.grad[:, 5].abs().sum()), 0.)

    def test_future_discharge_excluded_from_every_input(self):
        dataset = ResidualDataset(self.store, 'test', self.stats)
        before = dataset[0]
        basin, position = dataset.samples[0]
        changed = copy.deepcopy(self.store)
        frame = changed.frames[basin]
        dates = frame.index[position + 1:position + 31]
        known = dates[frame.loc[dates, 'q_cumecs'].notna()]
        frame.loc[known, 'q_cumecs'] = 1e9
        after = ResidualDataset(changed, 'test', self.stats)[0]
        for key in ('history', 'future', 'climatology', 'smooth_climatology'):
            torch.testing.assert_close(before[key], after[key], rtol=0, atol=0)

    def test_normalization_and_calendar_curves_use_training_only(self):
        changed = copy.deepcopy(self.store)
        for frame in changed.frames.values():
            frame.loc[frame.index.year >= 2021, ['precipitation_mm', 'temperature_c', 'q_cumecs']] = 1e8
        self.assertEqual(self.stats, fit_statistics(changed))
        for key in ('dynamic', 'forecast', 'flow'):
            self.assertEqual(self.stats[key], self.parent['statistics'][key])

    def test_training_calendar_excludes_own_year(self):
        changed = copy.deepcopy(self.store)
        for frame in changed.frames.values():
            frame.loc[frame.index.year == 2019, 'q_cumecs'] *= 3
        new = fit_statistics(changed)
        self.assertEqual(self.stats['climatology']['marala']['leave_year_out']['2019'], new['climatology']['marala']['leave_year_out']['2019'])

    def test_validation_blending_and_interval_order(self):
        rng = np.random.default_rng(42)
        c = rng.uniform(100, 800, (60, 30))
        y = c + rng.normal(0, 100, c.shape)
        p = c + .7 * (y - c) + rng.normal(0, 50, c.shape)
        q = p[:, :, None] + np.array([-150, -50, 0, 50, 150])
        post = fit_postprocessing(p, q, c, y, np.ones_like(y, bool), self.cfg)
        _, adjusted = apply_postprocessing(p, q, c, post)
        self.assertTrue((np.diff(adjusted, axis=-1) >= 0).all())
        for group in post['lead_groups']:
            self.assertLessEqual(group['validation_blended_mse'], group['validation_climatology_mse'] + 1e-8)

    def test_parent_and_previous_run_files_preserved(self):
        protected = json.loads((ROOT / 'reference_artifacts_before.json').read_text())
        for entry in protected:
            self.assertEqual(sha(entry['path']), entry['sha256'])
        receipt = json.loads((ROOT / 'data/preparation_report.json').read_text())
        self.assertEqual(sha(ROOT / 'data/marala_daily.csv'), receipt['source_sha256'])
        self.assertTrue(set(self.parent['training_years'] + self.parent['selection_years']).isdisjoint({2022, 2023, 2024}))


if __name__ == '__main__':
    unittest.main()
