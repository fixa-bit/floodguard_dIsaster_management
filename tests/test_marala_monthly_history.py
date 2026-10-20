import copy
import json
from datetime import date
from pathlib import Path

import pytest

from scripts.collect_marala_monthly_history import aggregate_months

ARTIFACTS = Path(__file__).resolve().parents[1] / "app/ml/marala_pilot/artifacts/seasonal"


def test_saved_monthly_history_matches_daily_provider_values():
    daily = json.loads((ARTIFACTS / "recent_history_daily.json").read_text(encoding="utf-8"))
    saved = json.loads((ARTIFACTS / "recent_monthly_history.json").read_text(encoding="utf-8"))
    rows = aggregate_months(daily, date.fromisoformat(saved["period_start"]), date.fromisoformat(saved["period_end"]))
    assert rows == saved["monthly"]
    assert len(rows) == 24
    assert saved["station_observation"] is False
    assert sum(row["days"] for row in rows) == len(daily["daily"]["time"])


@pytest.mark.parametrize("invalid", ["null", "missing_day", "duplicate_day"])
def test_incomplete_history_cannot_create_monthly_points(invalid):
    daily = json.loads((ARTIFACTS / "recent_history_daily.json").read_text(encoding="utf-8"))
    broken = copy.deepcopy(daily)
    if invalid == "null":
        broken["daily"]["river_discharge"][0] = None
    elif invalid == "missing_day":
        broken["daily"]["time"].pop(0)
        broken["daily"]["river_discharge"].pop(0)
    else:
        broken["daily"]["time"][1] = broken["daily"]["time"][0]
    with pytest.raises(ValueError):
        aggregate_months(broken, date(2024, 10, 1), date(2026, 9, 30))
