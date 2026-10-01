from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.core.enums import EventType, IncidentStatus
from app.locations import get_location
from app.models.incident import Incident
from app.schemas.incident import IncidentCreate, IncidentUpdate
from app.services.event_service import EventService


class IncidentService:
    def __init__(self, db: Session):
        self.db = db

    def list(self) -> list[Incident]:
        return list(self.db.scalars(select(Incident).order_by(Incident.created_at.desc())))

    def get(self, incident_id: int) -> Incident:
        incident = self.db.get(Incident, incident_id)
        if incident is None:
            raise AppError("INCIDENT_NOT_FOUND", "Invalid incident id", 404)
        return incident

    def create(self, payload: IncidentCreate) -> Incident:
        get_location(payload.location_id)
        incident = Incident(**payload.model_dump(mode="json"))
        self.db.add(incident)
        self.db.commit()
        self.db.refresh(incident)
        EventService(self.db).record(EventType.INCIDENT_CREATED, f"Incident {incident.id} created", incident.location_id, {"incident_id": incident.id})
        return incident

    def update(self, incident_id: int, payload: IncidentUpdate) -> Incident:
        incident = self.get(incident_id)
        old_status = incident.status
        for key, value in payload.model_dump(exclude_unset=True, mode="json").items():
            setattr(incident, key, value)
        self.db.commit()
        self.db.refresh(incident)
        if incident.status == IncidentStatus.CONFIRMED.value and old_status != incident.status:
            EventService(self.db).record(EventType.INCIDENT_CONFIRMED, f"Incident {incident.id} confirmed", incident.location_id)
        return incident
