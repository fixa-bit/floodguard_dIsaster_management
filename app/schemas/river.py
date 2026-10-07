from app.schemas.common import EnvironmentalBase


class RiverResponse(EnvironmentalBase):
    river_name: str
    station_name: str
    river_level_m: float | None
    observed_level_value: float | None = None
    observed_level_unit: str | None = None
    official_recording_time: str | None = None
    data_note: str | None = None
    normal_level_m: float | None
    warning_level_m: float | None
    danger_level_m: float | None
    rate_of_rise_m_per_hour: float | None
    discharge_cumecs: float | None = None
    discharge_change_cumecs_per_day: float | None = None
    forecast_discharge_next_24h_cumecs: float | None = None
    discharge_mean_cumecs: float | None = None
    discharge_median_cumecs: float | None = None
    discharge_min_cumecs: float | None = None
    discharge_max_cumecs: float | None = None
    discharge_p25_cumecs: float | None = None
    discharge_p75_cumecs: float | None = None
    status: str
