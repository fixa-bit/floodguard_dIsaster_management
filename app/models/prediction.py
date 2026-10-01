from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    location_id: Mapped[str] = mapped_column(String(32), index=True)
    scenario: Mapped[str] = mapped_column(String(64))
    probability: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    factors: Mapped[list[str]] = mapped_column(JSON)
    explanation: Mapped[str] = mapped_column(String(500))
    monitoring_interval_minutes: Mapped[int] = mapped_column(Integer)
    trend: Mapped[str] = mapped_column(String(32), default="STABLE")
    probability_change: Mapped[float] = mapped_column(Float, default=0.0)
    model_name: Mapped[str] = mapped_column(String(64), default="rule_based_v1")
    model_type: Mapped[str] = mapped_column(String(32), default="rule_based")
    top_risk_factors: Mapped[list[str]] = mapped_column(JSON, default=list)
    weather_source: Mapped[str] = mapped_column(String(32), default="simulation")
    river_source: Mapped[str] = mapped_column(String(32), default="simulation")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
