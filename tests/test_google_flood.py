import asyncio
from types import SimpleNamespace

import httpx
from pydantic import SecretStr

from app.services import google_flood_service as module
from app.services.google_flood_service import GoogleFloodService


def configure(monkeypatch, key="test-secret"):
    settings = SimpleNamespace(
        google_flood_api_key=SecretStr(key),
        google_flood_region_codes="PK",
        google_flood_cache_seconds=600,
    )
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    return settings


def test_missing_key_returns_no_fabricated_points(monkeypatch, client):
    configure(monkeypatch, "")
    response = client.get("/api/v1/gis/google-flood-hub")
    assert response.status_code == 200
    assert response.json()["features"] == []
    assert response.json()["metadata"]["status"] == "not_configured"


def test_severity_coordinates_and_missing_forecasts():
    gauges = [{"gaugeId": str(i), "siteName": f"Site {i}", "location": {"latitude": 30 + i, "longitude": 72}} for i in range(6)]
    statuses = [{"gaugeId": str(i), "severity": severity, "issuedTime": "2026-10-10T10:00:00Z", "forecastTimeRange": {"start": "2026-10-10T10:00:00Z", "end": "2026-10-17T10:00:00Z"}} for i, severity in enumerate(["EXTREME", "SEVERE", "ABOVE_NORMAL", "NO_FLOODING", "UNKNOWN"])]
    features = GoogleFloodService.features(gauges, statuses)
    assert [feature["properties"]["severity_label"] for feature in features] == ["Extreme", "Danger", "Warning", "Normal", "No data", "No data"]
    assert features[0]["geometry"]["coordinates"] == [72, 30]
    assert features[0]["properties"]["forecast_end"] == "2026-10-17T10:00:00Z"
    assert features[-1]["properties"]["issued_at"] is None
    assert GoogleFloodService.features([{"gaugeId": "bad", "location": {"latitude": float("nan"), "longitude": 72}}], []) == []


def test_pagination_cache_and_stale_refresh(monkeypatch):
    configure(monkeypatch)
    calls = []
    fail = False

    def handler(request):
        import json
        calls.append(request)
        assert request.headers["X-Goog-Api-Key"] == "test-secret"
        assert "key=" not in str(request.url)
        if fail:
            return httpx.Response(403, json={"error": {"message": "test-secret"}})
        body = json.loads(request.content)
        assert body["regionCode"] == "PK"
        if request.url.path.endswith("gauges:searchGaugesByArea"):
            if body.get("pageToken") == "second":
                return httpx.Response(200, json={"gauges": [{"gaugeId": "2", "location": {"latitude": 31, "longitude": 73}}]})
            return httpx.Response(200, json={"gauges": [{"gaugeId": "1", "siteName": "Indus", "location": {"latitude": 30, "longitude": 72}}], "nextPageToken": "second"})
        return httpx.Response(200, json={"floodStatuses": [{"gaugeId": "1", "severity": "NO_FLOODING"}]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    service = GoogleFloodService()

    async def run():
        nonlocal fail
        live = await service.feature_collection()
        assert live["metadata"]["status"] == "live"
        assert len(live["features"]) == 2
        assert live["features"][1]["properties"]["severity"] == "UNKNOWN"
        assert await service.feature_collection() == live
        assert len(calls) == 3
        fail = True
        service._expires = 0
        stale = await service.feature_collection()
        assert stale["metadata"]["status"] == "stale"
        assert stale["features"] == live["features"]
        assert stale["metadata"]["fetched_at"] == live["metadata"]["fetched_at"]
        assert "test-secret" not in str(stale)

    asyncio.run(run())


def test_denied_access_does_not_expose_credentials(monkeypatch):
    settings = configure(monkeypatch)
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(403, json={"error": "test-secret"}))
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: real_client(transport=transport, **kwargs))
    service = GoogleFloodService()
    result = asyncio.run(service.feature_collection())
    assert result["metadata"]["status"] == "unavailable"
    assert result["features"] == []
    assert "test-secret" not in str(result)
    settings.google_flood_api_key = SecretStr("")
    assert asyncio.run(service.feature_collection())["metadata"]["status"] == "not_configured"
