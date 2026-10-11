from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.upstream_forecast import UpstreamForecastResponse, UpstreamStationForecast


class GaugeReading(BaseModel):
    gauge: Literal["INFLOW", "OUTFLOW"]
    value: float
    time: str
    source: str = "https://ffd.pmd.gov.pk/river-state?zoom=6"


class RiverMonitoringStation(UpstreamStationForecast):
    gauge_readings: list[GaugeReading] = Field(default_factory=list)
    current_discharge_cumecs: float | None = None
    current_source: str
    observed_at: str | None = None
    observed_level_value: float | None = None
    observed_level_unit: str | None = None
    level_source: str | None = None
    level_observed_at: str | None = None
    forecast_discharge_cumecs: float | None = None
    forecast_valid_at: str | None = None
    change_24h_cumecs: float | None = None
    change_source: str
    flood_category: str
    official_forecast_text: str | None = None
    expected_peak_at: str | None = None
    expected_peak_cumecs: float | None = None
    upstream_station_ids: list[str]


class RiverMonitoringResponse(UpstreamForecastResponse):
    stations: list[RiverMonitoringStation]
    chains: dict[str, list[str]] = {}
