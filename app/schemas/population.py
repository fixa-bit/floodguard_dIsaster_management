from typing import Literal
from pydantic import Field
from app.schemas.exposure import ExposureRequest


class PopulationRequest(ExposureRequest):
    flood_source: Literal['historical_reference', 'provided', 'sample', 'segmentation'] = 'historical_reference'
    include_reference_buildings: bool = False
    population_method: Literal['fractional_area'] = 'fractional_area'
    grid_km: float = Field(default=2, ge=1, le=25)
