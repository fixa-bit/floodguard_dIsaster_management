from datetime import date, datetime, timezone

import httpx

from app.core.config import get_settings
from app.core.enums import RiverStatus, Scenario
from app.core.exceptions import AppError
from app.locations import get_location
from app.providers.base.river_provider import RiverProvider
from app.schemas.river import RiverResponse


class LiveRiverProvider(RiverProvider):
    """GloFAS modeled river discharge from Open-Meteo's public Flood API."""

    def __init__(self, client: httpx.AsyncClient | None = None):
        settings = get_settings()
        self.base_url = settings.flood_api_base_url
        self.timeout = settings.flood_api_timeout_seconds
        self.client = client

    async def get_current(self, location_id: str, scenario: Scenario) -> RiverResponse:
        location = get_location(location_id)
        params = {
            "latitude": location.river_latitude or location.latitude,
            "longitude": location.river_longitude or location.longitude,
            "daily": "river_discharge",
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

    def _normalize(self, location_id: str, scenario: Scenario, payload: dict) -> RiverResponse:
        location = get_location(location_id)
        daily = payload["daily"]
        dates = [date.fromisoformat(value) for value in daily["time"]]
        values = [float(value) if value is not None else None for value in daily["river_discharge"]]
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
            normal_level_m=None,
            warning_level_m=None,
            danger_level_m=None,
            rate_of_rise_m_per_hour=None,
            discharge_cumecs=round(current, 2),
            discharge_change_cumecs_per_day=change,
            forecast_discharge_next_24h_cumecs=round(forecast, 2) if forecast is not None else None,
            status=status.value,
        )
