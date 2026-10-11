from datetime import datetime, timedelta, timezone

from app.models.river_gauge_observation import RiverGaugeObservation


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
