from datetime import datetime, timedelta, timezone

from app.models.river_gauge_observation import RiverGaugeObservation
from app.models.river_gauge_observation import TypedRiverGaugeObservation
from app.services.ffd_bulletin_service import ffd_bulletins


def test_history_is_station_scoped_recent_ordered_and_utc(client, db_session):
    now = datetime.now(timezone.utc)
    db_session.add_all([
        RiverGaugeObservation(station_id="TAUNSA", recorded_at=now - timedelta(hours=24), discharge_cumecs=100),
        RiverGaugeObservation(station_id="TAUNSA", recorded_at=now - timedelta(hours=3), discharge_cumecs=125),
        RiverGaugeObservation(station_id="TAUNSA", recorded_at=now, discharge_cumecs=130),
        RiverGaugeObservation(station_id="TAUNSA", recorded_at=now - timedelta(hours=49), discharge_cumecs=50),
        RiverGaugeObservation(station_id="GUDDU", recorded_at=now, discharge_cumecs=250),
    ])
    db_session.commit()
    response = client.get("/api/v1/river/monitoring/TAUNSA/history")
    assert response.status_code == 200
    data = response.json()
    assert data["station_id"] == "TAUNSA"
    assert data["source"] == "FFD stored observations"
    assert [row["value"] for row in data["samples"]] == [100, 125, 130]
    assert all(row["time"].endswith("+00:00") for row in data["samples"])
    assert client.get("/api/v1/river/monitoring/CHASHMA/history").json()["samples"] == []
    assert client.get("/api/v1/river/monitoring/UNKNOWN/history").status_code == 404


def test_official_history_never_mixes_gauges_or_legacy_values(client, db_session, monkeypatch):
    now = datetime.now(timezone.utc)
    bulletin_time = (now - timedelta(hours=6)).astimezone(timezone(timedelta(hours=5)))
    async def latest():
        return {"Trimmu": {"samples": {"INFLOW": {"time": bulletin_time.isoformat(), "value": 453.07, "source": "https://ffd.pmd.gov.pk/b/test"}},
                           "forecast": {"gauge": "INFLOW", "text": "No sig. change", "low": None, "high": None}}}
    monkeypatch.setattr(ffd_bulletins, "get", latest)
    db_session.add_all([
        RiverGaugeObservation(station_id="TRIMMU", recorded_at=now, discharge_cumecs=999),
        TypedRiverGaugeObservation(station_id="TRIMMU", gauge="INFLOW", recorded_at=now, discharge_cumecs=434.92, source="FFD live"),
        TypedRiverGaugeObservation(station_id="TRIMMU", gauge="OUTFLOW", recorded_at=now, discharge_cumecs=32.82, source="FFD live"),
        TypedRiverGaugeObservation(station_id="TAUNSA", gauge="INFLOW", recorded_at=now, discharge_cumecs=2000, source="FFD live"),
    ])
    db_session.commit()
    path = "/api/v1/river/monitoring/TRIMMU/official-history"
    inflow = client.get(path).json()
    assert [sample["value"] for sample in inflow["samples"]] == [453.07, 434.92]
    assert inflow["official_forecast"]["low"] is None
    assert inflow["samples"][0]["source"] == "https://ffd.pmd.gov.pk/b/test"
    assert datetime.fromisoformat(inflow["samples"][0]["time"]) == bulletin_time, "PKT storage retains the actual UTC instant"
    outflow = client.get(path + "?gauge=OUTFLOW").json()
    assert [sample["value"] for sample in outflow["samples"]] == [32.82]
    assert outflow["official_forecast"] is None
    assert client.get(path + "?gauge=BAD").status_code == 422
    assert client.get("/api/v1/river/monitoring/UNKNOWN/official-history").status_code == 404


def test_official_history_feed_failure_does_not_use_legacy(client, monkeypatch):
    async def unavailable():
        raise ValueError("Unexpected bulletin layout")
    monkeypatch.setattr(ffd_bulletins, "get", unavailable)
    data = client.get("/api/v1/river/monitoring/TRIMMU/official-history").json()
    assert data["samples"] == [] and data["official_forecast"] is None and data["error"]
