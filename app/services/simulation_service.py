from app.core.enums import EventType, Scenario
from app.locations import get_location
from app.schemas.simulation import SimulationStartRequest
from app.services.event_service import EventService
from app.services.state_service import StateService
from app.simulation.scenarios import SCENARIO_SEQUENCE


class SimulationService:
    def __init__(self, db):
        self.db = db
        self.state_service = StateService(db)

    def start(self, payload: SimulationStartRequest):
        get_location(payload.location_id)
        state = self.state_service.set_scenario(payload.scenario, payload.location_id)
        EventService(self.db).record(EventType.SIMULATION_STARTED, f"Simulation started with {payload.scenario.value}", payload.location_id)
        return state

    def reset(self):
        state = self.state_service.set_scenario(Scenario.NORMAL, self.state_service.get_state().active_location_id)
        EventService(self.db).record(EventType.SIMULATION_STARTED, "Simulation reset to NORMAL", state.active_location_id)
        return state

    def advance(self):
        state = self.state_service.get_state()
        current = Scenario(state.active_scenario)
        next_index = min(SCENARIO_SEQUENCE.index(current) + 1, len(SCENARIO_SEQUENCE) - 1) if current in SCENARIO_SEQUENCE else 0
        state = self.state_service.set_scenario(SCENARIO_SEQUENCE[next_index], state.active_location_id)
        state = self.state_service.advance_time()
        EventService(self.db).record(EventType.SIMULATION_ADVANCED, f"Simulation advanced to {state.active_scenario}", state.active_location_id)
        return state
