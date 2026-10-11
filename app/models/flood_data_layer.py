from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Interval,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Geometry4326(UserDefinedType):
    """PostGIS geometry in production, WKT text in SQLite development/test DBs."""

    cache_ok = True

    def get_col_spec(self, **kw: object) -> str:
        return "TEXT"


@compiles(Geometry4326, "postgresql")
def _compile_geometry_postgresql(type_: Geometry4326, compiler: object, **kw: object) -> str:
    return "geometry(Geometry,4326)"


@compiles(Geometry4326, "sqlite")
def _compile_geometry_sqlite(type_: Geometry4326, compiler: object, **kw: object) -> str:
    return "TEXT"


class FloodLocation(Base):
    __tablename__ = "locations"
    __table_args__ = (
        CheckConstraint(
            "kind in ('station','barrage','dam','basin','subbasin','district','coastal_point','grid_cell')",
            name="ck_locations_kind",
        ),
        Index("ix_locations_geom_gist", "geom", postgresql_using="gist"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    river: Mapped[str | None] = mapped_column(String(80), nullable=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    geom: Mapped[str | None] = mapped_column(Geometry4326(), nullable=True)
    glofas_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    glofas_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class FloodVariable(Base):
    __tablename__ = "variables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class FloodSource(Base):
    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint(
            "kind in ('external','agency','manual','citizen','derived','model')",
            name="ck_sources_kind",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (
        CheckConstraint("quality in (0,1,2,3)", name="ck_observations_quality"),
        Index("ix_observations_variable_observed_at", "variable_id", "observed_at"),
        Index("ix_observations_location_variable_observed_at", "location_id", "variable_id", "observed_at"),
    )

    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), primary_key=True)
    variable_id: Mapped[int] = mapped_column(ForeignKey("variables.id"), primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    quality: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    raw: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ForecastModelRegistry(Base):
    __tablename__ = "models"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_models_name_version"),
        CheckConstraint(
            "hazard in ('riverine','flash_flood','coastal','glof','urban','drought','generic')",
            name="ck_models_hazard",
        ),
        CheckConstraint("horizon in ('nowcast','short','medium','long','seasonal')", name="ck_models_horizon"),
        CheckConstraint("kind in ('external','physical','ml','ensemble','baseline')", name="ck_models_kind"),
        CheckConstraint("status in ('planned','training','shadow','active','retired')", name="ck_models_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    hazard: Mapped[str] = mapped_column(String(32), nullable=False)
    horizon: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    artifact_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    input_spec: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    output_spec: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    training: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ModelCoverage(Base):
    __tablename__ = "model_coverage"

    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), primary_key=True)
    variable_id: Mapped[int] = mapped_column(ForeignKey("variables.id"), primary_key=True)


class ForecastRun(Base):
    __tablename__ = "forecast_runs"
    __table_args__ = (
        UniqueConstraint("model_id", "issued_at", name="uq_forecast_runs_model_issued_at"),
        CheckConstraint("status in ('running','complete','failed')", name="ck_forecast_runs_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False, index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    init_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    step: Mapped[object | None] = mapped_column(Interval, nullable=True)
    lead_max: Mapped[object | None] = mapped_column(Interval, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    params: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ForecastValue(Base):
    __tablename__ = "forecast_values"
    __table_args__ = (
        Index("ix_forecast_values_location_variable_valid_at", "location_id", "variable_id", "valid_at"),
    )

    run_id: Mapped[int] = mapped_column(ForeignKey("forecast_runs.id", ondelete="CASCADE"), primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), primary_key=True)
    variable_id: Mapped[int] = mapped_column(ForeignKey("variables.id"), primary_key=True)
    valid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    p10: Mapped[float | None] = mapped_column(Float, nullable=True)
    p25: Mapped[float | None] = mapped_column(Float, nullable=True)
    p50: Mapped[float | None] = mapped_column(Float, nullable=True)
    p75: Mapped[float | None] = mapped_column(Float, nullable=True)
    p90: Mapped[float | None] = mapped_column(Float, nullable=True)
    prob_exceed: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Threshold(Base):
    __tablename__ = "thresholds"
    __table_args__ = (
        CheckConstraint("hazard in ('riverine','flash_flood','coastal','glof','urban','drought','generic')", name="ck_thresholds_hazard"),
        CheckConstraint("level between 1 and 5", name="ck_thresholds_level"),
        Index("ix_thresholds_location_variable_hazard", "location_id", "variable_id", "hazard"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)
    variable_id: Mapped[int] = mapped_column(ForeignKey("variables.id"), nullable=False)
    hazard: Mapped[str] = mapped_column(String(32), nullable=False)
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str | None] = mapped_column(String(160), nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class RecordValue(Base):
    __tablename__ = "record_values"

    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), primary_key=True)
    variable_id: Mapped[int] = mapped_column(ForeignKey("variables.id"), primary_key=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    occurred_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str | None] = mapped_column(String(160), nullable=True)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint("basis in ('observed','forecast','stale_data')", name="ck_alerts_basis"),
        CheckConstraint("status in ('active','escalated','cleared')", name="ck_alerts_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)
    variable_id: Mapped[int | None] = mapped_column(ForeignKey("variables.id"), nullable=True)
    hazard: Mapped[str] = mapped_column(String(32), nullable=False)
    basis: Mapped[str] = mapped_column(String(32), nullable=False)
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    model_id: Mapped[int | None] = mapped_column(ForeignKey("models.id"), nullable=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("forecast_runs.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    peak_expected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


Index(
    "uq_alerts_one_non_cleared",
    Alert.location_id,
    Alert.hazard,
    Alert.basis,
    func.coalesce(Alert.model_id, 0),
    unique=True,
    sqlite_where=(Alert.status != "cleared"),
    postgresql_where=(Alert.status != "cleared"),
)


class AlertEvent(Base):
    __tablename__ = "alert_events"
    __table_args__ = (
        CheckConstraint("event in ('created','escalated','deescalated','cleared','notified')", name="ck_alert_events_event"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id"), nullable=False, index=True)
    event: Mapped[str] = mapped_column(String(32), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class NotificationChannel(Base):
    __tablename__ = "notification_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class Subscriber(Base):
    __tablename__ = "subscribers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    locations: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    min_level: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id"), nullable=False, index=True)
    subscriber_id: Mapped[int] = mapped_column(ForeignKey("subscribers.id"), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class IngestionLog(Base):
    __tablename__ = "ingestion_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    rows_read: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_written: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class SourceHealth(Base):
    __tablename__ = "source_health"

    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), primary_key=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_observation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stale_after: Mapped[object | None] = mapped_column(Interval, nullable=True)


class ModelSkill(Base):
    __tablename__ = "model_skill"
    __table_args__ = (
        UniqueConstraint(
            "model_id",
            "location_id",
            "variable_id",
            "lead_hours",
            "window_start",
            "window_end",
            name="uq_model_skill_window",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)
    variable_id: Mapped[int] = mapped_column(ForeignKey("variables.id"), nullable=False)
    lead_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    n: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rmse: Mapped[float | None] = mapped_column(Float, nullable=True)
    mae: Mapped[float | None] = mapped_column(Float, nullable=True)
    bias: Mapped[float | None] = mapped_column(Float, nullable=True)
    nse: Mapped[float | None] = mapped_column(Float, nullable=True)
    hit_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    false_alarm_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class DataRetentionPolicy(Base):
    __tablename__ = "data_retention_policy"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    policy: Mapped[str] = mapped_column(Text, nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class PartitionPlan(Base):
    __tablename__ = "partition_plan"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    table_name: Mapped[str] = mapped_column(String(80), nullable=False)
    month_start: Mapped[datetime] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="planned", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
