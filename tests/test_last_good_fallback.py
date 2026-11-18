"""Live providers fall back to the last good response stored on disk."""
import asyncio
import json
import time
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from app.core.enums import Scenario
from app.core.exceptions import AppError
from app.providers import last_good_store
from app.providers.live.live_river_provider import LiveRiverProvider
from app.services import google_flood_service as google_module
from app.services.google_flood_service import GoogleFloodService
from tests.test_live_weather import river_payload


@pytest.fixture
def store_dir(monkeypatch, tmp_path):
    settings = SimpleNamespace(last_good_cache_dir=str(tmp_path), last_good_max_age_hours=72)
    monkeypatch.setattr(last_good_store, "get_settings", lambda: settings)
    return settings


def river_client(ok: bool) -> httpx.AsyncClient:
    response = (lambda _: httpx.Response(200, json=river_payload())) if ok else (lambda _: httpx.Response(500))
    return httpx.AsyncClient(transport=httpx.MockTransport(response))


@pytest.mark.asyncio
async def test_river_serves_last_good_reading_when_all_sources_fail(store_dir):
    async with river_client(ok=True) as client:
        live = await LiveRiverProvider(client).get_current("JHG_001", Scenario.NORMAL)
    async with river_client(ok=False) as client:
        stale = await LiveRiverProvider(client).get_current("JHG_001", Scenario.NORMAL)

    assert stale.discharge_cumecs == live.discharge_cumecs
    assert stale.timestamp == live.timestamp
    assert stale.data_note.startswith("Live river sources are unavailable; showing the last reading saved")


@pytest.mark.asyncio
async def test_river_error_when_nothing_saved_or_too_old(store_dir, tmp_path):
    async with river_client(ok=False) as client:
        with pytest.raises(AppError):
            await LiveRiverProvider(client).get_current("JHG_001", Scenario.NORMAL)

    async with river_client(ok=True) as client:
        await LiveRiverProvider(client).get_current("JHG_001", Scenario.NORMAL)
    path = tmp_path / "river-current-JHG_001.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["saved_at"] = time.time() - 73 * 3600
    path.write_text(json.dumps(stored), encoding="utf-8")
    async with river_client(ok=False) as client:
        with pytest.raises(AppError):
            await LiveRiverProvider(client).get_current("JHG_001", Scenario.NORMAL)


def test_google_flood_hub_survives_restart(monkeypatch, store_dir):
    settings = SimpleNamespace(google_flood_api_key=SecretStr("test-secret"), google_flood_region_codes="PK", google_flood_cache_seconds=600)
    monkeypatch.setattr(google_module, "get_settings", lambda: settings)
    fail = False

    def handler(request):
        if fail:
            return httpx.Response(503)
        if request.url.path.endswith("gauges:searchGaugesByArea"):
            return httpx.Response(200, json={"gauges": [{"gaugeId": "1", "siteName": "Indus", "location": {"latitude": 30, "longitude": 72}}]})
        return httpx.Response(200, json={"floodStatuses": [{"gaugeId": "1", "severity": "SEVERE"}]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(google_module.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))

    live = asyncio.run(GoogleFloodService().feature_collection())
    assert live["metadata"]["status"] == "live"
    fail = True
    restarted = asyncio.run(GoogleFloodService().feature_collection())
    assert restarted["metadata"]["status"] == "stale"
    assert restarted["features"] == live["features"]
    assert restarted["metadata"]["fetched_at"] == live["metadata"]["fetched_at"]
    assert "test-secret" not in str(restarted)
