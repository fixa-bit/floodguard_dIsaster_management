from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.db.monitoring import get_monitoring_db
from app.main import app
from app.models.incident import Incident
from app.models.monitoring_simulation_run import MonitoringSimulationRun
from app.models.system_event import SystemEvent
from app.schemas.monitoring_simulation import MonitoringSimulationRequest
from app.services.monitoring_simulation_service import MonitoringSimulationService
from monitoring.database import create_monitoring_engine, session_factory
from monitoring.migrations.runner import upgrade
from monitoring.models import Provider, Station, StationValue, Threshold
from monitoring.repository import store_value
from monitoring.seed import seed


@pytest.fixture
def monitoring_db(tmp_path):
    engine = create_monitoring_engine(f"sqlite:///{(tmp_path / 'monitoring.db').as_posix()}")
    upgrade(engine)
    sessions = session_factory(engine)
    with sessions.begin() as session:
        seed(session)
    with sessions() as session:
        app.dependency_overrides[get_monitoring_db] = lambda: session
        yield session
    app.dependency_overrides.pop(get_monitoring_db, None)
    engine.dispose()


def scenario(**overrides):
    return {
        "run_id": str(uuid4()), "name": "Taunsa threshold test", "station": "TAUNSA",
        "measurement": "discharge_inflow", "unit": "cusecs", "start_at": "2026-10-12T10:00:00+05:00",
        "threshold_mode": "custom", "warning_threshold": 300000, "danger_threshold": 600000,
        "readings": [{"offset_minutes": 0, "value": 299999}, {"offset_minutes": 60, "value": 300000},
                     {"offset_minutes": 120, "value": 600000}],
        **overrides,
    }


def play(client, payload):
    return client.post("/api/v1/simulation/monitoring/play", json=payload)


def test_play_saves_simulated_alerts_and_approval_creates_persistent_incidents(client, monitoring_db):
    payload = scenario()
    response = play(client, payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["inserted"] == 3
    assert [row["level"] for row in result["readings"]] == ["normal", "warning", "danger"]
    assert len(result["alerts"]) == 2
    assert result["incidents"] == []
    values = list(monitoring_db.scalars(select(StationValue).order_by(StationValue.id)))
    assert len(values) == 3
    assert all(row.value_type == "simulated" and row.forecast_issued_at is None for row in values)
    assert values[0].value_at.isoformat() == "2026-10-12T05:00:00+00:00"
    provider = monitoring_db.get(Provider, values[0].provider_id)
    assert provider.code.startswith("SIMULATED_FLOW_")
    assert provider.kind == "import"
    alerts = client.get("/api/v1/alerts").json()
    incidents = client.get("/api/v1/incidents").json()
    assert len(alerts) == 2
    assert incidents == []
    for alert in alerts:
        metadata = alert["event_metadata"]
        assert metadata["source"] == "SIMULATED_FLOW"
        assert metadata["threshold_mode"] == "custom"
        assert metadata["run_id"] == payload["run_id"]
        assert metadata["approval_status"] == "pending"
        assert "incident_id" not in metadata
    for alert in alerts:
        approved = client.post(f"/api/v1/alerts/{alert['id']}/approve")
        assert approved.status_code == 200, approved.text
        assert approved.json()["event_metadata"]["approval_status"] == "approved"
    incidents = client.get("/api/v1/incidents").json()
    assert {incident["severity"] for incident in incidents} == {"HIGH", "CRITICAL"}
    for alert in client.get("/api/v1/alerts").json():
        metadata = alert["event_metadata"]
        incident = next(row for row in incidents if row["id"] == metadata["incident_id"])
        assert incident["source"] == "SIMULATED_FLOW" and incident["location_id"] == "TAUNSA"
        assert "SIMULATED FLOW" in incident["description"]
    assert all(row.value is None for row in monitoring_db.scalars(select(Threshold)))


def test_below_threshold_saves_readings_without_alert_or_incident(client, monitoring_db):
    payload = scenario(readings=[{"value": 299999, "p25": 290000, "p75": 310000}])
    result = play(client, payload).json()
    assert result["inserted"] == 1
    assert result["alerts"] == result["incidents"] == []
    assert client.get("/api/v1/alerts").json() == []
    assert client.get("/api/v1/incidents").json() == []
    row = monitoring_db.scalar(select(StationValue))
    assert (row.p25, row.p75) == (290000, 310000)


def test_retry_is_idempotent_and_changed_payload_conflicts(client, monitoring_db):
    payload = scenario()
    first = play(client, payload)
    second = play(client, payload)
    assert second.status_code == 200
    assert first.json() == second.json()
    assert monitoring_db.scalar(select(func.count()).select_from(StationValue)) == 3
    assert len(client.get("/api/v1/alerts").json()) == 2
    assert client.get("/api/v1/incidents").json() == []
    assert play(client, {**payload, "name": "Changed run"}).status_code == 409


def test_alert_approval_is_idempotent_and_survives_reload(client):
    response = play(client, scenario(readings=[{"offset_minutes": 0, "value": 650000}]))
    assert response.status_code == 200, response.text
    alert_id = response.json()["alerts"][0]["id"]
    first = client.post(f"/api/v1/alerts/{alert_id}/approve")
    second = client.post(f"/api/v1/alerts/{alert_id}/approve")
    assert first.status_code == second.status_code == 200
    incident_id = first.json()["event_metadata"]["incident_id"]
    assert second.json()["event_metadata"]["incident_id"] == incident_id
    assert first.json()["event_metadata"]["approved_at"] == second.json()["event_metadata"]["approved_at"]
    # Every request opens a new DB session, just as the UI does after a reload.
    assert client.get("/api/v1/alerts").json()[0]["event_metadata"]["incident_id"] == incident_id
    incidents = client.get("/api/v1/incidents").json()
    assert len(incidents) == 1
    assert incidents[0]["id"] == incident_id and incidents[0]["source"] == "SIMULATED_FLOW"
    events = client.get("/api/v1/events").json()
    assert sum(event["event_type"] == "INCIDENT_CREATED" for event in events) == 1


def test_operational_alert_cannot_be_approved_as_simulated(client, db_session):
    alert = SystemEvent(event_type="ALERT_REQUIRED", location_id="TAUNSA", message="Operational alert", event_metadata={})
    db_session.add(alert)
    db_session.commit()
    assert client.post(f"/api/v1/alerts/{alert.id}/approve").status_code == 400
    assert client.get("/api/v1/incidents").json() == []


def test_saved_thresholds_match_station_measurement_and_units(client, monitoring_db):
    station = monitoring_db.scalar(select(Station).where(Station.code == "TAUNSA"))
    limit = monitoring_db.scalar(select(Threshold).where(
        Threshold.station_id == station.id, Threshold.measurement == "discharge_inflow", Threshold.level == "warning"))
    limit.value = 300000
    monitoring_db.commit()
    payload = scenario(threshold_mode="saved", warning_threshold=None, danger_threshold=None,
                       readings=[{"value": 300000}])
    response = play(client, payload)
    assert response.status_code == 200, response.text
    assert response.json()["alerts"][0]["event_metadata"]["threshold_mode"] == "saved"
    assert play(client, {**payload, "run_id": str(uuid4()), "unit": "m3/s"}).status_code == 400
    assert play(client, {**payload, "run_id": str(uuid4()), "measurement": "discharge_outflow"}).status_code == 400
    options = client.get("/api/v1/simulation/monitoring/stations").json()
    taunsa = next(item for item in options if item["code"] == "TAUNSA")
    assert any(row["level"] == "warning" and row["value"] == 300000 for row in taunsa["thresholds"])


def test_water_level_requires_matching_gauge_datum(client, monitoring_db):
    station = monitoring_db.scalar(select(Station).where(Station.code == "TAUNSA"))
    limit = monitoring_db.scalar(select(Threshold).where(
        Threshold.station_id == station.id, Threshold.measurement == "water_level", Threshold.level == "danger"))
    limit.value, limit.level_reference = 8, "Taunsa gauge datum"
    monitoring_db.commit()
    payload = scenario(measurement="water_level", unit="m", threshold_mode="saved",
                       warning_threshold=None, danger_threshold=None, level_reference="Taunsa gauge datum",
                       readings=[{"value": 8}])
    assert play(client, {**payload, "level_reference": "Different datum"}).status_code == 400
    response = play(client, payload)
    assert response.status_code == 200, response.text
    assert response.json()["alerts"][0]["event_metadata"]["threshold_level"] == "danger"


@pytest.mark.parametrize("overrides", [
    {"station": "UNKNOWN"}, {"unit": "m"}, {"start_at": "2026-10-12T10:00:00"},
    {"warning_threshold": 600000, "danger_threshold": 300000},
    {"warning_threshold": None, "danger_threshold": None},
    {"readings": [{"value": -1}]}, {"readings": [{"value": 1, "p25": 3, "p75": 2}]},
    {"readings": [{"value": 1}, {"value": 2}]}, {"readings": []},
    {"measurement": "water_level", "unit": "m", "readings": [{"value": 4}]},
])
def test_invalid_input_does_not_write_any_data(client, monitoring_db, overrides):
    response = play(client, scenario(**overrides))
    assert response.status_code in {404, 422}, response.text
    assert monitoring_db.scalar(select(func.count()).select_from(StationValue)) == 0
    assert client.get("/api/v1/alerts").json() == []
    assert client.get("/api/v1/incidents").json() == []


def test_app_commit_failure_rolls_back_simulated_data(monitoring_db, db_session, monkeypatch):
    payload = MonitoringSimulationRequest.model_validate(scenario())
    def fail_commit():
        raise RuntimeError("Test commit failure")
    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="Test commit failure"):
        MonitoringSimulationService(db_session, monitoring_db).play(payload)
    assert monitoring_db.scalar(select(func.count()).select_from(StationValue)) == 0
    assert monitoring_db.scalar(select(Provider).where(Provider.code.startswith("SIMULATED_FLOW_"))) is None
    assert db_session.scalar(select(func.count()).select_from(Incident)) == 0
    assert db_session.scalar(select(func.count()).select_from(SystemEvent)) == 0
    assert db_session.scalar(select(func.count()).select_from(MonitoringSimulationRun)) == 0


def test_simulation_preserves_observed_readings(client, monitoring_db):
    observed, _ = store_value(monitoring_db, station="TAUNSA", provider="FFD", measurement="discharge_inflow",
                              value=100000, unit="cusecs", value_type="observed", value_at="2026-10-12T05:00:00Z")
    monitoring_db.commit()
    assert play(client, scenario()).status_code == 200
    monitoring_db.refresh(observed)
    assert observed.value == 100000 and observed.value_type == "observed"
