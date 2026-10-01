from sqlalchemy.orm import Session

from app.core.enums import DataMode, Scenario
from app.providers.base.river_provider import RiverProvider
from app.providers.live.live_river_provider import LiveRiverProvider
from app.providers.simulation.simulation_river_provider import SimulationRiverProvider
from app.schemas.river import RiverResponse
from app.services.state_service import StateService


def get_river_provider(data_mode: DataMode) -> RiverProvider:
    if data_mode == DataMode.SIMULATION:
        return SimulationRiverProvider()
    return LiveRiverProvider()


class RiverService:
    def __init__(self, db: Session, data_mode: DataMode):
        self.db = db
        self.data_mode = data_mode
        self.provider = get_river_provider(data_mode)

    async def current(self, location_id: str) -> RiverResponse:
        scenario = (
            Scenario(StateService(self.db).get_state().active_scenario)
            if self.data_mode == DataMode.SIMULATION
            else Scenario.NORMAL
        )
        return await self.provider.get_current(location_id, scenario)
