from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel


class CitizenReportCreate(BaseModel):
    location_id: str
    latitude: float
    longitude: float
    description: str
    image_url: str | None = None
    video_url: str | None = None
    image_latitude: float | None = None
    image_longitude: float | None = None
    reported_water_depth_cm: float | None = None
    source: str = "citizen"
    timestamp: datetime | None = None


class CitizenReportResponse(ORMModel):
    id: int
    location_id: str
    latitude: float
    longitude: float
    description: str
    image_url: str | None
    video_url: str | None
    image_latitude: float | None
    image_longitude: float | None
    reported_water_depth_cm: float | None
    source: str
    verification_status: str
    report_status: str
    is_important: bool
    important_marked_at: datetime | None
    closed_at: datetime | None
    timestamp: datetime
