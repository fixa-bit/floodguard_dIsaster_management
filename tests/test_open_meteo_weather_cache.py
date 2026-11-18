import asyncio
import json
import os
import time

import httpx
import pytest

from app.core.config import get_settings
from app.providers import open_meteo_weather_cache as cache

URL = "https://api.open-meteo.com/v1/forecast"
PARAMS = {"latitude": 31.5, "longitude": 74.3, "hourly": "precipitation"}
LIMIT_BODY = {"error": True, "reason": "Daily API request limit exceeded. Please try again tomorrow."}


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("WEATHER_CACHE_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def client_returning(responses, calls):
    def handler(request):
        calls.append(request)
        status, body = responses[min(len(calls) - 1, len(responses) - 1)]
        return httpx.Response(status, json=body)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def fetch(client, **kwargs):
    return asyncio.run(cache.get_weather_json(client, URL, dict(PARAMS), **kwargs))


def test_fresh_response_is_reused_across_restarts(cache_dir):
    calls = []
    client = client_returning([(200, {"hourly": {"precipitation": [1]}})], calls)
    assert fetch(client) == {"hourly": {"precipitation": [1]}}
    cache.reset_state()  # simulates a backend restart: only the disk entry survives
    assert fetch(client) == {"hourly": {"precipitation": [1]}}
    assert len(calls) == 1


def test_daily_limit_serves_stale_data_and_pauses_requests(cache_dir):
    calls = []
    client = client_returning([(200, {"v": 1}), (429, LIMIT_BODY)], calls)
    fetch(client)
    assert fetch(client, ttl_seconds=0) == {"v": 1}  # limit hit -> stored copy
    assert fetch(client, ttl_seconds=0) == {"v": 1}  # paused -> no further request
    assert len(calls) == 2
    assert cache._blocked_until > time.time() + 60


def test_limit_without_stored_data_raises(cache_dir):
    client = client_returning([(429, LIMIT_BODY)], [])
    with pytest.raises(httpx.HTTPError):
        fetch(client)
    with pytest.raises(httpx.HTTPError, match="paused"):
        fetch(client)


def test_stale_entries_older_than_limit_are_not_served(cache_dir, monkeypatch):
    calls = []
    client = client_returning([(200, {"v": 1}), (500, {})], calls)
    fetch(client)
    entry = next(cache_dir.glob("*.json"))
    stored = json.loads(entry.read_text())
    stored["fetched_at"] -= 48 * 3600
    entry.write_text(json.dumps(stored))
    with pytest.raises(httpx.HTTPError):
        fetch(client)


def test_disabled_cache_always_calls_api():
    assert os.environ["WEATHER_CACHE_DIR"] == ""
    calls = []
    client = client_returning([(200, {"v": 1})], calls)
    fetch(client)
    fetch(client)
    assert len(calls) == 2


FALLBACK = "https://historical-forecast-api.open-meteo.com/v1/forecast"


@pytest.fixture
def with_fallback(cache_dir, monkeypatch):
    monkeypatch.setenv("WEATHER_API_FALLBACK_BASE_URL", FALLBACK)
    get_settings.cache_clear()
    yield cache_dir
    get_settings.cache_clear()


def routed_client(primary, fallback, calls):
    def handler(request):
        host = request.url.host
        calls.append(host)
        status, body = primary if host == "api.open-meteo.com" else fallback
        return httpx.Response(status, json=body)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_limit_without_stored_data_uses_fallback_host(with_fallback):
    calls = []
    client = routed_client((429, LIMIT_BODY), (200, {"v": "fallback"}), calls)
    assert fetch(client) == {"v": "fallback"}
    assert calls == ["api.open-meteo.com", "historical-forecast-api.open-meteo.com"]
    # The fallback answer is stored like any other, so it is reused within the TTL.
    assert fetch(client) == {"v": "fallback"}
    assert len(calls) == 2
    # While the main API is paused, misses go straight to the fallback host.
    assert fetch(client, ttl_seconds=0) == {"v": "fallback"}
    assert calls[-1] == "historical-forecast-api.open-meteo.com" and len(calls) == 3


def test_fallback_failure_serves_stored_then_raises(with_fallback):
    calls = []
    client = routed_client((500, {}), (500, {}), calls)
    with pytest.raises(httpx.HTTPError):
        fetch(client)
    ok = routed_client((200, {"v": 1}), (500, {}), calls)
    fetch(ok)
    assert fetch(client, ttl_seconds=0) == {"v": 1}


def test_fallback_only_mirrors_the_weather_api(with_fallback):
    calls = []
    client = routed_client((500, {}), (200, {"v": "fallback"}), calls)
    with pytest.raises(httpx.HTTPError):
        asyncio.run(cache.get_weather_json(client, "https://api.open-meteo.com/v1/other", dict(PARAMS)))
    assert calls == ["api.open-meteo.com"]
