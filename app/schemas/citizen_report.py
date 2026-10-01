from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel


class CitizenReportCreate(BaseModel):
    location_id: str
    latitude: float
    longitude: float
    description: str
    image_url: str | None = None
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
    reported_water_depth_cm: float | None
    source: str
    verification_status: str
    timestamp: datetime
