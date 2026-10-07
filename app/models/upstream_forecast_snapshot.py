from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UpstreamForecastSnapshot(Base):
    __tablename__ = "upstream_forecast_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refresh_error: Mapped[str | None] = mapped_column(String(250), nullable=True)
