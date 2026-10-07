from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CitizenReport(Base):
    __tablename__ = "citizen_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    location_id: Mapped[str] = mapped_column(String(32), index=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    description: Mapped[str] = mapped_column(String(1000))
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    video_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    image_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    image_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    reported_water_depth_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(64))
    verification_status: Mapped[str] = mapped_column(String(32), index=True)
    report_status: Mapped[str] = mapped_column(String(32), default="OPEN", index=True)
    is_important: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    important_marked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
