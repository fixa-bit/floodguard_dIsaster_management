from datetime import datetime, timedelta, timezone

import pytest

from app.gis.national_risk_service import NationalRiskService


def test_national_gis_covers_pakistan_districts_in_simulation(client):
    response = client.get("/api/v1/gis/national-risk")
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "FeatureCollection"
    assert data["metadata"]["coverage"] == "Pakistan ADM2 districts"
    assert data["metadata"]["data_mode"] == "simulation"
    assert data["metadata"]["feature_count"] == 126
    assert len(data["features"]) == 126
    assert all(feature["properties"]["risk_basis"] == "district_weather_screening" for feature in data["features"])
    assert response.headers["content-encoding"] == "gzip"


def test_national_gis_supports_viewport_filtering(client):
    response = client.get("/api/v1/gis/national-risk?bbox=66,24,68,26")
    assert response.status_code == 200
    data = response.json()
    assert 0 < data["metadata"]["returned_feature_count"] < data["metadata"]["feature_count"]
    assert len(data["features"]) == data["metadata"]["returned_feature_count"]


def test_national_gis_rejects_invalid_bbox(client):
    response = client.get("/api/v1/gis/national-risk?bbox=70,30,60,20")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_BBOX"


def test_water_intelligence_separates_gis_stations_and_model_points(client):
    response = client.get("/api/v1/gis/water-intelligence")
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "FeatureCollection"
    assert data["metadata"]["observed_station_count"] > 0
    assert data["metadata"]["model_forecast_count"] == 4
    classes = {feature["properties"]["data_class"] for feature in data["features"]}
    assert {"gis_feature", "observed_station", "model_forecast"} <= classes
    rivers = [feature for feature in data["features"] if feature["properties"]["feature_kind"] == "river"]
    assert len(rivers) == 6
    assert all(feature["geometry"]["type"] == "MultiLineString" for feature in rivers)
    assert all(feature["properties"]["geometry_source"] == "WaterwayMap/OpenStreetMap" for feature in rivers)
    assert data["metadata"]["map_notice"] == "River alignments are schematic unless source geometry is marked official."
    observed = [feature for feature in data["features"] if feature["properties"]["data_class"] == "observed_station"]
    assert all(feature["properties"]["coordinate_quality"] == "approximate" for feature in observed)
    assert all(feature["properties"]["observed_level_m"] is None for feature in observed)
    assert all(feature["properties"]["observed_discharge_cumecs"] is None for feature in observed)


def test_water_intelligence_supports_bbox_filtering(client):
    response = client.get("/api/v1/gis/water-intelligence?bbox=71,30,73,32")
    assert response.status_code == 200
    data = response.json()
    assert 0 < data["metadata"]["returned_feature_count"] < data["metadata"]["feature_count"]
    assert len(data["features"]) == data["metadata"]["returned_feature_count"]


def test_national_gis_simulation_is_deterministic_and_scenario_aware(client):
    normal = client.get("/api/v1/gis/national-risk").json()
    client.post("/api/v1/simulation/start", json={"scenario": "CRITICAL_FLOOD", "location_id": "JHG_001"})
    critical = client.get("/api/v1/gis/national-risk").json()
    assert normal["features"][0]["properties"]["risk_probability"] < critical["features"][0]["properties"]["risk_probability"]
    assert critical["metadata"]["scenario"] == "CRITICAL_FLOOD"


def test_district_dataset_has_unique_ids_and_geometries():
    districts = NationalRiskService.districts()
    assert len({district["id"] for district in districts}) == len(districts)
    assert all(district["geometry"]["type"] in {"Polygon", "MultiPolygon"} for district in districts)


@pytest.mark.asyncio
async def test_live_national_gis_batches_all_districts(monkeypatch):
    service = NationalRiskService()
    calls = []
    start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=24)
    payload = {
        "hourly": {
            "time": [(start + timedelta(hours=index)).replace(tzinfo=None).isoformat(timespec="minutes") for index in range(50)],
            "precipitation": [1.0] * 50,
            "temperature_2m": [28.0] * 50,
            "relative_humidity_2m": [80.0] * 50,
            "soil_moisture_0_to_7cm": [0.4] * 50,
        }
    }

    async def fake_batch(districts):
        calls.append(len(districts))
        return [payload for _ in districts]

    monkeypatch.setattr(service, "_weather_batch", fake_batch)
    collection = await service._live_collection()
    assert calls == [40, 40, 40, 6]
    assert len(collection["features"]) == 126
    assert collection["features"][0]["properties"]["source"] == "live"
    assert collection["features"][0]["properties"]["rainfall_24h_mm"] == 24.0

