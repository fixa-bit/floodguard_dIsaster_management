"""Disk cache in front of the Open-Meteo weather forecast API.

The free API allows about 10,000 location-calls a day. The national risk map
(145 districts), rainfall heatmap (177 samples) and dashboard weather together
can exceed that. The old caches were held only in memory, so every backend
restart (uvicorn --reload) fetched everything again.

This module:
- reuses a stored response while it is younger than the TTL, across restarts;
- stops calling the API until the limit resets once Open-Meteo reports one;
- when the main API fails or is paused, asks the fallback host
  (``weather_api_fallback_base_url``, Open-Meteo's historical-forecast API,
  which has its own limit and accepts the same parameters);
- returns the last stored response, up to ``weather_cache_max_stale_hours`` old,
  when both fail.
"""
import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[2]

_blocked_until: float = 0.0
_blocked_reason: str = ""
_fallback_blocked_until: float = 0.0
_locks: dict[str, asyncio.Lock] = {}


def reset_state() -> None:
    global _blocked_until, _blocked_reason, _fallback_blocked_until
    _blocked_until = 0.0
    _blocked_reason = ""
    _fallback_blocked_until = 0.0
    _locks.clear()


async def _from_fallback(client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> Any | None:
    """Same request against the fallback host; None when there is none or it fails."""
    global _fallback_blocked_until
    settings = get_settings()
    fallback = settings.weather_api_fallback_base_url.strip()
    if not fallback or url != settings.weather_api_base_url or time.time() < _fallback_blocked_until:
        return None
    try:
        response = await client.get(fallback, params=params)
        block = _limit_block_seconds(response)
        if block is not None:
            _fallback_blocked_until = time.time() + block
            logger.warning("Open-Meteo fallback limit reached; pausing it for %.0f minutes", block / 60)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        logger.info("Open-Meteo fallback request failed", exc_info=True)
        return None
    if isinstance(payload, dict) and payload.get("error"):
        return None
    return payload


def _cache_dir() -> Path | None:
    configured = get_settings().weather_cache_dir.strip()
    if not configured:
        return None
    path = Path(configured)
    return path if path.is_absolute() else REPO_ROOT / path


def _key(url: str, params: dict[str, Any]) -> str:
    canonical = json.dumps([url, sorted((str(k), str(v)) for k, v in params.items())])
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


def _read(path: Path | None) -> tuple[float, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
        return float(stored["fetched_at"]), stored["payload"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write(path: Path | None, payload: Any) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"fetched_at": time.time(), "payload": payload}), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        logger.warning("Could not store Open-Meteo weather cache entry %s", path, exc_info=True)


def _limit_block_seconds(response: httpx.Response) -> float | None:
    """How long to stop calling the API after a rate-limit response, or None if it is not one."""
    if response.status_code != 429:
        return None
    try:
        reason = str(response.json().get("reason", "")).lower()
    except ValueError:
        reason = ""
    if "minutely" in reason:
        return 60
    if "hourly" in reason:
        return 3600 - time.time() % 3600
    # Daily (and unknown) limits: wait for the next UTC day.
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
    return (tomorrow - now).total_seconds()


async def get_weather_json(client: httpx.AsyncClient, url: str, params: dict[str, Any],
                           ttl_seconds: float | None = None) -> Any:
    """Return the decoded Open-Meteo JSON for ``url`` + ``params``; raises httpx.HTTPError when nothing usable exists."""
    global _blocked_until, _blocked_reason
    settings = get_settings()
    ttl = settings.weather_cache_ttl_seconds if ttl_seconds is None else ttl_seconds
    max_stale = settings.weather_cache_max_stale_hours * 3600
    directory = _cache_dir()
    key = _key(url, params)
    path = directory / f"{key}.json" if directory else None

    def stored(max_age: float):
        entry = _read(path)
        return entry[1] if entry and time.time() - entry[0] < max_age else None

    if (fresh := stored(ttl)) is not None:
        return fresh
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        if (fresh := stored(ttl)) is not None:
            return fresh
        if time.time() < _blocked_until:
            if (payload := await _from_fallback(client, url, params)) is not None:
                _write(path, payload)
                return payload
            if (stale := stored(max_stale)) is not None:
                return stale
            raise httpx.HTTPError(f"Open-Meteo weather requests paused: {_blocked_reason}")
        try:
            response = await client.get(url, params=params)
            block = _limit_block_seconds(response)
            if block is not None:
                _blocked_until = time.time() + block
                _blocked_reason = response.text[:160]
                logger.warning("Open-Meteo weather limit reached; pausing requests for %.0f minutes: %s", block / 60, _blocked_reason)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            if (fallback := await _from_fallback(client, url, params)) is not None:
                logger.info("Open-Meteo weather request failed; served from the fallback host %s", key)
                _write(path, fallback)
                return fallback
            if (stale := stored(max_stale)) is not None:
                logger.info("Open-Meteo weather request failed; serving stored response %s", key)
                return stale
            raise
        _write(path, payload)
        return payload
