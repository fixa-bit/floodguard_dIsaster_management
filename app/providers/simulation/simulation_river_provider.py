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
            discharge_change_cumecs_per_day=round(river[4] * 24, 2),
            forecast_discharge_next_24h_cumecs=round(river[5] * (1 + min(max(river[4], -1), 1) * 0.08), 2),
            discharge_mean_cumecs=river[5],
            discharge_median_cumecs=river[5],
            discharge_min_cumecs=round(river[5] * 0.82, 2),
            discharge_max_cumecs=round(river[5] * 1.18, 2),
            discharge_p25_cumecs=round(river[5] * 0.92, 2),
            discharge_p75_cumecs=round(river[5] * 1.08, 2),
            status=river[6].value,
        )
