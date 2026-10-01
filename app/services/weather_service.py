from sqlalchemy.orm import Session

from app.core.enums import DataMode, Scenario
from app.providers.base.weather_provider import WeatherProvider
from app.providers.live.live_weather_provider import LiveWeatherProvider
from app.providers.simulation.simulation_weather_provider import SimulationWeatherProvider
from app.schemas.weather import WeatherResponse
from app.services.state_service import StateService


def get_weather_provider(data_mode: DataMode) -> WeatherProvider:
    if data_mode in {DataMode.HYBRID, DataMode.LIVE}:
        return LiveWeatherProvider()
    return SimulationWeatherProvider()


class WeatherService:
    def __init__(self, db: Session, data_mode: DataMode):
        self.db = db
        self.data_mode = data_mode
        self.provider = get_weather_provider(data_mode)

    async def current(self, location_id: str) -> WeatherResponse:
        scenario = (
            Scenario(StateService(self.db).get_state().active_scenario)
            if self.data_mode == DataMode.SIMULATION
            else Scenario.NORMAL
        )
        return await self.provider.get_current(location_id, scenario)
