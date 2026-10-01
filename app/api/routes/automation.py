from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.routes.flood import flood_risk
from app.db.session import get_db
from app.schemas.automation import AutomationContext

router = APIRouter(prefix="/automation", tags=["Automation"])


@router.get("/context", response_model=AutomationContext)
async def context(location_id: str, db: Session = Depends(get_db)):
    risk = await flood_risk(location_id, db)
    return AutomationContext(
        location_id=location_id,
        risk_probability=risk.flood_probability,
        severity=risk.severity,
        incident_status=risk.status,
        monitoring_interval_minutes=risk.monitoring_interval_minutes,
        requires_verification=risk.severity in {"MEDIUM", "HIGH"},
        requires_alert=risk.severity == "CRITICAL" or risk.status == "CONFIRMED",
    )
