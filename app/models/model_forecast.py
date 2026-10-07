from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ModelForecastPoint(Base):
    __tablename__ = "model_forecast_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    model_case: Mapped[str] = mapped_column(String(48), index=True)
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    target_name: Mapped[str] = mapped_column(String(120))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    valid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    horizon_hours: Mapped[int] = mapped_column(Integer)
    value: Mapped[float] = mapped_column(Float)
    value_unit: Mapped[str] = mapped_column(String(32))
    probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_class: Mapped[str] = mapped_column(String(48))
    model_name: Mapped[str] = mapped_column(String(96))
    point_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
