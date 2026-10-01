from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.schemas.simulation import SimulationStartRequest, SimulationStatus
from app.services.simulation_service import SimulationService
from app.services.state_service import StateService

router = APIRouter(prefix="/simulation", tags=["Simulation"])


def require_simulation_enabled() -> None:
    if not get_settings().enable_simulation:
        raise AppError("SIMULATION_DISABLED", "Simulation is disabled in this real-data deployment", 403)


def state_response(state) -> SimulationStatus:
    return SimulationStatus(
        simulation_time=state.simulation_time,
        scenario=state.active_scenario,
        location_id=state.active_location_id,
        monitoring_mode=state.monitoring_mode,
        monitoring_interval_minutes=state.monitoring_interval_minutes,
    )


@router.post("/start", response_model=SimulationStatus)
async def start(payload: SimulationStartRequest, db: Session = Depends(get_db)):
    require_simulation_enabled()
    return state_response(SimulationService(db).start(payload))


@router.post("/reset", response_model=SimulationStatus)
async def reset(db: Session = Depends(get_db)):
    require_simulation_enabled()
    return state_response(SimulationService(db).reset())


@router.post("/advance", response_model=SimulationStatus)
async def advance(db: Session = Depends(get_db)):
    require_simulation_enabled()
    return state_response(SimulationService(db).advance())


@router.get("/status", response_model=SimulationStatus)
async def status(db: Session = Depends(get_db)):
    return state_response(StateService(db).get_state())
