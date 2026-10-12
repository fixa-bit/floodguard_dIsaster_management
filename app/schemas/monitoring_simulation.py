from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.schemas.event import EventResponse
from app.schemas.incident import IncidentResponse


class SimulationReading(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")

    offset_minutes: int = Field(default=0, ge=0, le=525600)
    value: float
    p25: float | None = None
    p75: float | None = None

    @model_validator(mode="after")
    def validate_band(self):
        if self.p25 is not None and self.p75 is not None and self.p25 > self.p75:
            raise ValueError("p25 must not exceed p75")
        return self


class MonitoringSimulationRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid", str_strip_whitespace=True)

    run_id: UUID
    name: str = Field(min_length=1, max_length=100)
    station: str = Field(min_length=1, max_length=80)
    measurement: Literal["discharge_inflow", "discharge_outflow", "water_level"]
    unit: Literal["cusecs", "m3/s", "m", "ft"]
    start_at: AwareDatetime
    level_reference: str | None = Field(default=None, min_length=1, max_length=160)
    threshold_mode: Literal["saved", "custom"] = "saved"
    warning_threshold: float | None = None
    danger_threshold: float | None = None
    readings: list[SimulationReading] = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def validate_scenario(self):
        is_level = self.measurement == "water_level"
        if self.unit not in ({"m", "ft"} if is_level else {"cusecs", "m3/s"}):
            raise ValueError("Unit does not match the selected measurement")
        if is_level and not self.level_reference:
            raise ValueError("Water level requires a gauge datum/reference")
        if not is_level and any(reading.value < 0 for reading in self.readings):
            raise ValueError("Discharge must be non-negative")
        offsets = [reading.offset_minutes for reading in self.readings]
        if offsets != sorted(set(offsets)):
            raise ValueError("Reading offsets must be unique and increasing")
        if self.threshold_mode == "custom":
            if self.warning_threshold is None and self.danger_threshold is None:
                raise ValueError("Enter at least one test threshold")
            if self.warning_threshold is not None and self.danger_threshold is not None:
                if self.warning_threshold >= self.danger_threshold:
                    raise ValueError("Danger threshold must exceed warning threshold")
            if not is_level and any(value < 0 for value in (self.warning_threshold, self.danger_threshold) if value is not None):
                raise ValueError("Discharge thresholds must be non-negative")
        elif self.warning_threshold is not None or self.danger_threshold is not None:
            raise ValueError("Custom limits require custom threshold mode")
        return self


class SimulationThreshold(BaseModel):
    measurement: str
    unit: str
    level: str
    value: float | None
    level_reference: str | None
    source_reference: str | None


class SimulationStation(BaseModel):
    code: str
    name: str
    river: str | None
    thresholds: list[SimulationThreshold]


class SimulationStoredReading(BaseModel):
    id: int
    value_at: AwareDatetime
    value: float
    level: str


class MonitoringSimulationResponse(BaseModel):
    run_id: str
    name: str
    station: str
    station_name: str
    provider: str
    value_type: Literal["simulated"] = "simulated"
    inserted: int
    readings: list[SimulationStoredReading]
    alerts: list[EventResponse]
    incidents: list[IncidentResponse]
