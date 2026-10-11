import asyncio
import math
from datetime import datetime, timezone
from time import monotonic

import httpx

from app.core.config import get_settings


SEVERITIES = {
    "EXTREME": "Extreme",
    "SEVERE": "Danger",
    "ABOVE_NORMAL": "Warning",
    "NO_FLOODING": "Normal",
    "UNKNOWN": "No data",
}


class GoogleFloodService:
    """Fetch verified Google river forecasts; never substitute simulated statuses."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._cached = None
        self._expires = 0.0
        self._cache_identity = None

    @staticmethod
    def collection(features, status, message=None, fetched_at=None):
        return {
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "status": status,
                "message": message,
                "fetched_at": fetched_at,
                "source": "Google Flood Forecasting API",
                "license": "CC BY 4.0",
                "source_url": "https://developers.google.com/flood-forecasting",
            },
        }

    @staticmethod
    async def search(client, method, field, region):
        items = []
        token = None
        seen_tokens = set()
        while True:
            body = {"regionCode": region, "pageSize": 1000}
            if token:
                body["pageToken"] = token
            response = await client.post(f"./{method}", json=body)
            response.raise_for_status()
            payload = response.json()
            items.extend(payload.get(field, []))
            token = payload.get("nextPageToken")
            if not token:
                return items
            if token in seen_tokens:
                raise ValueError("Repeated Google pagination token")
            seen_tokens.add(token)

    @staticmethod
    def features(gauges, statuses):
        gauges_by_id = {item["gaugeId"]: item for item in gauges}
        statuses_by_id = {item["gaugeId"]: item for item in statuses}
        features = []
        for gauge_id in gauges_by_id.keys() | statuses_by_id.keys():
            gauge = gauges_by_id.get(gauge_id, {})
            status = statuses_by_id.get(gauge_id, {})
            location = status.get("gaugeLocation") or gauge.get("location") or {}
            lat, lon = location.get("latitude"), location.get("longitude")
            if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
                continue
            if not math.isfinite(lat) or not math.isfinite(lon) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            severity = status.get("severity", "UNKNOWN")
            if severity not in SEVERITIES:
                severity = "UNKNOWN"
            window = status.get("forecastTimeRange") or {}
            features.append({
                "type": "Feature",
                "id": gauge_id,
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "id": gauge_id,
                    "name": gauge.get("siteName") or gauge_id,
                    "river": gauge.get("river") or "River unspecified",
                    "country_code": gauge.get("countryCode", ""),
                    "severity": severity,
                    "severity_label": SEVERITIES[severity],
                    "issued_at": status.get("issuedTime"),
                    "forecast_start": window.get("start"),
                    "forecast_end": window.get("end"),
                    "trend": status.get("forecastTrend", "FORECAST_TREND_UNSPECIFIED"),
                    "source": status.get("source") or gauge.get("source") or "Google",
                    "quality_verified": status.get("qualityVerified", gauge.get("qualityVerified", False)),
                    "source_url": "https://sites.research.google/floods/",
                },
            })
        return sorted(features, key=lambda feature: feature["properties"]["id"])

    async def feature_collection(self):
        settings = get_settings()
        key = settings.google_flood_api_key.get_secret_value().strip()
        if not key:
            return self.collection([], "not_configured", "Google Flood Hub is not connected. API access is required.")
        regions = tuple(dict.fromkeys(code.strip().upper() for code in settings.google_flood_region_codes.split(",") if code.strip()))
        identity = (key, regions)
        async with self._lock:
            if self._cache_identity != identity:
                self._cached = None
                self._expires = 0.0
                self._cache_identity = identity
            if self._cached is not None and monotonic() < self._expires:
                return self._cached
            try:
                if not regions:
                    raise ValueError("No Google regions configured")
                gauges, statuses = [], []
                async with httpx.AsyncClient(
                    base_url="https://floodforecasting.googleapis.com/v1/",
                    headers={"X-Goog-Api-Key": key},
                    timeout=15.0,
                ) as client:
                    for region in regions:
                        gauges.extend(await self.search(client, "gauges:searchGaugesByArea", "gauges", region))
                        statuses.extend(await self.search(client, "floodStatus:searchLatestFloodStatusByArea", "floodStatuses", region))
                features = self.features(gauges, statuses)
                result = self.collection(features, "live", None if features else "No Google gauges are available in the configured area.", datetime.now(timezone.utc).isoformat())
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                # Do not expose upstream responses, URLs, or credentials to the browser.
                if self._cached and self._cached["metadata"]["fetched_at"]:
                    result = self.collection(self._cached["features"], "stale", "Google forecasts could not be refreshed. Showing the last retrieved data.", self._cached["metadata"]["fetched_at"])
                else:
                    result = self.collection([], "unavailable", "Google forecasts are unavailable. Check API access and try again.")
            self._cached = result
            self._expires = monotonic() + (settings.google_flood_cache_seconds if result["metadata"]["status"] == "live" else 60)
            return result


google_flood_service = GoogleFloodService()
