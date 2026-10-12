from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator


class ExposureRequest(BaseModel):
    region: str = Field(default="trimmu_jhang", pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    flood_source: Literal["historical_reference", "provided", "sample"] = "historical_reference"
    flood_extent: dict[str, Any] | None = None
    flood_crs: str = Field(default="EPSG:4326", max_length=128)
    flood_label: str = Field(default="User-provided flood extent (unverified)", max_length=250)
    population_method: Literal["fractional_area", "cell_center"] = "fractional_area"
    include_reference_buildings: bool = True

    @model_validator(mode="after")
    def check_source(self):
        if self.flood_source == "provided" and self.flood_extent is None:
            raise ValueError("provided source requires flood_extent GeoJSON")
        if self.flood_source != "provided" and self.flood_extent is not None:
            raise ValueError("flood_extent is accepted only with provided source")
        return self
