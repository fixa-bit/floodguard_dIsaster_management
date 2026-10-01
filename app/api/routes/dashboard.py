from sqlalchemy import func, select
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models.citizen_report import CitizenReport
from app.models.incident import Incident
from app.models.prediction import Prediction
from app.schemas.dashboard import DashboardSummary
from app.services.state_service import StateService

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/summary", response_model=DashboardSummary)
async def summary(db: Session = Depends(get_db)):
    state = StateService(db).get_state()
    active = db.scalar(select(func.count()).select_from(Incident).where(Incident.status.in_(["OPEN", "UNDER_VERIFICATION", "CONFIRMED"]))) or 0
    critical = db.scalar(select(func.count()).select_from(Incident).where(Incident.severity == "CRITICAL")) or 0
    predicted = db.scalar(select(func.count()).select_from(Prediction).where(Prediction.status == "PREDICTED")) or 0
    confirmed = db.scalar(select(func.count()).select_from(Prediction).where(Prediction.status == "CONFIRMED")) or 0
    pending = db.scalar(select(func.count()).select_from(CitizenReport).where(CitizenReport.verification_status == "PENDING")) or 0
    highest = db.scalar(select(func.max(Prediction.probability))) or 0
    return DashboardSummary(
        active_incidents=active,
        critical_incidents=critical,
        predicted_floods=predicted,
        confirmed_floods=confirmed,
        pending_citizen_reports=pending,
        highest_risk_probability=highest,
        monitoring_mode=state.monitoring_mode,
        system_mode=get_settings().data_mode.value,
    )
