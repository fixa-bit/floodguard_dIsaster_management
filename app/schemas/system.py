from datetime import datetime

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    timestamp: datetime


class SystemStatusResponse(BaseModel):
    data_mode: str
    active_scenario: str
    monitoring_mode: str
    monitoring_interval_minutes: int
    backend_status: str
    simulation_enabled: bool
    rule_based_fallback_enabled: bool
    ml_model_enabled: bool
