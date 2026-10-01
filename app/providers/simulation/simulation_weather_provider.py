from datetime import datetime, timezone

from app.core.enums import Scenario
from app.locations import get_location
from app.providers.base.weather_provider import WeatherProvider
from app.schemas.weather import WeatherResponse
from app.simulation.scenarios import SCENARIOS


class SimulationWeatherProvider(WeatherProvider):
    async def get_current(self, location_id: str, scenario: Scenario) -> WeatherResponse:
        location = get_location(location_id)
        values = SCENARIOS[scenario]["weather"]
        return WeatherResponse(
            location_id=location.id,
            location_name=location.name,
            timestamp=datetime.now(timezone.utc),
            source="simulation",
            scenario=scenario.value,
            rainfall_current_mm=values[0],
            rainfall_last_1h_mm=values[1],
            rainfall_last_6h_mm=values[2],
            rainfall_last_24h_mm=values[3],
            forecast_rainfall_next_6h_mm=values[4],
            forecast_rainfall_next_24h_mm=values[5],
            temperature_c=values[6],
            humidity_percent=values[7],
            soil_moisture_percent=values[8],
        )
