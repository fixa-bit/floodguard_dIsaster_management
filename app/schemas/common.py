from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class EnvironmentalBase(BaseModel):
    location_id: str
    location_name: str
    timestamp: datetime
    source: str
    scenario: str
