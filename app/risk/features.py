from pydantic import BaseModel

from app.schemas.river import RiverResponse
from app.schemas.weather import WeatherResponse


class RiskFeatures(BaseModel):
    rainfall_last_1h: float
    rainfall_last_6h: float
    rainfall_last_24h: float
    forecast_rainfall_24h: float
    river_level: float | None
    river_level_relative_to_warning: float | None
    river_rise_rate: float | None
    river_discharge: float
    river_discharge_change: float
    soil_moisture: float

    def as_model_vector(self) -> list[float]:
        return [
            self.rainfall_last_1h,
            self.rainfall_last_6h,
            self.rainfall_last_24h,
            self.forecast_rainfall_24h,
            self.river_level if self.river_level is not None else float("nan"),
            self.river_level_relative_to_warning if self.river_level_relative_to_warning is not None else float("nan"),
            self.river_rise_rate if self.river_rise_rate is not None else float("nan"),
            self.river_discharge,
            self.river_discharge_change,
            self.soil_moisture,
        ]


def build_features(weather: WeatherResponse, river: RiverResponse) -> RiskFeatures:
    return RiskFeatures(
        rainfall_last_1h=weather.rainfall_last_1h_mm,
        rainfall_last_6h=weather.rainfall_last_6h_mm,
        rainfall_last_24h=weather.rainfall_last_24h_mm,
        forecast_rainfall_24h=weather.forecast_rainfall_next_24h_mm,
        river_level=river.river_level_m,
        river_level_relative_to_warning=(
            river.river_level_m / river.warning_level_m
            if river.river_level_m is not None and river.warning_level_m
            else None
        ),
        river_rise_rate=river.rate_of_rise_m_per_hour,
        river_discharge=river.discharge_cumecs or 0.0,
        river_discharge_change=river.discharge_change_cumecs_per_day or 0.0,
        soil_moisture=weather.soil_moisture_percent,
    )
