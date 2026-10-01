from datetime import datetime

from app.schemas.common import ORMModel


class RiskResponse(ORMModel):
    location_id: str
    location_name: str
    timestamp: datetime
    scenario: str
    flood_probability: float
    severity: str
    status: str
    confidence: float
    factors: list[str]
    explanation: str
    monitoring_mode: str
    monitoring_interval_minutes: int
    trend: str
    probability_change: float
    model: str
    model_type: str
    top_risk_factors: list[str]
    data_sources: dict[str, str]


class PredictionResponse(ORMModel):
    id: int
    location_id: str
    scenario: str
    probability: float
    severity: str
    status: str
    confidence: float
    factors: list[str]
    explanation: str
    monitoring_interval_minutes: int
    trend: str
    probability_change: float
    model_name: str
    model_type: str
    top_risk_factors: list[str]
    weather_source: str
    river_source: str
    created_at: datetime
