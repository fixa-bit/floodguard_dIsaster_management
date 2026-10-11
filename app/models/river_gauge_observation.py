from datetime import datetime

from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RiverGaugeObservation(Base):
    __tablename__ = "river_gauge_observations"

    station_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    discharge_cumecs: Mapped[float] = mapped_column(Float)


class TypedRiverGaugeObservation(Base):
    __tablename__ = "typed_river_gauge_observations"

    station_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    gauge: Mapped[str] = mapped_column(String(8), primary_key=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    discharge_cumecs: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(500))
