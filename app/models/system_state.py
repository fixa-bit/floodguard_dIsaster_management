from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SystemState(Base):
    __tablename__ = "system_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    active_scenario: Mapped[str] = mapped_column(String(64), default="NORMAL")
    active_location_id: Mapped[str] = mapped_column(String(32), default="JHG_001")
    monitoring_mode: Mapped[str] = mapped_column(String(32), default="LOW")
    monitoring_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    simulation_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_monitoring_change_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
