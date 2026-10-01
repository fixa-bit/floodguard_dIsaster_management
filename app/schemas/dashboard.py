from pydantic import BaseModel


class DashboardSummary(BaseModel):
    active_incidents: int
    critical_incidents: int
    predicted_floods: int
    confirmed_floods: int
    pending_citizen_reports: int
    highest_risk_probability: float
    monitoring_mode: str
    system_mode: str
