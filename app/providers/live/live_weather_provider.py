from datetime import datetime, timezone

import httpx

from app.core.config import get_settings
from app.core.enums import Scenario
from app.core.exceptions import AppError
from app.locations import get_location
from app.providers.base.weather_provider import WeatherProvider
from app.schemas.weather import WeatherResponse


HOURLY_FIELDS = (
    "precipitation,temperature_2m,relative_humidity_2m,"
    "soil_moisture_0_to_7cm"
)


class LiveWeatherProvider(WeatherProvider):
    def __init__(self, client: httpx.AsyncClient | None = None):
        settings = get_settings()
        self.base_url = settings.weather_api_base_url
        self.timeout = settings.weather_api_timeout_seconds
        self.client = client

    async def get_current(self, location_id: str, scenario: Scenario) -> WeatherResponse:
        location = get_location(location_id)
        params = {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "hourly": HOURLY_FIELDS,
            "past_hours": 24,
            "forecast_hours": 25,
            "timezone": "UTC",
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
                "WEATHER_PROVIDER_ERROR",
                "Live weather data is temporarily unavailable or invalid",
                502,
            ) from exc

    def _normalize(self, location_id: str, scenario: Scenario, payload: dict) -> WeatherResponse:
        location = get_location(location_id)
        hourly = payload["hourly"]
        times = [datetime.fromisoformat(value).replace(tzinfo=timezone.utc) for value in hourly["time"]]
        now = datetime.now(timezone.utc)
        current_index = max((index for index, value in enumerate(times) if value <= now), default=0)
        precipitation = [float(value or 0) for value in hourly["precipitation"]]

        def past_sum(hours: int) -> float:
            start = max(0, current_index - hours + 1)
            return round(sum(precipitation[start : current_index + 1]), 2)

        def forecast_sum(hours: int) -> float:
            return round(sum(precipitation[current_index + 1 : current_index + 1 + hours]), 2)

        soil_value = float(hourly["soil_moisture_0_to_7cm"][current_index] or 0)
        return WeatherResponse(
            location_id=location.id,
            location_name=location.name,
            timestamp=times[current_index],
            source="live",
            scenario=scenario.value,
            rainfall_current_mm=precipitation[current_index],
            rainfall_last_1h_mm=past_sum(1),
            rainfall_last_6h_mm=past_sum(6),
            rainfall_last_24h_mm=past_sum(24),
            forecast_rainfall_next_6h_mm=forecast_sum(6),
            forecast_rainfall_next_24h_mm=forecast_sum(24),
            temperature_c=float(hourly["temperature_2m"][current_index]),
            humidity_percent=float(hourly["relative_humidity_2m"][current_index]),
            soil_moisture_percent=round(min(max(soil_value * 100, 0), 100), 2),
        )
