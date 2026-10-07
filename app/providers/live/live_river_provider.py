import re
import time
from datetime import date, datetime, timedelta, timezone
from math import asin, cos, radians, sin, sqrt

import httpx

from app.core.config import get_settings
from app.core.enums import RiverStatus, Scenario
from app.core.exceptions import AppError
from app.locations import get_location
from app.providers.base.river_provider import RiverProvider
from app.schemas.river import RiverResponse


class LiveRiverProvider(RiverProvider):
    """Official FFD observed river data with GloFAS modeled fallback/forecast context."""

    DAILY_FIELDS = (
        "river_discharge,river_discharge_mean,river_discharge_median,"
        "river_discharge_max,river_discharge_min,river_discharge_p25,river_discharge_p75"
    )
    FFD_PAGE_URL = "https://ffd.pmd.gov.pk/river-state?zoom=6"
    FFD_DATA_URL = "https://ffd.pmd.gov.pk/river-state/data"
    FFD_HEADERS = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
        "Referer": FFD_PAGE_URL,
        "X-Requested-With": "XMLHttpRequest",
    }
    CUSEC_TO_CUMECS = 0.028316846592
    PKT = timezone(timedelta(hours=5))
    OFFICIAL_STATION_BY_LOCATION = {
        "JHG_001": "Trimmu",
        "MUL_001": "Panjnad",
    }
    FFD_CACHE_TTL_SECONDS = 120
    _ffd_cache: list[dict] | None = None
    _ffd_cache_timestamp = 0.0

    def __init__(self, client: httpx.AsyncClient | None = None):
        settings = get_settings()
        self.base_url = settings.flood_api_base_url
        self.timeout = settings.flood_api_timeout_seconds
        self.client = client

    async def get_current(self, location_id: str, scenario: Scenario) -> RiverResponse:
        try:
            station = await self._get_ffd_station(location_id)
            return self._from_official_station(location_id, scenario, station)
        except (httpx.HTTPError, KeyError, TypeError, ValueError, IndexError):
            return await self._get_glofas_current(location_id, scenario)

    async def _get_glofas_current(self, location_id: str, scenario: Scenario) -> RiverResponse:
        location = get_location(location_id)
        params = {
            "latitude": location.river_latitude or location.latitude,
            "longitude": location.river_longitude or location.longitude,
            "daily": self.DAILY_FIELDS,
            "past_days": 7,
            "forecast_days": 7,
            "cell_selection": "nearest",
        }
        try:
            if self.client is not None:
                response = await self.client.get(self.base_url, params=params)
            else:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.get(self.base_url, params=params)
            response.raise_for_status()
            return self._normalize(location_id, scenario, response.json())
        except (httpx.HTTPError, KeyError, TypeError, ValueError, IndexError) as exc:
            raise AppError(
                "RIVER_PROVIDER_ERROR",
                "Live modeled river discharge is temporarily unavailable or invalid",
                502,
            ) from exc

    async def _get_ffd_station(self, location_id: str) -> dict:
        stations = await self._get_ffd_stations()
        if not stations:
            raise ValueError("FFD station feed is empty")
        preferred_station = self.OFFICIAL_STATION_BY_LOCATION.get(location_id)
        if preferred_station:
            for station in stations:
                if str(station.get("name", "")).strip().lower() == preferred_station.lower():
                    return station
        return self._nearest_station(location_id, stations)

    async def _get_ffd_stations(self) -> list[dict]:
        now = time.monotonic()
        cache = type(self)._ffd_cache
        if cache is not None and now - type(self)._ffd_cache_timestamp <= self.FFD_CACHE_TTL_SECONDS:
            return cache
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
            page = await client.get(self.FFD_PAGE_URL)
            page.raise_for_status()
            token = self._extract_ffd_token(page.text)
            headers = {**self.FFD_HEADERS, "X-FW-Token": token}
            response = await client.get(self.FFD_DATA_URL, headers=headers)
            response.raise_for_status()
            stations = response.json().get("stations", [])
        if not isinstance(stations, list):
            raise ValueError("FFD station feed has invalid format")
        type(self)._ffd_cache = stations
        type(self)._ffd_cache_timestamp = now
        return stations

    def _normalize(self, location_id: str, scenario: Scenario, payload: dict) -> RiverResponse:
        location = get_location(location_id)
        daily = payload["daily"]
        dates = [date.fromisoformat(value) for value in daily["time"]]

        def series(name: str) -> list[float | None]:
            return [float(value) if value is not None else None for value in daily.get(name, [])]

        values = series("river_discharge")
        mean_values = series("river_discharge_mean")
        median_values = series("river_discharge_median")
        min_values = series("river_discharge_min")
        max_values = series("river_discharge_max")
        p25_values = series("river_discharge_p25")
        p75_values = series("river_discharge_p75")
        today = datetime.now(timezone.utc).date()
        current_index = max((index for index, value in enumerate(dates) if value <= today), default=0)
        current = values[current_index]
        if current is None:
            raise ValueError("Current river discharge is missing")
        previous = values[current_index - 1] if current_index > 0 else None
        change = round(current - previous, 2) if previous is not None else 0.0
        forecast = values[current_index + 1] if current_index + 1 < len(values) else None
        rising_threshold = max(current * 0.1, 5.0)
        status = RiverStatus.RISING if change >= rising_threshold else RiverStatus.NORMAL
        return RiverResponse(
            location_id=location.id,
            location_name=location.name,
            timestamp=datetime.combine(dates[current_index], datetime.min.time(), tzinfo=timezone.utc),
            source="live",
            scenario=scenario.value,
            river_name=location.river_name or "Nearest modeled river",
            station_name=f"{location.river_station_name or location.name} / Open-Meteo GloFAS 5 km grid",
            river_level_m=None,
            observed_level_value=None,
            observed_level_unit=None,
            official_recording_time=None,
            data_note="GloFAS provides modeled discharge, not observed gauge height.",
            normal_level_m=None,
            warning_level_m=None,
            danger_level_m=None,
            rate_of_rise_m_per_hour=None,
            discharge_cumecs=round(current, 2),
            discharge_change_cumecs_per_day=change,
            forecast_discharge_next_24h_cumecs=round(forecast, 2) if forecast is not None else None,
            discharge_mean_cumecs=self._value_at(mean_values, current_index),
            discharge_median_cumecs=self._value_at(median_values, current_index),
            discharge_min_cumecs=self._value_at(min_values, current_index),
            discharge_max_cumecs=self._value_at(max_values, current_index),
            discharge_p25_cumecs=self._value_at(p25_values, current_index),
            discharge_p75_cumecs=self._value_at(p75_values, current_index),
            status=status.value,
        )

    def _from_official_station(self, location_id: str, scenario: Scenario, station: dict) -> RiverResponse:
        location = get_location(location_id)
        official_discharge_cumecs = self._parse_cusecs_to_cumecs(station.get("discharge"))
        forecast_cumecs = self._parse_ffd_forecast_quant(station.get("forecast_quant"))
        level_value = self._parse_number(station.get("level"))
        level_unit = "ft" if level_value is not None else None
        river_level_m = round(level_value * 0.3048, 3) if level_value is not None else None
        recording_time = str(station.get("recording_time") or "").strip() or None
        return RiverResponse(
            location_id=location.id,
            location_name=location.name,
            timestamp=self._parse_ffd_recording_time(recording_time) or datetime.now(timezone.utc),
            source="FFD Lahore observed",
            scenario=scenario.value,
            river_name=self._official_river_name(station) or location.river_name or "Official FFD station",
            station_name=f"{station.get('name', location.river_station_name or location.name)} / FFD Lahore",
            river_level_m=river_level_m,
            observed_level_value=level_value,
            observed_level_unit=level_unit,
            official_recording_time=recording_time,
            data_note=(
                "FFD publishes observed discharge/status for this station. "
                "Observed level is shown only where FFD publishes a level value."
            ),
            normal_level_m=None,
            warning_level_m=None,
            danger_level_m=None,
            rate_of_rise_m_per_hour=None,
            discharge_cumecs=official_discharge_cumecs,
            discharge_change_cumecs_per_day=None,
            forecast_discharge_next_24h_cumecs=forecast_cumecs,
            discharge_mean_cumecs=None,
            discharge_median_cumecs=None,
            discharge_min_cumecs=None,
            discharge_max_cumecs=None,
            discharge_p25_cumecs=None,
            discharge_p75_cumecs=None,
            status=self._map_ffd_status(station),
        )

    @staticmethod
    def _value_at(values: list[float | None], index: int) -> float | None:
        if index >= len(values) or values[index] is None:
            return None
        return round(values[index], 2)

    @staticmethod
    def _extract_ffd_token(html: str) -> str:
        match = re.search(r'RS_TOKEN\s*=\s*"([^"]+)"', html)
        if not match:
            raise ValueError("FFD token not found")
        return match.group(1)

    @staticmethod
    def _parse_number(value: object) -> float | None:
        if value is None:
            return None
        text = str(value).replace(",", "").strip()
        if not text:
            return None
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        return float(match.group(0)) if match else None

    def _parse_cusecs_to_cumecs(self, value: object) -> float | None:
        cusecs = self._parse_number(value)
        return round(cusecs * self.CUSEC_TO_CUMECS, 2) if cusecs is not None else None

    def _parse_ffd_forecast_quant(self, value: object) -> float | None:
        if value is None:
            return None
        parts = [float(part) for part in re.findall(r"\d+(?:\.\d+)?", str(value).replace(",", ""))]
        if not parts:
            return None
        thousands_of_cusecs = sum(parts) / len(parts)
        return round(thousands_of_cusecs * 1000 * self.CUSEC_TO_CUMECS, 2)

    @staticmethod
    def _official_river_name(station: dict) -> str | None:
        area_name = str(station.get("area_name") or "").strip()
        if not area_name or area_name.upper() == "N/A":
            return None
        return area_name.replace(" River", "")

    @staticmethod
    def _map_ffd_status(station: dict) -> str:
        status = str(station.get("status") or "NORMAL").upper()
        if status in {"VERY_HIGH", "EX_HIGH", "HIGH", "MEDIUM"}:
            return RiverStatus.DANGER.value
        if status == "LOW":
            return RiverStatus.WARNING.value
        gauges = station.get("gauges") or []
        if any(str(gauge.get("trend_icon") or "").lower() == "up" for gauge in gauges):
            return RiverStatus.RISING.value
        return RiverStatus.NORMAL.value

    def _parse_ffd_recording_time(self, value: str | None) -> datetime | None:
        if not value:
            return None
        match = re.search(r"(\d{1,2})-([A-Za-z]{3})\s+(\d{1,2})", value)
        if not match:
            return None
        day, month_text, hour = match.groups()
        month = datetime.strptime(month_text.title(), "%b").month
        now = datetime.now(self.PKT)
        return datetime(now.year, month, int(day), int(hour), tzinfo=self.PKT).astimezone(timezone.utc)

    def _nearest_station(self, location_id: str, stations: list[dict]) -> dict:
        location = get_location(location_id)
        latitude = location.river_latitude or location.latitude
        longitude = location.river_longitude or location.longitude
        candidates = [
            station
            for station in stations
            if station.get("latitude") is not None and station.get("longitude") is not None
        ]
        if not candidates:
            raise ValueError("FFD stations have no coordinates")
        return min(
            candidates,
            key=lambda station: self._distance_km(latitude, longitude, float(station["latitude"]), float(station["longitude"])),
        )

    @staticmethod
    def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        radius_km = 6371.0
        d_lat = radians(lat2 - lat1)
        d_lon = radians(lon2 - lon1)
        a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
        return 2 * radius_km * asin(sqrt(a))
