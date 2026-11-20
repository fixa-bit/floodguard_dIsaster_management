import json
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from app.services.marala_forward_forecast import (
    build_forward_forecast,
    daily_history_from_readings,
)


HERE = Path(__file__).resolve().parent


def fixture_history():
    raw = json.loads((HERE / "data/live_gauge_readings.json").read_text(encoding="utf-8"))
    readings = [SimpleNamespace(**{
        **row,
        "recorded_at": datetime.fromisoformat(row["recorded_at"]),
    }) for row in raw]
    return daily_history_from_readings(readings)


def test_latest_live_origin_produces_future_targets_from_copied_models():
    history = fixture_history()
    result = build_forward_forecast(
        history,
        HERE / "artifacts",
        now=datetime.fromisoformat("2026-11-19T12:00:00+00:00"),
    )

    assert result is not None
    assert result["origin"]["observed_at"].startswith("2026-11-19T06:00:00+05:00")
    forecasts = result["forecasts"]
    assert [row["horizon_days"] for row in forecasts] == [1, 3, 7]
    origin = datetime.fromisoformat(result["origin"]["observed_at"])
    for row, horizon in zip(forecasts, (1, 3, 7), strict=True):
        target = datetime.fromisoformat(row["target_at"])
        assert target == origin + timedelta(days=horizon)
        assert target > datetime.fromisoformat("2026-11-19T12:00:00+00:00")
        assert row["champion"]["predicted_inflow_cumecs"] >= 0
        assert row["best_learned"]["predicted_inflow_cumecs"] >= 0
        assert len(row["candidates"]) == 5
        assert row["champion"]["candidate"] == row["candidates"][0]["candidate"]
        assert len({candidate["candidate"] for candidate in row["candidates"]}) == 5
        scores = [candidate["validation_rmse_cumecs"] for candidate in row["candidates"]]
        assert scores == sorted(scores)


def test_stale_origin_does_not_reuse_expired_forecast_as_live():
    result = build_forward_forecast(
        fixture_history(),
        HERE / "artifacts",
        now=datetime.fromisoformat("2026-11-21T12:00:00+00:00"),
    )

    assert result is None


def test_live_forecast_is_not_returned_once_the_one_day_target_has_passed():
    result = build_forward_forecast(
        fixture_history(),
        HERE / "artifacts",
        now=datetime.fromisoformat("2026-11-20T01:00:00+00:00"),
    )

    assert result is None


def test_missing_previous_day_does_not_make_up_model_lag():
    history = fixture_history()
    history.pop(date(2026, 11, 18), None)
    result = build_forward_forecast(
        history,
        HERE / "artifacts",
        now=datetime.fromisoformat("2026-11-19T12:00:00+00:00"),
    )

    assert result is None
