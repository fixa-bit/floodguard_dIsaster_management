from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import EventType
from app.models.system_event import SystemEvent


class EventService:
    def __init__(self, db: Session):
        self.db = db

    def record(self, event_type: EventType, message: str, location_id: str | None = None, metadata: dict | None = None) -> SystemEvent:
        event = SystemEvent(
            event_type=event_type.value,
            location_id=location_id,
            message=message,
            event_metadata=metadata or {},
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    def list(self, location_id: str | None = None, event_type: EventType | None = None, limit: int = 50) -> list[SystemEvent]:
        query = select(SystemEvent).order_by(SystemEvent.timestamp.desc()).limit(limit)
        if location_id:
            query = query.where(SystemEvent.location_id == location_id)
        if event_type:
            query = query.where(SystemEvent.event_type == event_type.value)
        return list(self.db.scalars(query))
