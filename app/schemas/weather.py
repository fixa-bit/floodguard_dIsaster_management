from app.schemas.common import EnvironmentalBase


class WeatherResponse(EnvironmentalBase):
    rainfall_current_mm: float
    rainfall_last_1h_mm: float
    rainfall_last_6h_mm: float
    rainfall_last_24h_mm: float
    forecast_rainfall_next_6h_mm: float
    forecast_rainfall_next_24h_mm: float
    temperature_c: float
    humidity_percent: float
    soil_moisture_percent: float
