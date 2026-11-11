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
    sar_unet_model_dir: str = ""
    allow_rule_based_fallback: bool = False
    enable_simulation: bool = False
    # Flood event reports (app/reports/flood_events.py): checked after each monitoring/forecast refresh.
    flood_event_reports_enabled: bool = True
    flood_event_close_after_hours: int = Field(default=24, ge=1)
    report_api_base: str = "http://127.0.0.1:8000/api/v1"
    report_frontend_url: str = "http://127.0.0.1:3000"
    report_run_satellite: bool = True
    report_capture_snapshots: bool = True
    # Daily Flood Situation Report schedule (app/services/report_jobs.py), local time in PKT.
    daily_report_schedule_enabled: bool = True
    daily_report_time: str = Field(default="06:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    daily_report_test_flood_region: str | None = "trimmu_jhang"
    # AI analysis of flagged signals (app/reports/ai/). Code owns status and calculations;
    # AI only explains values a rule flagged, in a separate, labelled block.
    anthropic_api_key: SecretStr = SecretStr("")
    ai_analysis_enabled: bool = True
    ai_model: str = "claude-opus-5-5"
    ai_explain_effort: str = "medium"
    ai_agent_effort: str = "high"
    ai_max_explanations: int = Field(default=4, ge=0, le=10)
    ai_max_agent_runs: int = Field(default=2, ge=0, le=5)
    ai_agent_max_turns: int = Field(default=8, ge=2, le=20)
    ai_agent_max_tool_calls: int = Field(default=12, ge=1, le=40)
    ai_agent_seconds: int = Field(default=240, ge=30)
    ai_timeout_seconds: int = Field(default=600, ge=60)
    ai_web_search: bool = True
    ai_web_search_max_uses: int = Field(default=3, ge=1, le=10)
    ai_web_search_domains: str = ("ffd.pmd.gov.pk,pmd.gov.pk,ffc.gov.pk,ndma.gov.pk,pdma.punjab.gov.pk,pdma.gos.pk,pdma.gov.pk,"
                                  "pdma.gob.pk,wapda.gov.pk,irsa.gov.pk,irrigation.punjab.gov.pk,app.com.pk,dawn.com,tribune.com.pk,thenews.com.pk")
    ai_review_automatic: str = Field(default="none", pattern=r"^(none|label|portal)$")
    ai_review_manual_default: str = Field(default="portal", pattern=r"^(label|portal)$")
    knowledge_dir: str = "knowledge"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
