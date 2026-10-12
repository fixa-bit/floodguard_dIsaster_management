from sqlalchemy import select, text

from monitoring.database import create_monitoring_engine, session_factory
from monitoring.migrations.v004_station_values import create_schema
from monitoring.migrations.runner import upgrade
from monitoring.models import Provider, Station, StationValue
from monitoring.repository import store_value


def test_additive_upgrade_preserves_existing_values(tmp_path):
    engine = create_monitoring_engine(f"sqlite:///{(tmp_path / 'v4.db').as_posix()}")
    try:
        create_schema(engine)
        factory = session_factory(engine)
        with factory.begin() as session:
            session.add(Station(code="TEST", name="Test station"))
            session.add(Provider(code="FFD", name="FFD", kind="api"))
            store_value(session, station="TEST", provider="FFD", measurement="discharge_inflow",
                        value=123, unit="cusecs", value_type="observed", value_at="2026-10-11T00:00:00Z")
        assert upgrade(engine) is None
        assert upgrade(engine) is None
        with factory() as session:
            assert session.scalar(select(StationValue)).value == 123
        with engine.connect() as connection:
            assert connection.execute(text("PRAGMA user_version")).scalar() == 5
            assert connection.execute(text("SELECT count(*) FROM thresholds")).scalar() == 0
            assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    finally:
        engine.dispose()
