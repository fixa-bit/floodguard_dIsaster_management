from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.core.enums import DataMode, Scenario
from app.db.session import SessionLocal
from app.gis.river_stations import RIVER_CHAINS, STATIONS, upstream_ids
from app.gis.water_intelligence_service import WaterIntelligenceService
from app.models.river_gauge_observation import RiverGaugeObservation
from app.services.river_monitoring_service import RiverMonitoringService


def test_complete_network_and_shared_panjnad():
    assert len(STATIONS) == 22
    assert RIVER_CHAINS["Indus"] == ["TARBELA", "KALABAGH", "CHASHMA", "TAUNSA", "GUDDU", "SUKKUR", "KOTRI"]
    assert RIVER_CHAINS["Kabul"] == ["NOWSHERA"]
    assert RIVER_CHAINS["Jhelum"] == ["MANGLA", "RASUL"]
    assert RIVER_CHAINS["Ravi"] == ["JASSAR", "SHAHDARA", "BALLOKI", "SIDHNAI"]
    assert upstream_ids("PANJNAD") == ["MARALA", "KHANKI", "QADIRABAD", "TRIMMU", "GANDA_SINGH_WALA", "SULEMANKI", "ISLAM"]
    collection = WaterIntelligenceService().feature_collection(DataMode.LIVE, Scenario.NORMAL)
    markers = [feature for feature in collection["features"] if feature["properties"].get("monitoring_station_id")]
    assert len(markers) == 22
    assert len({feature["properties"]["monitoring_station_id"] for feature in markers}) == 22


@pytest.mark.asyncio
async def test_batch_normalization_observed_fallback_and_peak():
    service = RiverMonitoringService()
    today = datetime.now(timezone.utc).date()
    definition = dict(id="TRIMMU", name="Trimmu", river="Chenab", latitude=31.1448, longitude=72.146, ffd_name="Trimmu")
    payload = {"daily": {"time": [(today + timedelta(days=offset)).isoformat() for offset in [-1, 0, 1, 2]], "river_discharge": [50, 60, 80, 100]}}
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=[payload, payload])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        models = await service._models(client, [definition, definition])
    assert len(calls) == 1
    assert len(models) == 2
    observed = {"discharge": "10,000", "status": "HIGH", "recording_time": datetime.now(timezone(timedelta(hours=5))).strftime("%d-%b %H PKT")}
    station = service._station(definition, models[0], observed)
    assert station.current_discharge_cumecs == 283.17
    assert station.current_source == "FFD observed"
    assert station.change_24h_cumecs == 10
    assert station.change_source == "GloFAS modeled 24h change"
    assert station.forecast_discharge_cumecs == 80
    assert station.flood_category == "High flood"
    assert station.expected_peak_at == (today + timedelta(days=2)).isoformat()
    fallback = service._station(definition, models[0], None)
    assert fallback.current_discharge_cumecs == 60
    assert fallback.current_source == "GloFAS modeled"
    assert fallback.flood_category == "Unavailable"
    recorded_at = datetime.fromisoformat(station.observed_at)
    with SessionLocal() as db:
        db.add(RiverGaugeObservation(station_id="TRIMMU", recorded_at=recorded_at - timedelta(hours=24), discharge_cumecs=200))
        db.commit()
    service._store_observations([station])
    service._store_observations([station])
    assert station.change_24h_cumecs == 83.17
    assert station.change_source == "FFD observed 24h change"


@pytest.mark.asyncio
async def test_wrong_batch_length_cannot_misassign_forecasts():
    service = RiverMonitoringService()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))) as client:
        models = await service._models(client, [{"latitude": 1, "longitude": 2}])
    assert len(models) == 1
    assert models[0].status == "unavailable"
