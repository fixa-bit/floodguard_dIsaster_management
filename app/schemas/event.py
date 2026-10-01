from datetime import datetime

from app.schemas.common import ORMModel


class EventResponse(ORMModel):
    id: int
    timestamp: datetime
    event_type: str
    location_id: str | None
    message: str
    event_metadata: dict
