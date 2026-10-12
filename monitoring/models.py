from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, UTCDateTime


def utc_now():
    return datetime.now(timezone.utc)


class Station(Base):
    __tablename__ = "stations"
    __table_args__ = (
        CheckConstraint("latitude IS NULL OR latitude BETWEEN -90 AND 90", name="ck_station_latitude"),
        CheckConstraint("longitude IS NULL OR longitude BETWEEN -180 AND 180", name="ck_station_longitude"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    river: Mapped[str | None] = mapped_column(String(80))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)


class Provider(Base):
    __tablename__ = "providers"
    __table_args__ = (CheckConstraint("kind in ('api','model','import')", name="ck_provider_kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(80))


class StationValue(Base):
    __tablename__ = "station_values"
    __table_args__ = (
        CheckConstraint("value_type in ('observed','simulated','forecast')", name="ck_value_type"),
        CheckConstraint("p25 IS NULL OR p75 IS NULL OR p25 <= p75", name="ck_value_band"),
        Index("ix_station_values_timeline", "station_id", "measurement", "value_at"),
        Index("ix_station_values_provider_time", "provider_id", "station_id", "value_at", "forecast_issued_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), nullable=False)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), nullable=False)
    measurement: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    value_type: Mapped[str] = mapped_column(String(16), nullable=False)
    value_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    forecast_issued_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    stored_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    p25: Mapped[float | None] = mapped_column(Float)
    p75: Mapped[float | None] = mapped_column(Float)
    level_reference: Mapped[str | None] = mapped_column(String(160))


class Threshold(Base):
    __tablename__ = "thresholds"
    __table_args__ = (
        UniqueConstraint("station_id", "measurement", "unit", "level", name="uq_station_threshold"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), nullable=False)
    measurement: Mapped[str] = mapped_column(String(80), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    level: Mapped[str] = mapped_column(String(40), nullable=False)
    value: Mapped[float | None] = mapped_column(Float)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("providers.id"))
    source_reference: Mapped[str | None] = mapped_column(String(500))
    level_reference: Mapped[str | None] = mapped_column(String(160))
