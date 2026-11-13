import unittest
import numpy as np
import pandas as pd
from hbv_residual.physical import BOUNDS, initial_state, simulate, branches
from hbv_residual.forcing import QuantileMapper, validate_archive, mixture_quantiles, mixture_exceedance
from hbv_residual.data import historical_features, masks
from hbv_residual.evaluation import threshold_metrics, flow_metrics, peak_events
from hbv_residual.learning import ResidualLSTM, pinball
import torch


class PhysicalTests(unittest.TestCase):
    def test_water_balance_snow_and_restart(self):
        par = np.mean(BOUNDS, axis=1)
        rng = np.random.default_rng(4)
        p, t, pet = rng.exponential(4, 1000), rng.normal(1, 9, 1000), rng.uniform(0, 5, 1000)
        states, fluxes = simulate(p, t, pet, par, initial_state(par))
        self.assertLess(abs(fluxes[:, 5]).max(), 1e-8)
        self.assertGreaterEqual(states.min(), 0)
        self.assertGreater(fluxes[:, 0].max(), 0)
        restart_states, restart_flux = branches(p[501:511][None], t[501:511][None], pet[501:511][None], par, states[500][None])
        np.testing.assert_allclose(restart_states[0], states[501:511])
        np.testing.assert_allclose(restart_flux[0], fluxes[501:511])

    def test_no_water_creates_no_flow(self):
        par = np.mean(BOUNDS, axis=1)
        states, fluxes = simulate(np.zeros(30), np.full(30, 10.), np.full(30, 2.), par, np.zeros(6))
        np.testing.assert_array_equal(states, 0)
        np.testing.assert_array_equal(fluxes, 0)


class ForcingTests(unittest.TestCase):
    def test_mapping_fits_train_only_and_keeps_temperature_identity(self):
        dates = pd.date_range("2018-01-01", "2021-12-31")
        frame = pd.DataFrame({"rain_era5_mm": np.arange(len(dates)) % 20,
                              "rain_chirps_mm": 2 * (np.arange(len(dates)) % 20),
                              "temperature_c": np.arange(len(dates)) % 30}, index=dates)
        mask = dates.year <= 2020
        a = QuantileMapper().fit(frame, mask)
        modified = frame.copy()
        modified.loc[~mask, "rain_chirps_mm"] = 99999
        b = QuantileMapper().fit(modified, mask)
        self.assertEqual(a.grids, b.grids)
        np.testing.assert_array_equal(a.transform([1, -2], [1, 2], "temperature"), [1, -2])
        np.testing.assert_allclose(a.transform([0, 5, 25], [1, 1, 1], "rain"), [0, 10, 44])

    def test_archive_rejects_future_availability_duplicates_and_wrong_dates(self):
        frame = pd.DataFrame({"issue_date": ["2020-06-01"]*10,
                              "valid_date": pd.date_range("2020-06-02", periods=10),
                              "lead_day": np.arange(1, 11), "member": "a",
                              "available_at": "2020-06-01T12:00Z", "precipitation_mm": 1., "temperature_c": 3.})
        self.assertEqual(len(validate_archive(frame)), 10)
        wrong = frame.copy()
        wrong.loc[0, "available_at"] = "2020-06-03"
        with self.assertRaises(ValueError):
            validate_archive(wrong)
        with self.assertRaises(ValueError):
            validate_archive(pd.concat([frame, frame.iloc[:1]]))
        wrong = frame.copy()
        wrong.loc[0, "valid_date"] = pd.Timestamp("2020-06-05")
        with self.assertRaises(ValueError):
            validate_archive(wrong)

    def test_member_mixture_is_not_mean_of_quantiles(self):
        quantiles = np.array([[[[0., 0., 0.]], [[100., 100., 100.]]]])
        mixture, samples = mixture_quantiles(quantiles)
        self.assertAlmostEqual(mixture[0, 0, 0], 0)
        self.assertAlmostEqual(mixture[0, 0, 2], 100)
        self.assertEqual((samples[0, 0] >= 60).mean(), .5)
        self.assertEqual(mixture_exceedance(quantiles[0], 60)[0], .5)
        self.assertEqual(mixture_exceedance(quantiles[0], 100)[0], .5)
        self.assertEqual(mixture_exceedance(quantiles[0], 101)[0], 0)

    def test_identical_member_quantiles_survive_mixture(self):
        quantiles = np.array([[[[10., 50., 90.]], [[10., 50., 90.]]]])
        mixture, _ = mixture_quantiles(quantiles)
        np.testing.assert_allclose(mixture[0, 0], [10., 50., 90.])
        self.assertAlmostEqual(mixture_exceedance(quantiles[0], 30)[0], .7)


class LeakageTests(unittest.TestCase):
    def test_past_features_are_unchanged_by_future_discharge_or_modis(self):
        dates = pd.date_range("2018-01-01", periods=150)
        frame = pd.DataFrame({"q_cumecs": np.arange(150.), "rain_chirps_mm": 2., "temperature_c": 3.,
                              "pet_mm": 1., "snow_cover_pct": 60., "valid_frac": .9}, index=dates)
        config = {"snow_cover_scale_mm": 50., "modis_min_valid_fraction": .5,
                  "modis_latency_days": 2, "modis_max_age_days": 7}
        states, flux = np.ones((150, 6)), np.ones((150, 6))
        before = historical_features(frame, states, flux, 1000., config)
        frame.loc[dates[101]:, "q_cumecs"] = 999999.
        frame.loc[dates[99]:, "snow_cover_pct"] = 0.
        after = historical_features(frame, states, flux, 1000., config)
        # At issue day 100, MODIS day 99 is still unavailable (2-day latency).
        pd.testing.assert_frame_equal(before.iloc[:101], after.iloc[:101])

    def test_all_target_days_remain_inside_whole_year_and_monsoon(self):
        frame = pd.DataFrame(index=pd.date_range("2014-01-01", "2024-12-31"))
        origins = np.arange(730, len(frame)-10)
        valid = frame.index.to_numpy()[origins[:, None]+np.arange(1, 11)]
        config = {"first_training_year": 2016, "monsoon_months": [6, 7, 8, 9], "warmup_days": 730}
        train, val, test = masks({"origins": origins, "valid": valid}, frame, config, 2023)
        self.assertTrue((valid[train, -1] <= np.datetime64("2021-12-31")).all())
        self.assertTrue((valid[val, 0] >= np.datetime64("2022-01-01")).all())
        self.assertTrue((valid[val, -1] <= np.datetime64("2022-12-31")).all())
        self.assertTrue((valid[test, 0] >= np.datetime64("2023-06-01")).all())
        self.assertTrue((valid[test, -1] <= np.datetime64("2023-09-30")).all())
        self.assertFalse((train & val | train & test | val & test).any())


class LearningAndMetricTests(unittest.TestCase):
    def test_lstm_order_and_missing_target_loss(self):
        torch.manual_seed(1)
        model = ResidualLSTM(4, 3, 8)
        pred = model(torch.randn(2, 6, 4), torch.randn(2, 10, 3))
        self.assertEqual(tuple(pred.shape), (2, 10, 3))
        self.assertTrue(bool((pred[..., 0] <= pred[..., 1]).all()))
        self.assertTrue(bool((pred[..., 1] <= pred[..., 2]).all()))
        target = torch.ones(2, 10)
        target[0, 0] = float("nan")
        loss = pinball(pred, target)
        self.assertTrue(bool(torch.isfinite(loss)))
        loss.backward()
        self.assertTrue(all(bool(torch.isfinite(p.grad).all()) for p in model.parameters()))

    def test_known_threshold_counts_and_flow_scores(self):
        obs = np.array([0., 2., 2., 0.])
        prob = np.array([0., .8, .2, .6])
        score = threshold_metrics(obs, prob, np.ones(4))
        self.assertEqual((score["tp"], score["fp"], score["fn"]), (1, 1, 1))
        self.assertEqual(score["pod"], .5)
        self.assertEqual(score["far"], .5)
        self.assertAlmostEqual(score["csi"], 1/3)
        self.assertAlmostEqual(score["brier_score"], .26)
        perfect = flow_metrics(np.arange(5.), np.arange(5.))
        self.assertAlmostEqual(perfect["kge"], 1.)
        self.assertEqual(perfect["nse"], 1.)

    def test_peak_timing_uses_dates(self):
        frame = pd.DataFrame({"valid_date": pd.date_range("2020-06-01", periods=9),
                              "observed": [0, 0, 5, 10, 6, 0, 0, 0, 0],
                              "p50": [0, 0, 0, 0, 0, 8, 0, 0, 0]})
        events = peak_events(frame, 7.)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["peak_timing_error_days"], 2)
        self.assertEqual(events[0]["peak_magnitude_error_cumecs"], -2.)


if __name__ == "__main__":
    unittest.main()
