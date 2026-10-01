from datetime import datetime, timezone

from app.core.enums import Scenario
from app.locations import get_location
from app.providers.base.river_provider import RiverProvider
from app.schemas.river import RiverResponse
from app.simulation.scenarios import SCENARIOS


class SimulationRiverProvider(RiverProvider):
    async def get_current(self, location_id: str, scenario: Scenario) -> RiverResponse:
        location = get_location(location_id)
        river = SCENARIOS[scenario]["river"]
        return RiverResponse(
            location_id=location.id,
            location_name=location.name,
            timestamp=datetime.now(timezone.utc),
            source="simulation",
            scenario=scenario.value,
            river_name=location.river_name or "N/A",
            station_name=f"{location.name} Simulation Gauge",
            river_level_m=river[0],
            normal_level_m=river[1],
            warning_level_m=river[2],
            danger_level_m=river[3],
            rate_of_rise_m_per_hour=river[4],
            discharge_cumecs=river[5],
            status=river[6].value,
        )
