from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.enums import DataMode


class Settings(BaseSettings):
    app_env: str = "development"
    app_version: str = "0.1.0"
    data_mode: DataMode = DataMode.LIVE
    database_url: str = "sqlite:///./floodguard.db"
    default_location_id: str = "JHG_001"
    default_monitoring_interval: int = 60
    monitoring_downgrade_cooldown_minutes: int = 30
    cors_origins: str = Field(default="http://localhost:3000,http://127.0.0.1:3000")
    weather_api_base_url: str = "https://api.open-meteo.com/v1/forecast"
    weather_api_timeout_seconds: float = 10.0
    flood_api_base_url: str = "https://flood-api.open-meteo.com/v1/flood"
    flood_api_timeout_seconds: float = 10.0
    google_flood_api_key: SecretStr = SecretStr("")
    google_flood_region_codes: str = "PK"
    google_flood_cache_seconds: int = Field(default=600, ge=60, le=86400)
    upstream_forecast_refresh_minutes: int = Field(default=60, ge=1)
    river_monitoring_refresh_minutes: int = Field(default=15, ge=1)
    gis_cache_ttl_seconds: int = 1800
    gis_weather_batch_size: int = 40
    gis_river_batch_size: int = 40
    gis_history_retention_days: int = 30
    exposure_dataset_root: str = ""
    exposure_output_root: str = ""
    ml_model_enabled: bool = False
    ml_model_path: str = "app/ml/artifacts/flood_risk_xgboost.json"
    allow_rule_based_fallback: bool = False
    enable_simulation: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
