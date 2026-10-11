import asyncio
import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.core.enums import DataMode, Scenario
from app.core.exceptions import AppError
from app.gis.geometry import bounds_intersect, geometry_bounds, representative_point


DISTRICT_DATA_PATH = Path(__file__).parents[2] / "frontend" / "src" / "data" / "pakistan" / "pakistan_districts.geojson"
WEATHER_FIELDS = "precipitation,temperature_2m,relative_humidity_2m,soil_moisture_0_to_7cm"


class NationalRiskService:
    _districts: list[dict] | None = None
    _cache: dict[str, tuple[datetime, dict]] = {}
    _locks: dict[str, asyncio.Lock] = {}

    def __init__(self, client: httpx.AsyncClient | None = None):
        self.settings = get_settings()
        self.client = client

    async def feature_collection(
        self,
        data_mode: DataMode,
        scenario: Scenario,
        bbox: tuple[float, float, float, float] | None = None,
    ) -> dict:
        cache_key = f"{data_mode.value}:{scenario.value}"
        now = datetime.now(timezone.utc)
        cached = self._cache.get(cache_key)
        if cached and now - cached[0] < timedelta(seconds=self.settings.gis_cache_ttl_seconds):
            return self._filter(copy.deepcopy(cached[1]), bbox, cache_status="fresh")

        lock = self._locks.setdefault(cache_key, asyncio.Lock())
        async with lock:
            cached = self._cache.get(cache_key)
            if cached and now - cached[0] < timedelta(seconds=self.settings.gis_cache_ttl_seconds):
                return self._filter(copy.deepcopy(cached[1]), bbox, cache_status="fresh")
            try:
                collection = (
                    self._simulation_collection(scenario)
                    if data_mode == DataMode.SIMULATION
                    else await self._live_collection()
                )
            except AppError:
                if cached:
                    stale = copy.deepcopy(cached[1])
                    stale["metadata"]["warning"] = "Live national refresh failed; last successful cached layer is shown."
                    return self._filter(stale, bbox, cache_status="stale")
                raise
            self._cache[cache_key] = (now, collection)
            return self._filter(copy.deepcopy(collection), bbox, cache_status="fresh")

    @classmethod
    def clear_cache(cls) -> None:
        cls._cache.clear()
        cls._locks.clear()

    @classmethod
    def districts(cls) -> list[dict]:
        if cls._districts is None:
            with DISTRICT_DATA_PATH.open(encoding="utf-8") as source:
                raw = json.load(source)
            districts = []
            for feature in raw["features"]:
                district_name = feature["properties"].get("district")
                if not district_name:
                    continue
                feature = copy.deepcopy(feature)
                district_id = feature["properties"].get("id") or f"PAK_ADM2_{len(districts):03d}"
                longitude, latitude = representative_point(feature["geometry"])
                feature["id"] = district_id
                feature["properties"] = {
                    "district_id": district_id,
                    "district_name": district_name,
                    "admin_level": "ADM2",
                    "longitude": longitude,
                    "latitude": latitude,
                }
                feature["_bbox"] = geometry_bounds(feature["geometry"])
                districts.append(feature)
            cls._districts = districts
        return cls._districts

    async def _live_collection(self) -> dict:
        districts = self.districts()
        batch_size = self.settings.gis_weather_batch_size
        batches = [districts[index : index + batch_size] for index in range(0, len(districts), batch_size)]
        results = await asyncio.gather(*(self._weather_batch(batch) for batch in batches))
        payloads = [payload for result in results for payload in result]
        if len(payloads) != len(districts):
            raise AppError("GIS_PROVIDER_ERROR", "National weather coverage returned an incomplete response", 502)

        features = []
        timestamps = []
        for district, payload in zip(districts, payloads, strict=True):
            metrics = self._weather_metrics(payload)
            timestamps.append(metrics.pop("observed_at"))
            score = self._screening_score(metrics)
            feature = copy.deepcopy(district)
            feature["properties"].update(self._risk_properties(score, "live", "NORMAL", metrics))
            features.append(feature)
        generated_at = datetime.now(timezone.utc)
        return self._collection(features, generated_at, min(timestamps), "live", "NORMAL")

    async def _weather_batch(self, districts: list[dict]) -> list[dict]:
        params = {
            "latitude": ",".join(str(feature["properties"]["latitude"]) for feature in districts),
            "longitude": ",".join(str(feature["properties"]["longitude"]) for feature in districts),
            "hourly": WEATHER_FIELDS,
            "past_hours": 24,
            "forecast_hours": 25,
            "timezone": "UTC",
        }
        try:
            if self.client is not None:
                response = await self.client.get(self.settings.weather_api_base_url, params=params)
            else:
                async with httpx.AsyncClient(timeout=self.settings.weather_api_timeout_seconds) as client:
                    response = await client.get(self.settings.weather_api_base_url, params=params)
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, list) else [payload]
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            raise AppError(
                "GIS_PROVIDER_ERROR",
                "Live national weather screening data is temporarily unavailable",
                502,
            ) from exc

    @staticmethod
    def _weather_metrics(payload: dict) -> dict:
        try:
            hourly = payload["hourly"]
            times = [datetime.fromisoformat(value).replace(tzinfo=timezone.utc) for value in hourly["time"]]
            current_index = max(
                (index for index, value in enumerate(times) if value <= datetime.now(timezone.utc)),
                default=0,
            )
            precipitation = [float(value or 0) for value in hourly["precipitation"]]

            def past_sum(hours: int) -> float:
                start = max(0, current_index - hours + 1)
                return round(sum(precipitation[start : current_index + 1]), 2)

            def forecast_sum(hours: int) -> float:
                return round(sum(precipitation[current_index + 1 : current_index + 1 + hours]), 2)

            soil = float(hourly["soil_moisture_0_to_7cm"][current_index] or 0) * 100
            return {
                "observed_at": times[current_index],
                "rainfall_6h_mm": past_sum(6),
                "rainfall_24h_mm": past_sum(24),
                "forecast_rainfall_24h_mm": forecast_sum(24),
                "temperature_c": round(float(hourly["temperature_2m"][current_index]), 1),
                "humidity_percent": round(float(hourly["relative_humidity_2m"][current_index]), 1),
                "soil_moisture_percent": round(min(max(soil, 0), 100), 1),
            }
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise AppError("GIS_PROVIDER_ERROR", "National weather data is invalid", 502) from exc

    @staticmethod
    def _screening_score(metrics: dict) -> float:
        score = (
            0.34 * min(metrics["rainfall_24h_mm"] / 120, 1)
            + 0.38 * min(metrics["forecast_rainfall_24h_mm"] / 100, 1)
            + 0.18 * min(metrics["soil_moisture_percent"] / 90, 1)
            + 0.10 * min(metrics["rainfall_6h_mm"] / 50, 1)
        )
        return round(min(max(score, 0.01), 0.98), 4)

    def _simulation_collection(self, scenario: Scenario) -> dict:
        base_scores = {
            Scenario.NORMAL: 0.12,
            Scenario.HEAVY_RAIN: 0.46,
            Scenario.DEVELOPING_FLOOD: 0.66,
            Scenario.CRITICAL_FLOOD: 0.86,
            Scenario.CONFIRMED_FLOOD: 0.94,
            Scenario.FALSE_ALARM: 0.08,
        }
        features = []
        for district in self.districts():
            digest = hashlib.sha256(district["id"].encode()).digest()[0]
            variation = (digest / 255 - 0.5) * 0.12
            score = round(min(max(base_scores[scenario] + variation, 0.01), 0.99), 4)
            feature = copy.deepcopy(district)
            feature["properties"].update(self._risk_properties(score, "simulation", scenario.value, {}))
            features.append(feature)
        now = datetime.now(timezone.utc)
        return self._collection(features, now, now, "simulation", scenario.value)

    @staticmethod
    def _risk_properties(score: float, source: str, scenario: str, metrics: dict) -> dict:
        if score >= 0.78:
            severity, status = "CRITICAL", "WARNING"
        elif score >= 0.58:
            severity, status = "HIGH", "WATCH"
        elif score >= 0.38:
            severity, status = "MEDIUM", "ADVISORY"
        else:
            severity, status = "LOW", "NORMAL"
        factors = sorted(
            [
                ("Forecast rainfall", metrics.get("forecast_rainfall_24h_mm", 0) / 100),
                ("Recent rainfall", metrics.get("rainfall_24h_mm", 0) / 120),
                ("Soil moisture", metrics.get("soil_moisture_percent", 0) / 90),
            ],
            key=lambda item: item[1],
            reverse=True,
        )
        return {
            "risk_probability": score,
            "severity": severity,
            "status": status,
            "confidence": 0.62 if source == "live" else 1.0,
            "risk_basis": "district_weather_screening",
            "model": "district_weather_screening_v1",
            "model_type": "screening_index",
            "source": source,
            "scenario": scenario,
            "top_risk_factors": [name for name, value in factors if value >= 0.2][:3],
            **metrics,
        }

    @staticmethod
    def _collection(features: list[dict], generated_at: datetime, observed_at: datetime, source: str, scenario: str) -> dict:
        return {
            "type": "FeatureCollection",
            "metadata": {
                "coverage": "Pakistan ADM2 districts",
                "feature_count": len(features),
                "generated_at": generated_at.isoformat(),
                "observed_at": observed_at.isoformat(),
                "data_mode": source,
                "scenario": scenario,
                "risk_basis": "district_weather_screening",
                "methodology": "Batched weather screening; detailed river-aware predictions remain station based.",
                "boundary_source": "Parallax Geo Pakistan Official Boundary Shapefile; WGS84/EPSG:4326",
            },
            "features": features,
        }

    @staticmethod
    def _filter(collection: dict, bbox: tuple[float, float, float, float] | None, cache_status: str) -> dict:
        if bbox:
            collection["features"] = [
                feature for feature in collection["features"] if bounds_intersect(feature["_bbox"], bbox)
            ]
        for feature in collection["features"]:
            feature.pop("_bbox", None)
        collection["metadata"]["cache_status"] = cache_status
        collection["metadata"]["returned_feature_count"] = len(collection["features"])
        return collection

