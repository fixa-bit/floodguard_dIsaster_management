from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.enums import EventType, HazardType, IncidentStatus, Severity
from app.core.exceptions import AppError
from app.models.incident import Incident
from app.models.system_event import SystemEvent


class SimulatedAlertService:
    def __init__(self, db: Session):
        self.db = db

    def approve(self, alert_id: int) -> SystemEvent:
        alert = self.db.get(SystemEvent, alert_id, with_for_update=True)
        if alert is None or alert.event_type != EventType.ALERT_REQUIRED.value:
            raise AppError("ALERT_NOT_FOUND", "Alert not found", 404)
        metadata = dict(alert.event_metadata or {})
        if metadata.get("source") != "SIMULATED_FLOW":
            raise AppError("ALERT_NOT_SIMULATED", "Only simulated alerts can be approved here", 400)

        linked_id = metadata.get("incident_id")
        linked = self.db.get(Incident, linked_id) if isinstance(linked_id, int) else None
        if linked is None:
            severity = metadata.get("severity")
            if severity not in (Severity.HIGH.value, Severity.CRITICAL.value):
                raise AppError("ALERT_INVALID_SEVERITY", "Simulated alert has no valid severity", 400)
            incident = Incident(
                location_id=alert.location_id or str(metadata.get("station", "")),
                type=HazardType.FLOOD.value,
                severity=severity,
                status=IncidentStatus.OPEN.value,
                confidence=1.0,
                description=alert.message,
                source="SIMULATED_FLOW",
            )
            self.db.add(incident)
            self.db.flush()
            metadata["incident_id"] = incident.id
            self.db.add(SystemEvent(
                event_type=EventType.INCIDENT_CREATED.value,
                location_id=alert.location_id,
                message=f"SIMULATED FLOW - Incident {incident.id} recorded for {metadata.get('station_name', alert.location_id)}",
                event_metadata={**metadata, "alert_id": alert.id, "approval_status": "approved"},
            ))

        if metadata.get("approval_status") != "approved":
            metadata["approval_status"] = "approved"
            metadata["approved_at"] = datetime.now(timezone.utc).isoformat()
        alert.event_metadata = metadata
        self.db.commit()
        self.db.refresh(alert)
        return alert
