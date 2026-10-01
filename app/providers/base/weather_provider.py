from abc import ABC, abstractmethod

from app.core.enums import Scenario
from app.schemas.weather import WeatherResponse


class WeatherProvider(ABC):
    @abstractmethod
    async def get_current(self, location_id: str, scenario: Scenario) -> WeatherResponse:
        raise NotImplementedError
