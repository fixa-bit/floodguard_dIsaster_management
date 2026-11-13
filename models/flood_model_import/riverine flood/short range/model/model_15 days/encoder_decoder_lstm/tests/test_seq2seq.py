"""Architecture, transfer provenance and future-target leakage correctness tests."""
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
import unittest
from pathlib import Path
import torch
import numpy as np
import pandas as pd
from data import load_config, resolve
from lstm.train import load_checkpoint
from encoder_decoder_lstm.model import adapt_checkpoint, HindcastForecastLSTM, masked_pinball
from encoder_decoder_lstm.predict import build_inputs

ROOT = Path(__file__).resolve().parents[1]


class Seq2SeqTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)
        self.cfg = load_config(ROOT / "config.yaml")
        self.parent = load_checkpoint(resolve(self.cfg, self.cfg['experiment']['source_pretrained_checkpoint']))

    def test_transfer_remaps_columns_and_preserves_parent(self):
        original = copy.deepcopy(self.parent["model_state"])
        adapted = adapt_checkpoint(self.parent, self.cfg)
        state = adapted["model_state"]
        self.assertEqual(tuple(state["lead.weight"].shape), (15, 8))
        torch.testing.assert_close(state["lead.weight"][:10], original["lead.weight"])
        torch.testing.assert_close(state["hindcast.weight_ih_l0"][:, :4], original["hindcast.weight_ih_l0"][:, :4])
        torch.testing.assert_close(state["hindcast.weight_ih_l0"][:, 6:], original["hindcast.weight_ih_l0"][:, 4:])
        self.assertEqual(int(torch.count_nonzero(state["hindcast.weight_ih_l0"][:, 4:6])), 0)
        for key in original:
            torch.testing.assert_close(self.parent["model_state"][key], original[key])
            if key not in ["lead.weight", "hindcast.weight_ih_l0"]:
                torch.testing.assert_close(state[key], original[key])

    def test_whole_horizon_order_and_finite_gradients(self):
        model = HindcastForecastLSTM(self.cfg, 8, 4, 0)
        output = model(torch.randn(3, 365, 8), torch.randn(3, 15, 4), torch.empty(3, 0))
        self.assertEqual(tuple(output.shape), (3, 15, 5))
        self.assertTrue(bool((output.diff(dim=-1) >= 0).all()))
        target = torch.randn(3, 15)
        target[0, 7] = float("nan")
        loss = masked_pinball(output, target, torch.isfinite(target), self.cfg["model"]["quantiles"])
        loss.backward()
        self.assertTrue(all(bool(torch.isfinite(p.grad).all()) for p in model.parameters()))

    def test_first_ten_leads_preserve_pretrained_function_before_finetuning(self):
        original = HindcastForecastLSTM(self.parent["config"], 6, 4, 0).eval()
        original.load_state_dict(self.parent["model_state"])
        adapted = adapt_checkpoint(self.parent, self.cfg)
        new = HindcastForecastLSTM(self.cfg, 8, 4, 0).eval()
        new.load_state_dict(adapted["model_state"])
        history, future = torch.randn(2, 30, 6), torch.randn(2, 15, 4)
        extended = torch.cat([history[..., :4], torch.randn(2, 30, 2), history[..., 4:]], -1)
        with torch.no_grad():
            before = original(history, future[:, :10], torch.empty(2, 0))
            after = new(extended, future, torch.empty(2, 0))
        torch.testing.assert_close(before, after[:, :10], rtol=1e-5, atol=1e-5)

    def test_inference_ignores_future_discharge_and_preserves_15_dates(self):
        issue = pd.Timestamp("2020-06-01")
        dates = pd.date_range(issue-pd.Timedelta(days=364), periods=380)
        history = pd.DataFrame({"precipitation_mm": 4., "temperature_c": 12., "q_cumecs": 400.}, index=dates)
        future = pd.DataFrame({"precipitation_mm": 3., "temperature_c": 15., "q_cumecs": 99999.},
                              index=dates[-15:])
        before = build_inputs(history, future, issue, self.cfg, self.parent["statistics"])
        history.loc[history.index > issue, "q_cumecs"] = np.nan
        future["q_cumecs"] = np.nan
        after = build_inputs(history, future, issue, self.cfg, self.parent["statistics"])
        for a, b in zip(before, after):
            torch.testing.assert_close(a, b)
        self.assertEqual(tuple(before[0].shape), (1, 365, 8))
        self.assertEqual(tuple(before[1].shape), (1, 15, 4))

    def test_inference_rejects_unavailable_weather(self):
        issue = pd.Timestamp("2020-06-01")
        history = pd.DataFrame({"precipitation_mm": 4., "temperature_c": 12., "q_cumecs": 400.},
                               index=pd.date_range(issue-pd.Timedelta(days=364), periods=365))
        future = pd.DataFrame({"precipitation_mm": 3., "temperature_c": 15., "available_at": "2020-06-03T00:00:00Z"},
                              index=pd.date_range(issue+pd.Timedelta(days=1), periods=15))
        with self.assertRaises(ValueError):
            build_inputs(history, future, issue, self.cfg, self.parent["statistics"])


if __name__ == "__main__":
    unittest.main()
