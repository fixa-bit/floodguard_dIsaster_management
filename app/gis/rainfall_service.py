import asyncio
import copy
import json
import math
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.gis.geometry import point_in_geometry


@lru_cache(maxsize=1)
def rainfall_coverage() -> dict:
    return json.loads((Path(__file__).parent / "data/rainfall_coverage.geojson").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def rainfall_sample_points() -> tuple[tuple[float, float], ...]:
    coverage = rainfall_coverage()
    west, south, east, north = coverage["bbox"]
    geometry = coverage["features"][0]["geometry"]
    points = {(float(lon), float(lat)) for lon in range(math.floor(west), math.ceil(east) + 1)
              for lat in range(math.floor(south), math.ceil(north) + 1)
              if point_in_geometry(lon, lat, geometry)}
    # Include key upstream valleys between grid points, without extrapolating city data abroad.
    valleys = {(74.8, 34.08), (77.58, 34.15), (69.17, 34.55), (77.19, 32.24),
               (78.72, 31.8), (79.7, 32.5)}
    points.update(point for point in valleys if point_in_geometry(*point, geometry))
    return tuple(sorted(points))


class RainfallService:
    _cache: tuple[datetime, dict] | None = None
    _lock: asyncio.Lock | None = None

    def __init__(self, client: httpx.AsyncClient | None = None):
        self.settings = get_settings()
        self.client = client

    @classmethod
    def clear_cache(cls):
        cls._cache = None
        cls._lock = None

    async def feature_collection(self) -> dict:
        cls = type(self)
        now = datetime.now(timezone.utc)
        if cls._cache and now - cls._cache[0] < timedelta(seconds=self.settings.gis_cache_ttl_seconds):
            return copy.deepcopy(cls._cache[1])
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        async with cls._lock:
            if cls._cache and now - cls._cache[0] < timedelta(seconds=self.settings.gis_cache_ttl_seconds):
                return copy.deepcopy(cls._cache[1])
            try:
                collection = await self._live_collection(now)
            except AppError:
                if not cls._cache:
                    raise
                stale = copy.deepcopy(cls._cache[1])
                stale["metadata"].update(cache_status="stale", warning="Regional rainfall refresh failed; cached rainfall shown.")
                return stale
            cls._cache = (datetime.now(timezone.utc), collection)
            return copy.deepcopy(collection)

    async def _live_collection(self, now: datetime) -> dict:
        points = rainfall_sample_points()
        semaphore = asyncio.Semaphore(4)
        async with httpx.AsyncClient(timeout=self.settings.weather_api_timeout_seconds) as own_client:
            client = self.client or own_client

            async def batch(samples):
                async with semaphore:
                    try:
                        response = await client.get(self.settings.weather_api_base_url, params={
                            "longitude": ",".join(str(point[0]) for point in samples),
                            "latitude": ",".join(str(point[1]) for point in samples),
                            "hourly": "precipitation", "past_hours": 24, "forecast_hours": 73,
                            "timezone": "UTC",
                        })
                        response.raise_for_status()
                        data = response.json()
                        payloads = data if isinstance(data, list) else [data]
                        if len(payloads) != len(samples):
                            return []
                        features = []
                        for point, payload in zip(samples, payloads, strict=True):
                            values = self.accumulations(payload, now)
                            if not any(value is not None for value in values.values()):
                                continue
                            features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": list(point)},
                                             "properties": {"accumulations_mm": values}})
                        return features
                    except (httpx.HTTPError, KeyError, TypeError, ValueError):
                        return []

            results = await asyncio.gather(*(batch(points[index:index + 40]) for index in range(0, len(points), 40)))
        features = [feature for result in results for feature in result]
        if not features:
            raise AppError("RAINFALL_PROVIDER_ERROR", "Regional rainfall provider is unavailable", 502)
        missing = len(points) - len(features)
        return {"type": "FeatureCollection", "features": features, "coverage": rainfall_coverage(),
                "metadata": {"source": "Open-Meteo model precipitation", "generated_at": now.isoformat(),
                             "sample_spacing_degrees": 1, "cache_status": "fresh", "missing_samples": missing,
                             "warning": f"{missing} regional rainfall samples unavailable." if missing else None}}

    @staticmethod
    def accumulations(payload: dict, now: datetime) -> dict:
        hourly = payload["hourly"]
        times = [datetime.fromisoformat(value).replace(tzinfo=timezone.utc) for value in hourly["time"]]
        values = hourly["precipitation"]
        by_time = dict(zip(times, values, strict=True))
        end = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)

        def total(hours: int, future: bool):
            timestamps = [end + timedelta(hours=offset) for offset in (range(1, hours + 1) if future else range(1 - hours, 1))]
            samples = [by_time.get(timestamp) for timestamp in timestamps]
            if any(not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 for value in samples):
                return None
            return round(sum(samples), 2)

        return {**{f"last_{hours}h": total(hours, False) for hours in (1, 3, 6, 24)},
                **{f"next_{hours}h": total(hours, True) for hours in (24, 72)}}
