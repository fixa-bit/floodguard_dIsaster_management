from pydantic import BaseModel


class AutomationContext(BaseModel):
    location_id: str
    risk_probability: float
    severity: str
    incident_status: str
    monitoring_interval_minutes: int
    requires_verification: bool
    requires_alert: bool
