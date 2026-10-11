import io
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import func, select

from app.gis.hydrograph_config import station_configs
from app.models.station_observation import StationObservation
from app.providers.open_meteo_hydrograph import FIELDS, OpenMeteoHydrograph, cusecs, normalize, open_meteo_hydrograph
from app.services.station_ingestion import import_csv, store_readings
from app.providers.irsa_report_parser import parse_report
from tests.test_ffd_bulletin import bulletin


def model_payload():
    today = datetime.now(timezone.utc).date()
    times = [(today + timedelta(days=i)).isoformat() for i in range(-7, 5)]
    return {"latitude": 30.525, "longitude": 70.825, "daily_units": {field: "m\u00b3/s" for field in FIELDS},
            "daily": {"time": times, **{field: [1000 + i * 10 for i in range(12)] for field in FIELDS}}}


def test_normalization_has_no_fake_observed_model_history():
    result = normalize(model_payload())
    assert len(result["forecast"]) == 5
    assert result["forecast"][0]["v"] == round(1070 * 35.3147, 2)
    assert result["forecast"][0]["p25"] == result["forecast"][0]["v"]
    for value in [None, "NaN", float("nan"), float("inf"), -1, True, 1e308]:
        assert cusecs(value) is None
    payload = model_payload()
    payload["daily_units"][FIELDS[0]] = "cusecs"
    with pytest.raises(ValueError):
        normalize(payload)


@pytest.mark.asyncio
async def test_model_cache_and_stale_fallback(monkeypatch):
    calls = []
    failed = False
    def handler(request):
        calls.append(request)
        return httpx.Response(503 if failed else 200, json={} if failed else model_payload())
    async def no_wait(_):
        pass
    monkeypatch.setattr("app.providers.open_meteo_hydrograph.asyncio.sleep", no_wait)
    provider = OpenMeteoHydrograph(httpx.MockTransport(handler))
    station = station_configs()["TAUNSA"]
    first = await provider.get(station, 5)
    assert calls[0].url.params["forecast_days"] == "5"
    assert calls[0].url.params["past_days"] == "7"
    assert await provider.get(station, 5) == first and len(calls) == 1
    key = next(iter(provider.cache))
    provider.cache[key] = (time.monotonic() - 5 * 3600, first)
    failed = True
    stale = await provider.get(station, 5)
    assert len(calls) == 4 and stale["stale"] and stale["forecast"] == first["forecast"]
    unavailable = await provider.get(station, 30)
    assert unavailable["forecastUnavailable"] and not unavailable["forecast"]


def test_ingestion_timezone_dedup_and_atomic_validation(db_session):
    timestamp = (datetime.now(timezone.utc) - timedelta(hours=6)).astimezone(timezone(timedelta(hours=5))).isoformat()
    csv = f"station_id,observed_at,discharge_cusecs,source\nTAUNSA,{timestamp},84200,IRSA supplied CSV inflow\n"
    assert import_csv(db_session, io.StringIO(csv)) == 1
    import_csv(db_session, io.StringIO(csv))
    assert db_session.scalar(select(func.count()).select_from(StationObservation)) == 1
    row = db_session.scalar(select(StationObservation))
    assert row.observed_at.replace(tzinfo=timezone.utc) == datetime.fromisoformat(timestamp)
    bad = csv + f"UNKNOWN,{timestamp},500,Invalid\n"
    with pytest.raises(ValueError):
        import_csv(db_session, io.StringIO(bad))
    assert db_session.scalar(select(func.count()).select_from(StationObservation)) == 1
    parsed = parse_report(bulletin(inflow="16.0", outflow="1.2"), "https://ffd.pmd.gov.pk/bulletin")
    assert parsed[0]["discharge_cusecs"] == 16000
    assert parsed[0]["source"].startswith("FFD bulletin inflow")


def test_endpoint_queries_validation_sources_and_no_internal_errors(client, db_session, monkeypatch):
    async def model(station, days):
        return normalize(model_payload())
    monkeypatch.setattr(open_meteo_hydrograph, "get", model)
    store_readings(db_session, [{"station_id": "TAUNSA", "observed_at": datetime.now(timezone.utc) - timedelta(hours=1), "discharge_cusecs": 84200, "source": "IRSA supplied CSV inflow"}])
    path = "/api/stations/TAUNSA/hydrograph"
    data = client.get(path + "?days=5").json()
    assert data["unit"] == "cusecs" and data["observed"][0]["v"] == 84200
    assert data["sources"]["observed"] == ["IRSA supplied CSV inflow"]
    assert all(v is None for v in data["thresholds"].values())
    assert client.get(path + "?days=30").status_code == 200
    assert client.get(path + "?days=10").status_code == 422
    assert client.get("/api/stations/UNKNOWN/hydrograph").status_code == 404
    assert client.get("/api/stations/MANGLA/hydrograph").json()["observed"] == []
    async def unavailable(station, days):
        return {"forecast": [], "modelCell": None, "generatedAt": datetime.now(timezone.utc).isoformat(), "stale": False, "forecastUnavailable": True}
    monkeypatch.setattr(open_meteo_hydrograph, "get", unavailable)
    assert client.get(path).status_code == 200  # Stored observations survive a forecast outage.
    response = client.get("/api/stations/MANGLA/hydrograph")
    assert response.status_code == 503 and "traceback" not in response.text.lower()
