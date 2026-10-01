def start(client, scenario="NORMAL", location_id="JHG_001"):
    return client.post("/api/v1/simulation/start", json={"scenario": scenario, "location_id": location_id})


def risk(client, location_id="JHG_001"):
    return client.get(f"/api/v1/flood/risk?location_id={location_id}")


def test_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_normal_scenario_low_risk(client):
    start(client, "NORMAL")
    data = risk(client).json()
    assert data["severity"] == "LOW"
    assert data["monitoring_interval_minutes"] == 60


def test_heavy_rain_medium_risk(client):
    start(client, "HEAVY_RAIN")
    data = risk(client).json()
    assert data["severity"] == "MEDIUM"
    assert data["monitoring_interval_minutes"] == 30


def test_developing_flood_high_risk(client):
    start(client, "DEVELOPING_FLOOD")
    data = risk(client).json()
    assert data["severity"] == "HIGH"
    assert data["monitoring_interval_minutes"] == 15


def test_critical_flood_critical_risk(client):
    start(client, "CRITICAL_FLOOD")
    data = risk(client).json()
    assert data["severity"] == "CRITICAL"
    assert data["monitoring_interval_minutes"] == 5


def test_simulation_transitions(client):
    start(client, "NORMAL")
    first = client.post("/api/v1/simulation/advance").json()
    second = client.post("/api/v1/simulation/advance").json()
    assert first["scenario"] == "HEAVY_RAIN"
    assert second["scenario"] == "DEVELOPING_FLOOD"


def test_reset(client):
    start(client, "CRITICAL_FLOOD")
    reset = client.post("/api/v1/simulation/reset").json()
    assert reset["scenario"] == "NORMAL"


def test_citizen_report_create_and_retrieve(client):
    response = client.post(
        "/api/v1/citizen-reports",
        json={
            "location_id": "JHG_001",
            "latitude": 31.27,
            "longitude": 72.32,
            "description": "Water entering street",
            "reported_water_depth_cm": 20,
        },
    )
    assert response.status_code == 201
    report_id = response.json()["id"]
    retrieved = client.get(f"/api/v1/citizen-reports/{report_id}")
    assert retrieved.status_code == 200
    assert retrieved.json()["verification_status"] == "PENDING"


def test_events_created_for_risk(client):
    start(client, "DEVELOPING_FLOOD")
    risk(client)
    events = client.get("/api/v1/events").json()
    event_types = {event["event_type"] for event in events}
    assert "RISK_UPDATED" in event_types
    assert "MONITORING_MODE_CHANGED" in event_types


def test_invalid_location(client):
    response = risk(client, "BAD_ID")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "LOCATION_NOT_FOUND"
