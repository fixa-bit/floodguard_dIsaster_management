"""A three-table station data store; previous metadata is retained in a backup."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import inspect, text

from ..database import Base, create_monitoring_engine
from .. import models


TABLES = {"stations", "providers", "station_values"}
LEGACY = {"locations", "variables", "sources", "observations", "models", "forecast_runs", "forecast_values"}


def create_schema(engine):
    with engine.begin() as connection:
        Base.metadata.create_all(connection, tables=[Base.metadata.tables[name] for name in sorted(TABLES)])
        if engine.dialect.name == "sqlite":
            connection.execute(text("PRAGMA user_version=4"))


def migrate_sqlite(engine):
    path = Path(engine.url.database).resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = path.with_name(f"{path.stem}.previous-design-{stamp}.db")
    staged = path.with_name(f"{path.stem}.station-staging-{stamp}.db")
    engine.dispose()
    with closing(sqlite3.connect(path)) as original:
        if original.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]:
            raise ValueError("Database is busy; stop collectors and viewer before migrating")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as source, closing(sqlite3.connect(backup)) as copy:
        source.backup(copy)
    staged_engine = create_monitoring_engine(f"sqlite:///{staged.as_posix()}")
    try:
        create_schema(staged_engine)
    finally:
        staged_engine.dispose()
    with closing(sqlite3.connect(backup)) as source, closing(sqlite3.connect(staged)) as target:
        source.row_factory = sqlite3.Row
        target.execute("PRAGMA foreign_keys=ON")
        variables = {row["id"]: (row["code"], row["unit"]) for row in source.execute("SELECT * FROM variables")}
        runs = {row["id"]: dict(row) for row in source.execute("SELECT * FROM forecast_runs")}
        model_providers = {}
        with target:
            for row in source.execute("SELECT * FROM locations"):
                metadata = json.loads(row["meta"] or "{}")
                target.execute("INSERT INTO stations VALUES(?,?,?,?,?,?)",
                               (row["id"], row["code"], row["name"], row["river"],
                                metadata.get("latitude"), metadata.get("longitude")))
            for row in source.execute("SELECT * FROM sources"):
                kind = "model" if row["kind"] == "model" else "import" if row["kind"] == "manual" else "api"
                if row["code"] in {"GLOFAS", "GEOGLOWS"}:
                    kind = "api"
                target.execute("INSERT INTO providers VALUES(?,?,?,?,?)", (row["id"], row["code"], row["code"], kind, None))
            for row in source.execute("SELECT * FROM models"):
                code = f"MODEL:{row['id']}"
                while target.execute("SELECT 1 FROM providers WHERE code=?", (code,)).fetchone():
                    code += ":legacy"
                cursor = target.execute("INSERT INTO providers(code,name,kind,model_version) VALUES(?,?,?,?)",
                                        (code, row["name"], "model", row["version"]))
                model_providers[row["id"]] = cursor.lastrowid
            statement = """INSERT INTO station_values(station_id,provider_id,measurement,value,unit,
                           value_type,value_at,forecast_issued_at,stored_at,p25,p75,level_reference)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"""
            for row in source.execute("SELECT * FROM observations ORDER BY observed_at,revision"):
                measurement, unit = variables[row["variable_id"]]
                raw = json.loads(row["raw"] or "{}")
                source_kind = source.execute("SELECT kind FROM sources WHERE id=?", (row["source_id"],)).fetchone()[0]
                target.execute(statement, (row["location_id"], row["source_id"], measurement, row["value"], unit,
                                           "simulated" if source_kind == "model" else "observed", row["observed_at"],
                                           None, row["ingested_at"], None, None, raw.get("datum")))
            member_providers = {}
            for row in source.execute("SELECT * FROM forecast_values"):
                run = runs[row["run_id"]]
                measurement, unit = variables[row["variable_id"]]
                provider_id = model_providers[run["model_id"]]
                # Legacy ensemble outputs remain distinguishable without adding a member column.
                if row["member"] != "deterministic":
                    key = (provider_id, row["member"])
                    if key not in member_providers:
                        provider = target.execute("SELECT name,model_version FROM providers WHERE id=?", (provider_id,)).fetchone()
                        cursor = target.execute("INSERT INTO providers(code,name,kind,model_version) VALUES(?,?,?,?)",
                                                (f"MEMBER:{provider_id}:{row['member']}", f"{provider[0]} / {row['member']}", "model", provider[1]))
                        member_providers[key] = cursor.lastrowid
                    provider_id = member_providers[key]
                stored = run["finished_at"] or run["started_at"] or run["issued_at"]
                target.execute(statement, (row["location_id"], provider_id, measurement, row["value"], unit,
                                           "forecast", row["valid_at"], run["issued_at"], stored,
                                           row["p25"], row["p75"], None))
            expected = source.execute("SELECT COUNT(*) FROM observations").fetchone()[0] + source.execute("SELECT COUNT(*) FROM forecast_values").fetchone()[0]
            if target.execute("SELECT COUNT(*) FROM station_values").fetchone()[0] != expected:
                raise ValueError("Migration value count mismatch")
            if target.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("Migration foreign-key validation failed")
        target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    staged.replace(path)
    return backup


def upgrade(engine):
    tables = set(inspect(engine).get_table_names())
    if not tables:
        create_schema(engine)
        return None
    if tables == TABLES:
        return None
    if tables != LEGACY:
        raise ValueError("Unrecognized database; refusing to modify it")
    if engine.dialect.name != "sqlite":
        raise ValueError("Legacy PostgreSQL conversion needs a separate backup/export plan")
    with engine.connect() as connection:
        if connection.execute(text("PRAGMA user_version")).scalar() != 3:
            raise ValueError("Not the previous station monitoring schema")
    return migrate_sqlite(engine)
