from datetime import datetime, timedelta, timezone

from app.db.base import Base
from sqlalchemy import func, inspect, select, text

from app.core.enums import VerificationStatus
from app.db.session import engine
from app.models.citizen_report import CitizenReport
from app.models.model_forecast import ModelForecastPoint
from app.models import river_gauge_observation
from app.models import citizen_report, district_risk_snapshot, incident, model_forecast, prediction, system_event, system_state, upstream_forecast_snapshot
from app.simulation.model_forecasts import build_dummy_model_forecasts


def init_db() -> None:
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    Base.metadata.create_all(bind=engine)
    _migrate_prediction_columns()
    _migrate_citizen_report_columns()
    _seed_dummy_model_forecasts()
    _seed_dummy_citizen_reports()


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


def _migrate_citizen_report_columns() -> None:
    """Keep existing development report tables compatible without requiring Alembic."""
    existing = {column["name"] for column in inspect(engine).get_columns("citizen_reports")}
    bool_default = "BOOLEAN NOT NULL DEFAULT FALSE" if engine.dialect.name == "postgresql" else "BOOLEAN NOT NULL DEFAULT 0"
    timestamp_type = "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "DATETIME"
    additions = {
        "video_url": "VARCHAR(500)",
        "image_latitude": "FLOAT",
        "image_longitude": "FLOAT",
        "report_status": "VARCHAR(32) NOT NULL DEFAULT 'OPEN'",
        "is_important": bool_default,
        "important_marked_at": timestamp_type,
        "closed_at": timestamp_type,
    }
    with engine.begin() as connection:
        for name, definition in additions.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE citizen_reports ADD COLUMN {name} {definition}"))


def _seed_dummy_citizen_reports() -> None:
    """Seed a few demo reports so the portal has DB-backed records during development."""
    from app.db.session import SessionLocal

    demo_source = "demo-citizen-feed-v1"
    with SessionLocal() as db:
        existing = db.scalar(select(func.count()).select_from(CitizenReport).where(CitizenReport.source == demo_source)) or 0
        if existing:
            return

        now = datetime.now(timezone.utc)
        reports = [
            CitizenReport(
                location_id="JHG_001",
                latitude=31.2681,
                longitude=72.3187,
                description="Water is crossing a low road near Jhang city. Traffic is slowing and residents are requesting field verification.",
                image_url="https://example.com/reports/jhang-road-water.jpg",
                video_url=None,
                image_latitude=None,
                image_longitude=None,
                reported_water_depth_cm=22,
                source=demo_source,
                report_status="OPEN",
                verification_status=VerificationStatus.PENDING.value,
                timestamp=now - timedelta(seconds=35),
            ),
            CitizenReport(
                location_id="MUL_001",
                latitude=30.1575,
                longitude=71.5249,
                description="Citizen reports rising water close to a settlement near the Chenab reach. No evacuation requested yet.",
                image_url=None,
                video_url="https://example.com/reports/multan-chenab-video.mp4",
                image_latitude=None,
                image_longitude=None,
                reported_water_depth_cm=14,
                source=demo_source,
                report_status="OPEN",
                verification_status=VerificationStatus.PENDING.value,
                timestamp=now - timedelta(minutes=7),
            ),
            CitizenReport(
                location_id="RWP_001",
                latitude=33.5651,
                longitude=73.0169,
                description="Blocked drainage channel reported after rainfall. Field team should inspect before evening peak traffic.",
                image_url="https://example.com/reports/rawalpindi-drainage.jpg",
                video_url=None,
                image_latitude=33.5651,
                image_longitude=73.0169,
                reported_water_depth_cm=None,
                source=demo_source,
                report_status="OPEN",
                verification_status=VerificationStatus.PENDING.value,
                is_important=True,
                important_marked_at=now - timedelta(minutes=3),
                timestamp=now - timedelta(minutes=19),
            ),
        ]
        db.add_all(reports)
        db.commit()


def _seed_dummy_model_forecasts() -> None:
    """Seed graph-ready dummy forecast series until trained models write rows."""
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        existing = db.scalar(select(func.count()).select_from(ModelForecastPoint)) or 0
        if existing:
            return
        issued_at = datetime.now(timezone.utc)
        db.add_all(build_dummy_model_forecasts(issued_at))
        db.commit()
