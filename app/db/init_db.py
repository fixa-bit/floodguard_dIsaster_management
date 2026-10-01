from app.db.base import Base
from sqlalchemy import inspect, text

from app.db.session import engine
from app.models import citizen_report, district_risk_snapshot, incident, prediction, system_event, system_state


def init_db() -> None:
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    Base.metadata.create_all(bind=engine)
    _migrate_prediction_columns()


def _migrate_prediction_columns() -> None:
    """Keep existing development databases compatible without requiring Alembic."""
    existing = {column["name"] for column in inspect(engine).get_columns("predictions")}
    additions = {
        "trend": "VARCHAR(32) NOT NULL DEFAULT 'STABLE'",
        "probability_change": "FLOAT NOT NULL DEFAULT 0",
        "model_name": "VARCHAR(64) NOT NULL DEFAULT 'rule_based_v1'",
        "model_type": "VARCHAR(32) NOT NULL DEFAULT 'rule_based'",
        "top_risk_factors": "JSON NOT NULL DEFAULT '[]'",
        "weather_source": "VARCHAR(32) NOT NULL DEFAULT 'simulation'",
        "river_source": "VARCHAR(32) NOT NULL DEFAULT 'simulation'",
    }
    with engine.begin() as connection:
        for name, definition in additions.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE predictions ADD COLUMN {name} {definition}"))
