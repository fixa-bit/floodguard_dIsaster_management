import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.models.upstream_forecast_snapshot import UpstreamForecastSnapshot
from app.schemas.upstream_forecast import UpstreamForecastResponse
from app.services.upstream_forecast_cache_service import UpstreamForecastCacheService
from app.services.upstream_forecast_service import UPSTREAM_STATIONS


@pytest.fixture
def cache_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cache.db'}", connect_args={"check_same_thread": False})
    UpstreamForecastSnapshot.__table__.create(engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


def forecast(value=10):
    station = {key: value for key, value in UPSTREAM_STATIONS[0].items() if key != "geoglows_river_id"}
    station.update(providers=[{
        "provider": "GloFAS", "source": "test", "status": "available",
        "series": [{"time": "2026-10-06", "value": value, "phase": "forecast"}], "retrospective": [],
    }], rainfall=[], flood_types=[], stats={})
    return UpstreamForecastResponse(generated_at=datetime.now(timezone.utc).isoformat(), stations=[station], notes=[])


def seed(factory, payload, overdue=False):
    now = datetime.now(timezone.utc)
    with factory() as db:
        db.add(UpstreamForecastSnapshot(id=1, payload=payload.model_dump(mode="json"), cached_at=now,
                                       next_refresh_at=now + timedelta(minutes=-1 if overdue else 60)))
        db.commit()


@pytest.mark.asyncio
async def test_cached_values_survive_service_restart_without_provider_call(cache_db):
    seed(cache_db, forecast())
    fetch = AsyncMock(side_effect=AssertionError("Cached read must not fetch providers"))
    for _ in range(2):
        cache = UpstreamForecastCacheService(cache_db, lambda: SimpleNamespace(forecasts=fetch))
        result = await cache.get()
        assert result.stations[0].providers[0].series[0].value == 10
        assert result.cached_at and result.next_refresh_at
        assert not result.refreshing
    fetch.assert_not_called()


@pytest.mark.asyncio
async def test_overdue_read_returns_stored_values_while_refresh_runs(cache_db):
    seed(cache_db, forecast(), overdue=True)
    release = asyncio.Event()

    async def fetch():
        await release.wait()
        return forecast(25)

    cache = UpstreamForecastCacheService(cache_db, lambda: SimpleNamespace(forecasts=fetch))
    try:
        result = await asyncio.wait_for(cache.get(), 2)
        assert result.refreshing
        assert result.stations[0].providers[0].series[0].value == 10
        release.set()
        await cache.refresh_task
        updated = await cache.get()
        assert updated.stations[0].providers[0].series[0].value == 25
        assert updated.cached_at and updated.last_attempt_at
        assert not updated.refreshing
    finally:
        await cache.stop()


@pytest.mark.asyncio
async def test_concurrent_manual_refreshes_share_one_fetch(cache_db):
    seed(cache_db, forecast())
    release = asyncio.Event()

    async def fetch():
        await release.wait()
        return forecast(30)

    fetch_mock = AsyncMock(side_effect=fetch)
    cache = UpstreamForecastCacheService(cache_db, lambda: SimpleNamespace(forecasts=fetch_mock))
    try:
        results = await asyncio.gather(*(cache.get(force_refresh=True) for _ in range(5)))
        assert all(result.refreshing for result in results)
        release.set()
        await cache.refresh_task
        fetch_mock.assert_awaited_once()
        assert (await cache.get()).stations[0].providers[0].series[0].value == 30
    finally:
        await cache.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_response", [False, True])
async def test_failed_refresh_retains_values_and_schedules_retry(cache_db, failed_response):
    seed(cache_db, forecast())
    fetch = AsyncMock(return_value=forecast(None)) if failed_response else AsyncMock(side_effect=RuntimeError("Provider offline"))
    cache = UpstreamForecastCacheService(cache_db, lambda: SimpleNamespace(forecasts=fetch))
    await cache.get(force_refresh=True)
    await cache.refresh_task
    result = await cache.get()
    assert result.stations[0].providers[0].series[0].value == 10
    assert result.refresh_error
    delay = datetime.fromisoformat(result.next_refresh_at) - datetime.now(timezone.utc)
    assert 0 < delay.total_seconds() <= 300
    fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_warms_empty_database_without_page_visit(cache_db):
    started = asyncio.Event()

    async def fetch():
        started.set()
        return forecast()

    cache = UpstreamForecastCacheService(cache_db, lambda: SimpleNamespace(forecasts=fetch))
    cache.start()
    try:
        await asyncio.wait_for(started.wait(), 2)
        await cache.refresh_task
        assert (await cache.get()).cached_at
    finally:
        await cache.stop()


@pytest.mark.asyncio
async def test_refresh_endpoint_returns_cache_without_waiting(cache_db, monkeypatch):
    seed(cache_db, forecast())
    release = asyncio.Event()

    async def fetch():
        await release.wait()
        return forecast(40)

    cache = UpstreamForecastCacheService(cache_db, lambda: SimpleNamespace(forecasts=fetch))
    monkeypatch.setattr("app.api.routes.river.upstream_forecast_cache", cache)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await asyncio.wait_for(client.post("/api/v1/river/upstream-forecasts/refresh"), 2)
            assert response.status_code == 200
            assert response.json()["refreshing"]
            assert response.json()["stations"][0]["providers"][0]["series"][0]["value"] == 10
            release.set()
            await cache.refresh_task
            assert (await client.get("/api/v1/river/upstream-forecasts")).json()["stations"][0]["providers"][0]["series"][0]["value"] == 40
    finally:
        await cache.stop()
