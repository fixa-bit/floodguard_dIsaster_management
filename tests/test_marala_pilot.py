"""Guard units, causal timing, missing observations, and out-of-sample separation."""
from datetime import date, timedelta

import numpy as np
import pytest

from app.ml.marala_pilot.collect import CUSEC_TO_CUMECS, parse_observation
from app.ml.marala_pilot.model import FEATURES, build_rows, config, flood_class, metrics, split_rows


def test_pdf_observations_are_not_forecast_values():
    text = """Dated: 25thSeptember, 2024
    QUANTITATIVE FLOOD FORECAST OF GAUGING STATIONS (IN THOUSANDS OF CUSECS)
    Actual Observations at 0600 PST
    Marala 1100 26.3 3.5 25-30 Below low 1100.0"""
    row = parse_observation(text, date(2024, 9, 25))
    assert row["inflow_cusecs"] == 26300
    assert row["outflow_cusecs"] == 3500
    assert row["inflow_cumecs"] == pytest.approx(26300 * CUSEC_TO_CUMECS)
    assert row["observed_at"].endswith("T06:00:00+05:00")
    with pytest.raises(ValueError, match="units"):
        parse_observation(text.replace("IN THOUSANDS OF CUSECS", "IN CUSECS"), date(2024, 9, 25))
    with pytest.raises(ValueError, match="date mismatch"):
        parse_observation(text, date(2024, 9, 26))


def samples():
    observations, weather = [], []
    for offset in range(18):
        day = date(2024, 6, 24) + timedelta(days=offset)
        observations.append({"station_id": "MARALA", "date": str(day), "observed_at": f"{day}T06:00:00+05:00",
                             "inflow_cumecs": 100 + offset, "outflow_cumecs": 50, "source_url": "test-fixture"})
        for point in config()["weather_points"]:
            weather.append({"date": str(day), "point": point["name"], "rainfall_mm": 1,
                            "temperature_c": 20, "soil_moisture_m3_m3": 0.3, "snow_depth_m": 0.1})
    return observations, weather


def test_future_weather_and_labels_cannot_enter_issue_features():
    observations, weather = samples()
    rows, _ = build_rows(observations, weather)
    first = rows[0]
    assert first["issued_at"].startswith("2024-07-01")
    assert first["rainfall_previous_7d_mm"] == 7
    for point in weather:
        if point["date"] >= "2024-07-01":
            point.update(rainfall_mm=9999, temperature_c=9999)
    observations[8]["inflow_cumecs"] = 9999  # tomorrow's label
    changed, _ = build_rows(observations, weather)
    assert [first[name] for name in FEATURES] == [changed[0][name] for name in FEATURES]
    assert changed[0]["target_discharge_cumecs"] == 9999


def test_gauge_gaps_are_not_interpolated_and_missing_weather_is_not_zero():
    observations, weather = samples()
    weather = [row for row in weather if not (row["date"] == "2024-06-30" and row["point"] == config()["weather_points"][0]["name"])]
    rows, _ = build_rows(observations, weather)
    assert np.isnan(rows[0]["rainfall_previous_1d_mm"])
    observations = [row for row in observations if row["date"] != "2024-07-02"]
    rows, skipped = build_rows(observations, weather)
    assert all(not row["issued_at"].startswith("2024-07-01") for row in rows)
    assert skipped["missing_daily_gauge_history_or_target"] > 0


def test_thresholds_and_baseline_metrics():
    threshold = 100000 * CUSEC_TO_CUMECS
    assert flood_class(threshold - 0.01) == "Below Low"
    assert flood_class(threshold) == "Low"
    assert flood_class(600000 * CUSEC_TO_CUMECS) == "Exceptionally High"
    result = metrics(np.asarray([1., 2., 3.]), np.asarray([1., 2., 3.]))
    assert result["rmse_cumecs"] == 0
    assert result["nash_sutcliffe_efficiency"] == 1
    assert result["flood_recall"] is None


def test_chronological_splits_purge_boundary_labels():
    rows = []
    for start in (date(2024, 8, 1), date(2024, 9, 1), date(2025, 7, 1)):
        for offset in range(31 if start.month == 8 else 20):
            day = start + timedelta(days=offset)
            rows.append({"issued_at": f"{day}T06:00:00+05:00", "target_at": f"{day + timedelta(days=1)}T06:00:00+05:00"})
    groups = split_rows(rows)
    assert max(row["target_at"] for row in groups["train"]) < min(row["issued_at"] for row in groups["validation"])
    assert not any(row["issued_at"].startswith("2024-08-31") for row in groups["train"])
