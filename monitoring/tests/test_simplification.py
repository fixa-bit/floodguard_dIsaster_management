import sqlite3
from contextlib import closing

import pytest
from sqlalchemy import inspect

from monitoring.database import create_monitoring_engine
from monitoring.migrations.runner import upgrade


def test_migration_preserves_station_api_model_timestamp_values(tmp_path):
    path = tmp_path / "old.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript("""
            PRAGMA user_version=3;
            CREATE TABLE locations(id INTEGER,code TEXT,name TEXT,river TEXT,meta TEXT);
            CREATE TABLE variables(id INTEGER,code TEXT,unit TEXT);
            CREATE TABLE sources(id INTEGER,code TEXT,kind TEXT);
            CREATE TABLE observations(location_id INTEGER,variable_id INTEGER,source_id INTEGER,
                observed_at TEXT,revision INTEGER,value REAL,ingested_at TEXT,raw TEXT);
            CREATE TABLE models(id INTEGER,name TEXT,version TEXT);
            CREATE TABLE forecast_runs(id INTEGER,model_id INTEGER,issued_at TEXT,
                started_at TEXT,finished_at TEXT);
            CREATE TABLE forecast_values(run_id INTEGER,location_id INTEGER,variable_id INTEGER,
                valid_at TEXT,member TEXT,value REAL,p25 REAL,p75 REAL);
            INSERT INTO locations VALUES(1,'TEST','Test station','Indus','{"latitude":30,"longitude":70}');
            INSERT INTO variables VALUES(1,'river_discharge','m3/s');
            INSERT INTO sources VALUES(1,'FFD','agency');
            INSERT INTO observations VALUES(1,1,1,'2026-10-11 07:00:00',1,123,'2026-10-11 07:01:00','{}');
            INSERT INTO models VALUES(1,'Test Model','v1');
            INSERT INTO forecast_runs VALUES(1,1,'2026-10-11 00:00:00',NULL,NULL);
            INSERT INTO forecast_values VALUES(1,1,1,'2026-10-12 00:00:00','deterministic',456,400,500);
            INSERT INTO forecast_values VALUES(1,1,1,'2026-10-12 00:00:00','member-01',460,NULL,NULL);
        """)
    engine = create_monitoring_engine(f"sqlite:///{path.as_posix()}")
    try:
        backup = upgrade(engine)
        assert backup.exists()
        assert set(inspect(engine).get_table_names()) == {"stations", "providers", "station_values", "thresholds"}
        with closing(sqlite3.connect(path)) as db:
            assert db.execute("SELECT COUNT(*) FROM station_values").fetchone()[0] == 3
            assert db.execute("SELECT value,unit,value_type FROM station_values ORDER BY id").fetchall() == [
                (123, "m3/s", "observed"), (456, "m3/s", "forecast"), (460, "m3/s", "forecast")]
            assert db.execute("SELECT model_version FROM providers WHERE code='MODEL:1'").fetchone()[0] == "v1"
            assert db.execute("SELECT latitude,longitude FROM stations").fetchone() == (30,70)
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        with closing(sqlite3.connect(backup)) as db:
            assert db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
        assert upgrade(engine) is None
    finally:
        engine.dispose()


def test_unrelated_database_not_changed(tmp_path):
    path = tmp_path / "other.db"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE portal_data(id INTEGER)")
    engine = create_monitoring_engine(f"sqlite:///{path.as_posix()}")
    try:
        with pytest.raises(ValueError, match="refusing"):
            upgrade(engine)
        assert inspect(engine).get_table_names() == ["portal_data"]
    finally:
        engine.dispose()
