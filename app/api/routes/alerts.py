from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.enums import EventType
from app.db.session import get_db
from app.schemas.event import EventResponse
from app.services.event_service import EventService
from app.services.simulated_alert_service import SimulatedAlertService

router = APIRouter(prefix="/alerts", tags=["Alerts"])


@router.get("", response_model=list[EventResponse])
def alerts(limit: int = Query(500, ge=1, le=500), db: Session = Depends(get_db)):
    return EventService(db).list(event_type=EventType.ALERT_REQUIRED, limit=limit)


@router.post("/{alert_id}/approve", response_model=EventResponse)
def approve_simulated_alert(alert_id: int, db: Session = Depends(get_db)):
    return SimulatedAlertService(db).approve(alert_id)
