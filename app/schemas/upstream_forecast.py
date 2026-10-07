from pydantic import BaseModel


class HydroSeriesPoint(BaseModel):
    time: str
    value: float | None
    phase: str
    low: float | None = None
    high: float | None = None


class RainfallPoint(BaseModel):
    date: str
    precipitation_mm: float | None
    probability_percent: float | None
    phase: str


class ProviderForecast(BaseModel):
    provider: str
    source: str
    status: str
    river_id: int | None = None
    generated_at: str | None = None
    current_cumecs: float | None = None
    peak_forecast_cumecs: float | None = None
    peak_forecast_time: str | None = None
    recent_trend_cumecs: float | None = None
    series: list[HydroSeriesPoint]
    retrospective: list[HydroSeriesPoint]
    note: str | None = None


class FloodTypeSignal(BaseModel):
    type: str
    severity: str
    probability: int
    basis: str
    lead_time: str


class UpstreamStationForecast(BaseModel):
    id: str
    name: str
    river: str
    basin: str
    latitude: float
    longitude: float
    why_selected: str
    source_focus: str
    facts: list[str]
    providers: list[ProviderForecast]
    rainfall: list[RainfallPoint]
    flood_types: list[FloodTypeSignal]
    stats: dict[str, float | int | str | None]


class UpstreamForecastResponse(BaseModel):
    generated_at: str
    stations: list[UpstreamStationForecast]
    notes: list[str]
    cached_at: str | None = None
    last_attempt_at: str | None = None
    next_refresh_at: str | None = None
    refresh_interval_minutes: int = 60
    refreshing: bool = False
    refresh_error: str | None = None
