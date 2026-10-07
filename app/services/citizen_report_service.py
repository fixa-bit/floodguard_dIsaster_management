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
        EventService(self.db).record(
            EventType.CITIZEN_REPORT_RECEIVED,
            f"Citizen report {report.id} received",
            report.location_id,
            {
                "report_id": report.id,
                "has_image": bool(report.image_url),
                "has_video": bool(report.video_url),
                "has_image_geotag": report.image_latitude is not None and report.image_longitude is not None,
            },
        )
        return report

    def list(self) -> list[CitizenReport]:
        return list(self.db.scalars(select(CitizenReport).order_by(CitizenReport.timestamp.desc())))

    def get(self, report_id: int) -> CitizenReport:
        report = self.db.get(CitizenReport, report_id)
        if report is None:
            raise AppError("REPORT_NOT_FOUND", "Citizen report not found", 404)
        return report

    def toggle_important(self, report_id: int) -> CitizenReport:
        report = self.get(report_id)
        if report.report_status == "CLOSED":
            raise AppError("REPORT_CLOSED", "Closed reports cannot be changed", 409)

        report.is_important = not report.is_important
        report.important_marked_at = datetime.now(timezone.utc) if report.is_important else None
        self.db.add(report)
        self.db.commit()
        self.db.refresh(report)

        EventService(self.db).record(
            EventType.CITIZEN_REPORT_MARKED_IMPORTANT,
            f"Citizen report {report.id} {'marked important' if report.is_important else 'unmarked important'}",
            report.location_id,
            {
                "report_id": report.id,
                "is_important": report.is_important,
                "n8n_event_type": "citizen_report_important",
                "n8n_pending": report.is_important,
                "image_url": report.image_url,
                "video_url": report.video_url,
            },
        )
        return report

    def close(self, report_id: int) -> CitizenReport:
        report = self.get(report_id)
        if report.report_status != "CLOSED":
            report.report_status = "CLOSED"
            report.closed_at = datetime.now(timezone.utc)
            self.db.add(report)
            self.db.commit()
            self.db.refresh(report)

        EventService(self.db).record(
            EventType.CITIZEN_REPORT_CLOSED,
            f"Citizen report {report.id} closed",
            report.location_id,
            {"report_id": report.id},
        )
        return report
