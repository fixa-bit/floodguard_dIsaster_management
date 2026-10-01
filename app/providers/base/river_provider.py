from abc import ABC, abstractmethod

from app.core.enums import Scenario
from app.schemas.river import RiverResponse


class RiverProvider(ABC):
    @abstractmethod
    async def get_current(self, location_id: str, scenario: Scenario) -> RiverResponse:
        raise NotImplementedError
