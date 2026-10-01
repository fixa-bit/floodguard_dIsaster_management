from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.core.enums import EventType, VerificationStatus
from app.locations import get_location
from app.models.citizen_report import CitizenReport
from app.schemas.citizen_report import CitizenReportCreate
from app.services.event_service import EventService


class CitizenReportService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, payload: CitizenReportCreate) -> CitizenReport:
        get_location(payload.location_id)
        data = payload.model_dump()
        data["timestamp"] = data["timestamp"] or datetime.now(timezone.utc)
        report = CitizenReport(**data, verification_status=VerificationStatus.PENDING.value)
        self.db.add(report)
        self.db.commit()
        self.db.refresh(report)
        EventService(self.db).record(EventType.CITIZEN_REPORT_RECEIVED, f"Citizen report {report.id} received", report.location_id, {"report_id": report.id})
        return report

    def list(self) -> list[CitizenReport]:
        return list(self.db.scalars(select(CitizenReport).order_by(CitizenReport.timestamp.desc())))

    def get(self, report_id: int) -> CitizenReport:
        report = self.db.get(CitizenReport, report_id)
        if report is None:
            raise AppError("REPORT_NOT_FOUND", "Citizen report not found", 404)
        return report
