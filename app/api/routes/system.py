from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.system import SystemStatusResponse
from app.services.state_service import StateService

router = APIRouter(prefix="/system", tags=["System"])


@router.get("/status", response_model=SystemStatusResponse)
async def status(db: Session = Depends(get_db)):
    settings = get_settings()
    state = StateService(db).get_state()
    return SystemStatusResponse(
        data_mode=settings.data_mode.value,
        active_scenario=state.active_scenario,
        monitoring_mode=state.monitoring_mode,
        monitoring_interval_minutes=state.monitoring_interval_minutes,
        backend_status="healthy",
        simulation_enabled=settings.enable_simulation,
        rule_based_fallback_enabled=settings.allow_rule_based_fallback,
        ml_model_enabled=settings.ml_model_enabled,
    )
