from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DistrictRiskSnapshot(Base):
    __tablename__ = "district_risk_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    district_id: Mapped[str] = mapped_column(String(64), index=True)
    district_name: Mapped[str] = mapped_column(String(128))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    horizon_hours: Mapped[int] = mapped_column(Integer, default=0, index=True)
    probability: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float)
    rainfall_24h_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    forecast_rainfall_24h_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    soil_moisture_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    discharge_cumecs: Mapped[float | None] = mapped_column(Float, nullable=True)
    discharge_change_cumecs_per_day: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_name: Mapped[str] = mapped_column(String(64))
    model_type: Mapped[str] = mapped_column(String(64))
    weather_source: Mapped[str] = mapped_column(String(64))
    river_source: Mapped[str] = mapped_column(String(64))
