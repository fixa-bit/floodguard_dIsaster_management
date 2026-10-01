from datetime import datetime

from pydantic import BaseModel

from app.core.enums import Scenario


class SimulationStartRequest(BaseModel):
    scenario: Scenario
    location_id: str


class SimulationStatus(BaseModel):
    simulation_time: datetime
    scenario: str
    location_id: str
    monitoring_mode: str
    monitoring_interval_minutes: int
