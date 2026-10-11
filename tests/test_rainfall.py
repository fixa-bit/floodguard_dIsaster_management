from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.core.exceptions import AppError
from app.gis.geometry import point_in_geometry
from app.gis.rainfall_service import RainfallService, rainfall_coverage, rainfall_sample_points


def hourly_payload(now):
    end = now.replace(minute=0, second=0, microsecond=0)
    return {"hourly": {"time": [(end + timedelta(hours=offset)).isoformat() for offset in range(-24, 73)],
                       "precipitation": [1.0] * 97}}


def test_rainfall_windows_and_missing_hours():
    now = datetime(2026, 10, 10, 12, 40, tzinfo=timezone.utc)
    payload = hourly_payload(now)
    assert RainfallService.accumulations(payload, now) == {
        "last_1h": 1, "last_3h": 3, "last_6h": 6, "last_24h": 24, "next_24h": 24, "next_72h": 72}
    payload["hourly"]["precipitation"][-1] = None
    metrics = RainfallService.accumulations(payload, now)
    assert metrics["next_72h"] is None
    assert metrics["next_24h"] == 24
    payload["hourly"]["precipitation"][24] = float("nan")
    assert RainfallService.accumulations(payload, now)["last_1h"] is None


def test_hydrological_coverage():
    geometry = rainfall_coverage()["features"][0]["geometry"]
    for point in ((74.8, 34.08), (77.58, 34.15), (69.17, 34.55), (77.19, 32.24), (78.72, 31.8), (79.7, 32.5)):
        assert point_in_geometry(*point, geometry), point
        assert point in rainfall_sample_points()
    assert not point_in_geometry(77.23, 28.61, geometry)
    assert all(point_in_geometry(*point, geometry) for point in rainfall_sample_points())


def test_rainfall_endpoint(client, monkeypatch):
    async def regional_feed(self):
        return {"type": "FeatureCollection", "features": [], "coverage": rainfall_coverage(),
                "metadata": {"source": "test provider"}}

    monkeypatch.setattr(RainfallService, "feature_collection", regional_feed)
    response = client.get("/api/v1/gis/rainfall")
    assert response.status_code == 200
    assert response.json()["coverage"]["features"]


@pytest.mark.asyncio
async def test_regional_feed_cache_and_stale_fallback(monkeypatch):
    RainfallService.clear_cache()
    monkeypatch.setattr("app.gis.rainfall_service.rainfall_sample_points", lambda: ((74.8, 34.08), (69.17, 34.55)))
    calls = []
    fail = False

    def handler(request):
        calls.append(request)
        assert request.url.params["forecast_hours"] == "73"
        if fail:
            return httpx.Response(503)
        return httpx.Response(200, json=[hourly_payload(datetime.now(timezone.utc))] * 2)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = RainfallService(client)
        result = await service.feature_collection()
        assert len(result["features"]) == 2
        assert result["features"][0]["properties"]["accumulations_mm"]["next_72h"] == 72
        assert result["metadata"]["missing_samples"] == 0
        result["features"].clear()
        assert len((await service.feature_collection())["features"]) == 2
        assert len(calls) == 1
        RainfallService._cache = (datetime.now(timezone.utc) - timedelta(days=1), RainfallService._cache[1])
        fail = True
        stale = await service.feature_collection()
        assert stale["metadata"]["cache_status"] == "stale"
        assert len(stale["features"]) == 2
        RainfallService.clear_cache()
        with pytest.raises(AppError):
            await service.feature_collection()
    RainfallService.clear_cache()


@pytest.mark.asyncio
async def test_partial_regional_feed_preserves_missing_values(monkeypatch):
    RainfallService.clear_cache()
    monkeypatch.setattr("app.gis.rainfall_service.rainfall_sample_points", lambda: tuple((74.8, 34.08) for _ in range(41)))

    def handler(request):
        if len(request.url.params["latitude"].split(",")) == 1:
            return httpx.Response(503)
        payload = hourly_payload(datetime.now(timezone.utc))
        payload["hourly"]["precipitation"][-1] = None
        return httpx.Response(200, json=[payload] * 40)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await RainfallService(client).feature_collection()
    assert len(result["features"]) == 40
    assert result["metadata"]["missing_samples"] == 1
    assert result["metadata"]["warning"]
    assert result["features"][0]["properties"]["accumulations_mm"]["next_72h"] is None
    RainfallService.clear_cache()
