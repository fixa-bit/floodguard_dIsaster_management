from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.enums import EventType
from app.db.session import get_db
from app.schemas.event import EventResponse
from app.services.event_service import EventService

router = APIRouter(prefix="/events", tags=["Events"])


@router.get("", response_model=list[EventResponse])
async def events(location_id: str | None = None, event_type: EventType | None = None, limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    return EventService(db).list(location_id, event_type, limit)
