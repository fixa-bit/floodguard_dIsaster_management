import sqlite3
from contextlib import closing
from functools import partial
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from monitoring.database import create_monitoring_engine, session_factory
from monitoring.migrations.runner import upgrade
from monitoring.seed import seed
from monitoring.viewer import Handler, connect, records, schema


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "monitoring.db"
    engine = create_monitoring_engine(f"sqlite:///{path.as_posix()}")
    upgrade(engine)
    with session_factory(engine).begin() as session:
        seed(session)
    engine.dispose()
    return path


def test_schema_and_placeholder_values(database):
    result = schema(database)
    assert result["readOnly"] and len(result["tables"]) == 4
    values = next(table for table in result["tables"] if table["name"] == "station_values")
    assert values["count"] == 0 and len(values["relationships"]) == 2
    result = records(database, "stations", size=25)
    assert result["total"] == 24
    assert records(database, "providers")["rows"][0]["model_version"] is None


def test_read_only_unknown_table_and_parameter_validation(database):
    with closing(connect(database)) as connection, pytest.raises(sqlite3.OperationalError):
        connection.execute("DELETE FROM stations")
    for table in ['stations; DROP TABLE stations', 'sqlite_master', 'missing']:
        with pytest.raises(ValueError):
            records(database, table)
    with pytest.raises(ValueError):
        records(database, "stations", size=100000)
    assert records(database, "stations", search="' OR 1=1 --")["total"] == 0


def test_loopback_http_routes(database):
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, database=database))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base + "/api/schema") as response:
            assert response.status == 200
        with urlopen(base + "/") as response:
            assert b"Stored Station Data" in response.read()
        with urlopen(base + "/diagram.js") as response:
            assert response.status == 200 and b"createDiagram" in response.read()
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base + "/api/schema", headers={"Host": "attacker.example"}))
        assert error.value.code == 403
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base + "/api/schema", method="POST"))
        assert error.value.code == 501
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_raw_storage_columns_json_boolean_null_and_order(database):
    with closing(sqlite3.connect(database)) as connection:
        fields = [row[1] for row in connection.execute('PRAGMA table_info("stations")')]
        expected = connection.execute('SELECT * FROM stations ORDER BY id LIMIT 1').fetchone()
    result = records(database, "stations", raw=True)
    assert result["columns"] == fields
    assert list(result["rows"][0]) == fields
    assert list(result["rows"][0].values()) == [None if value is None else str(value) for value in expected]
    assert records(database, "providers", raw=True)["rows"][0]["model_version"] is None
    assert records(database, "stations", raw=True, order="rowid")["orderBy"] == "rowid"
    with pytest.raises(ValueError):
        records(database, "stations", raw=True, order="id; DROP TABLE stations")
    with closing(sqlite3.connect(database)) as connection:
        expected_order = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid")]
    assert schema(database)["schemaOrder"] == expected_order


def test_raw_empty_tables_have_columns(database):
    result = records(database, "station_values", raw=True)
    assert result["rows"] == []
    assert "value_at" in result["columns"] and "provider_id" in result["columns"]


def test_normal_values_show_station_and_provider_names(database):
    from monitoring.repository import store_value
    engine = create_monitoring_engine(f"sqlite:///{database.as_posix()}")
    try:
        with session_factory(engine).begin() as session:
            store_value(session, station="TAUNSA", provider="GLOFAS", measurement="river_discharge",
                        value=123, unit="m3/s", value_type="forecast", value_at="2026-10-12T00:00:00Z")
        result = records(database, "station_values", search="TAUNSA")
        assert result["total"] == 1 and "TAUNSA" in result["rows"][0]["station"]
        assert "GLOFAS" in result["rows"][0]["provider"]
        assert "station_id" not in result["columns"]
        assert "station_id" in records(database, "station_values", raw=True)["columns"]
    finally:
        engine.dispose()


def test_planned_providers_and_station_thresholds_are_visible(database):
    planned = records(database, "providers", search="planned")
    assert planned["total"] == 6
    assert all(row["model_version"] is None and row["kind"] == "model" for row in planned["rows"])
    limits = records(database, "thresholds", search="TAUNSA")
    assert limits["total"] == 6
    assert all("TAUNSA" in row["station"] and row["value"] is None and row["provider"] is None
               for row in limits["rows"])
    raw = records(database, "thresholds", raw=True)
    assert "station_id" in raw["columns"] and "provider_id" in raw["columns"]
    assert raw["rows"][0]["value"] is None
