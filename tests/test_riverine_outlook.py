"""Riverine outlook snapshot: Marala is served from the saved model run; other stations get an empty shape."""
from datetime import date, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import predictive_riverine
from app.services.riverine_outlook import SNAPSHOTS, STALE_AFTER_DAYS, get_riverine_outlook


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(predictive_riverine.router)
    return TestClient(app)


def test_marala_snapshot_has_every_horizon():
    body = _client().get("/predictive/riverine-outlook/marala").json()
    assert body["available"] is True
    assert body["station"]["id"] == "MARALA"
    seasonal = body["seasonal"]
    assert len(seasonal["daily"]) == 180
    issue = date.fromisoformat(seasonal["issue_date"])
    assert date.fromisoformat(seasonal["daily"][0]["date"]) == issue + timedelta(days=1)
    for row in seasonal["daily"]:
        assert row["p10"] <= row["p50"] <= row["p90"]
    assert {h["horizon_days"] for h in body["seasonal_means"]["horizons"]} == {90, 180}
    assert {s["id"] for s in body["climate"]["scenarios"]} == {"ssp245", "ssp585"}
    assert len(body["climate"]["typical_year_hydrograph"]["baseline"]) == 365
    assert body["flood_classes_cumecs"]["Low"] < body["flood_classes_cumecs"]["Exceptional"]


def test_station_without_models_returns_empty_shape():
    body = _client().get("/predictive/riverine-outlook/KHANKI").json()
    assert body == {"station": {"id": "KHANKI"}, "available": False, "reason": body["reason"]}
    assert "Marala" in body["reason"]


def test_snapshot_is_flagged_stale_when_old():
    issue = date.fromisoformat(get_riverine_outlook("MARALA")["seasonal"]["issue_date"])
    assert get_riverine_outlook("MARALA", today=issue + timedelta(days=STALE_AFTER_DAYS))["stale"] is False
    assert get_riverine_outlook("MARALA", today=issue + timedelta(days=STALE_AFTER_DAYS + 1))["stale"] is True


def test_snapshot_file_exists():
    assert SNAPSHOTS["MARALA"].is_file()


def test_replay_covers_every_trained_short_range_model():
    replay = get_riverine_outlook("MARALA")["replay"]
    assert len(replay["models"]) == 24
    assert {m["family"] for m in replay["models"]} == {"baseline", "statistical", "ai", "physics", "hybrid"}
    assert [e["id"] for e in replay["events"]] == ["2022", "2023", "2024"]
    lead10 = replay["scores"]["10"]["models"]
    assert set(lead10) == {m["id"] for m in replay["models"] if m["max_lead"] >= 10}
    # Matched scoring: every model at a lead is scored on the same number of pairs.
    assert len({s["n"] for s in lead10.values()}) == 1
    lead30 = replay["scores"]["30"]["models"]
    assert set(lead30) == {m["id"] for m in replay["models"] if m["max_lead"] >= 30}
    event = replay["events"][1]
    assert len(replay["series"][event["id"]]["10"]["hbv_lstm"]["values"]) == len(event["observed"])
