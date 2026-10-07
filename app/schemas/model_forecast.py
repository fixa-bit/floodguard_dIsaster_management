from datetime import datetime

from app.schemas.common import ORMModel


class ModelForecastPointResponse(ORMModel):
    id: int
    model_case: str
    target_id: str
    target_name: str
    issued_at: datetime
    valid_at: datetime
    horizon_hours: int
    value: float
    value_unit: str
    probability: float | None
    risk_class: str
    model_name: str
    point_metadata: dict
    created_at: datetime
