"""Causality, missing dates, exact lead semantics and immutable audit records."""
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from models.marala_station_forecast import core
from models.marala_station_forecast.archive import begin_run, seal_run
from models.marala_station_forecast.validate import verify_inventory
from models.marala_seasonal_outlook import experiment as seasonal


class MeasuredModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.history, _ = core.load_observations([core.HERE / "data/observations.csv"])

    def test_features_ignore_all_future_measurements(self):
        origin = date(2026, 8, 1)
        past = {day: row for day, row in self.history.items() if day <= origin}
        np.testing.assert_allclose(core.feature_row(self.history, origin)["features"],
                                   core.feature_row(past, origin)["features"], equal_nan=True)

    def test_missing_target_is_never_interpolated(self):
        origin = date(2026, 8, 1)
        missing = {day: row for day, row in self.history.items() if day != origin + timedelta(days=3)}
        rows, skipped = core.build_rows(missing, 3)
        self.assertFalse(any(row["issue_date"] == origin.isoformat() for row in rows))
        self.assertGreater(skipped["missing_target_day"], 0)

    def test_missing_previous_reading_blocks_forecast_features(self):
        origin = date(2026, 8, 1)
        missing = {day: row for day, row in self.history.items() if day != origin - timedelta(days=1)}
        with self.assertRaises(ValueError):
            core.feature_row(missing, origin)

    def test_exact_horizon_and_measurement_time(self):
        rows, _ = core.build_rows(self.history, 7)
        for row in rows:
            self.assertEqual(date.fromisoformat(row["target_date"]) - date.fromisoformat(row["issue_date"]), timedelta(days=7))
            self.assertTrue(row["target_at"].endswith("T06:00:00+05:00"))

    def test_future_inference_is_not_historical_backtest(self):
        from models.marala_station_forecast.predict import forecast
        with self.assertRaisesRegex(ValueError, "labels after"):
            forecast(as_of="2026-08-01")

    def test_ridge_saved_fit_replays_predictions(self):
        rows, _ = core.build_rows(self.history, 1)
        fit_rows = [r for r in rows if r["target_date"].startswith("2024")]
        test_rows = [r for r in rows if r["target_date"].startswith("2026")]
        model = core.fit({"id": "test", "family": "ridge", "target": "log_return", "penalty": 100}, fit_rows, 1)
        with tempfile.TemporaryDirectory() as tmp:
            core.save_model(model, tmp)
            np.testing.assert_allclose(core.predict(model, test_rows), core.predict(core.load_model(tmp), test_rows))


class AnnualOutlookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        first = date(2020, 1, 1)
        cls.history = {first + timedelta(days=i): 100 + i % 365 for i in range(1100)}

    def test_year_ahead_features_do_not_read_future(self):
        origin = date(2022, 1, 15)
        past = {day: value for day, value in self.history.items() if day <= origin}
        for lead in (1, 30, 180, 365):
            self.assertEqual(seasonal.row_at(self.history, origin, lead), seasonal.row_at(past, origin, lead))

    def test_missing_reference_day_cannot_be_filled(self):
        origin = date(2022, 1, 15)
        past = {day: value for day, value in self.history.items() if day != origin - timedelta(days=100)}
        with self.assertRaises(KeyError):
            seasonal.row_at(past, origin, 265)

    def test_rejects_untrained_extra_horizon(self):
        with self.assertRaises(ValueError):
            seasonal.row_at(self.history, date(2022, 1, 15), 366)

    def test_one_value_per_date_for_full_year_and_monthly_means(self):
        model = {"spec": {"family": "seasonal_naive"}, "training_last_target": "2021-01-01"}
        result = seasonal.outlook(self.history, model)
        self.assertEqual(len(result["daily"]), 365)
        self.assertEqual(len({r["date"] for r in result["daily"]}), 365)
        for month in result["monthly"]:
            daily = [r["predicted_daily_mean_cumecs"] for r in result["daily"] if r["date"].startswith(month["month"])]
            self.assertAlmostEqual(month["mean_of_forecast_daily_means_cumecs"], np.mean(daily))
            self.assertEqual(month["forecast_days"], len(daily))


class AuditTests(unittest.TestCase):
    def test_snapshot_retains_original_bytes_and_detects_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.json"
            source.write_text("[]", encoding="utf-8")
            run, sources = begin_run([source], root / "artifacts")
            source.write_text("changed", encoding="utf-8")
            self.assertEqual(sources[0].read_text(), "[]")
            (run / "artifacts").mkdir()
            seal_run(run, run / "data", run / "artifacts")
            self.assertGreater(verify_inventory(run), 0)
            with self.assertRaisesRegex(ValueError, "sealed run"):
                seal_run(run, run / "data", run / "artifacts")
            sources[0].write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "changed"):
                verify_inventory(run)


if __name__ == "__main__":
    unittest.main()
