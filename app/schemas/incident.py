from datetime import datetime

from pydantic import BaseModel, Field

from app.core.enums import HazardType, IncidentStatus, Severity
from app.schemas.common import ORMModel


class IncidentCreate(BaseModel):
    location_id: str
    type: HazardType = HazardType.FLOOD
    severity: Severity
    status: IncidentStatus = IncidentStatus.OPEN
    confidence: float = Field(ge=0, le=1)
    description: str
    source: str = "manual"


class IncidentUpdate(BaseModel):
    severity: Severity | None = None
    status: IncidentStatus | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    description: str | None = None


class IncidentResponse(ORMModel):
    id: int
    location_id: str
    type: str
    severity: str
    status: str
    confidence: float
    description: str
    source: str
    created_at: datetime
    updated_at: datetime
