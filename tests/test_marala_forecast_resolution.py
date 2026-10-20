import calendar
import json
from pathlib import Path

import pytest

ARTIFACTS = Path(__file__).resolve().parents[1] / "app/ml/marala_pilot/artifacts/seasonal"


def test_saved_daily_forecasts_match_provider_response():
    saved = json.loads((ARTIFACTS / "current_provider_outlook.json").read_text(encoding="utf-8"))
    raw = json.loads((ARTIFACTS / "current_provider_outlook.daily-source.json").read_text(encoding="utf-8"))
    indexed = dict(zip(raw["daily"]["time"], raw["daily"]["river_discharge_mean"], strict=True))
    assert saved["daily_forecast"]
    assert all(row["mean_cumecs"] == indexed[row["date"]] for row in saved["daily_forecast"])
    assert "not an instantaneous 06:00" in saved["daily_time_basis"]
    assert len({row["date"] for row in saved["daily_forecast"]}) == len(saved["daily_forecast"])


def test_monthly_forecast_is_average_of_same_daily_forecasts():
    saved = json.loads((ARTIFACTS / "current_provider_outlook.json").read_text(encoding="utf-8"))
    for month in saved["forecast"]:
        year, number = map(int, month["target_month"].split("-"))
        values = [row["mean_cumecs"] for row in saved["daily_forecast"] if row["date"].startswith(month["target_month"])]
        assert len(values) == calendar.monthrange(year, number)[1] == month["days"]
        assert month["monthly_mean_discharge_cumecs"]["mean"] == pytest.approx(sum(values) / len(values))
