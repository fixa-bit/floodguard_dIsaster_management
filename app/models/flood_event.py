"""Flood events tracked for event-triggered reports (dedupe table).

One row per flood incident on a river system. A new report version is issued only
when the event opens, escalates above the highest level already reported, or closes.
See docs/reports/flood_event_report_spec.md.
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FloodEvent(Base):
    __tablename__ = "flood_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_no: Mapped[str] = mapped_column(String(48), unique=True)  # e.g. FER-CHENAB-20261111-01
    river: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), default="OPEN", index=True)  # OPEN | CLOSED
    is_test: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # Level scale: 1 forecast/model watch, 2 Low flood ... 6 Exceptionally high flood (FFD observed).
    current_level: Mapped[int] = mapped_column(Integer, default=0)
    peak_level: Mapped[int] = mapped_column(Integer, default=0)
    reported_level: Mapped[int] = mapped_column(Integer, default=0)  # highest level already covered by a report
    peak_value_cumecs: Mapped[float | None] = mapped_column(Float, nullable=True)
    stations: Mapped[list] = mapped_column(JSON, default=list)  # station ids that have shown a signal
    signals: Mapped[list] = mapped_column(JSON, default=list)  # latest qualifying signals
    versions: Mapped[list] = mapped_column(JSON, default=list)  # [{version, reason, level, issued_at, path}]
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_signal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quiet_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # no signal since
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
