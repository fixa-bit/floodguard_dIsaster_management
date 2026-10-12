"""Add station reference limits without changing existing station values."""

from sqlalchemy import inspect, text

from ..models import Threshold
from .v004_station_values import TABLES as VALUE_TABLES, upgrade as upgrade_values


TABLES = VALUE_TABLES | {"thresholds"}


def upgrade(engine):
    current = set(inspect(engine).get_table_names())
    backup = None
    if current != TABLES:
        backup = upgrade_values(engine)
        with engine.begin() as connection:
            Threshold.__table__.create(connection, checkfirst=True)
    if engine.dialect.name == "sqlite":
        with engine.begin() as connection:
            connection.execute(text("PRAGMA user_version=5"))
    return backup
