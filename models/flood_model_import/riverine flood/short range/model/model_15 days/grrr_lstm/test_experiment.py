"""Scientific integrity checks: leakage, unchanged observations and scoring masks."""
import unittest

import numpy as np
import pandas as pd

from compare import PROTOCOL, load_frame
from experiment import ARMS, HORIZON, LOOKBACK, build_features, build_tensors, calibrate_fills, common_origins, make_predictions


class ExperimentIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame = load_frame()
        cls.frame = cls.frame[(cls.frame.date >= '2016-03-01') & (cls.frame.date <= '2026-10-23')].reset_index(drop=True)

    def test_fills_preserve_observations_and_do_not_extend_archive(self):
        frame = self.frame
        values, filled, _ = calibrate_fills(frame)
        observed = frame.is_observed.to_numpy()
        np.testing.assert_array_equal(values[observed], frame.loc[observed, 'observed_discharge_m3_s'])
        self.assertFalse(np.any(filled & observed))
        self.assertFalse(np.any(filled & frame.grrr_discharge_m3_s.isna()))
        self.assertTrue(np.isnan(values[(frame.year == 2026) & ~frame.is_observed]).all())

    def test_calibration_cannot_see_validation_or_test_observations(self):
        frame = self.frame
        values, filled, parameters = calibrate_fills(frame)
        modified = frame.copy()
        modified.loc[modified.split != 'train', 'observed_discharge_m3_s'] = 1e9
        modified_values, modified_filled, modified_parameters = calibrate_fills(modified)
        self.assertEqual(parameters, modified_parameters)
        np.testing.assert_array_equal(filled, modified_filled)
        np.testing.assert_array_equal(values[filled], modified_values[filled])

    def test_windows_and_features_respect_time(self):
        frame = self.frame
        for part, origins in common_origins(frame).items():
            for origin in origins:
                self.assertTrue(frame.iloc[origin - 1].is_observed)
                self.assertGreaterEqual(frame.is_observed.iloc[origin - LOOKBACK:origin].sum(), 15)
                self.assertTrue((frame.split.iloc[origin:origin + HORIZON] == part).all())
        np.testing.assert_array_equal(frame.grrr_lagged_m3_s.iloc[2:], frame.grrr_discharge_m3_s.iloc[:-2])

    def test_synthetic_targets_have_lower_weight_and_never_enter_scores(self):
        frame = self.frame
        values, filled, _ = calibrate_fills(frame)
        observed = frame.is_observed.to_numpy()
        norm = dict(observed_mean=1000., observed_std=500., grrr_mean=1000., grrr_std=500.)
        features = build_features(frame, values, filled, True, norm)
        origins = common_origins(frame)
        tensors = build_tensors(features, values, filled, observed, origins, norm, 'weighted_fills')
        _, _, weights, obs = tensors['train']
        synthetic = (weights > 0) & (obs == 0)
        self.assertTrue(synthetic.any())
        np.testing.assert_allclose(weights[synthetic], PROTOCOL['filled_target_weight'])
        for part in ('validation', 'test'):
            np.testing.assert_array_equal(tensors[part][2], tensors[part][3])
        dummy = {arm: {part: np.ones((len(origins[part]), HORIZON)) for part in ('validation', 'test')} for arm in ARMS}
        predictions = make_predictions(frame, origins, dummy, 1000)
        target_values = frame.set_index('date').observed_discharge_m3_s
        np.testing.assert_array_equal(predictions.observed_m3_s, target_values.loc[predictions.target_date])
        self.assertFalse(predictions.observed_m3_s.isna().any())
        # Both arms inhabit one row per scoring key, guaranteeing identical tests.
        self.assertFalse(predictions.duplicated(['split', 'issue_after_date', 'target_date', 'lead_days']).any())


if __name__ == '__main__':
    unittest.main()
