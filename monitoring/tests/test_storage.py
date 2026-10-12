import json

import pytest
from sqlalchemy import func, inspect, select

from monitoring.cli import import_values
from monitoring.database import create_monitoring_engine, session_factory
from monitoring.migrations.runner import upgrade
from monitoring.models import Provider, Station, StationValue, Threshold
from monitoring.repository import store_value
from monitoring.seed import seed


@pytest.fixture
def storage(tmp_path):
    engine = create_monitoring_engine(f"sqlite:///{(tmp_path / 'store.db').as_posix()}")
    upgrade(engine)
    factory = session_factory(engine)
    with factory.begin() as session:
        seed(session)
        session.add(Provider(code="MODEL_A", name="River Model", kind="model", model_version="1"))
        session.add(Provider(code="MODEL_B", name="River Model", kind="model", model_version="2"))
    yield engine, factory
    engine.dispose()


def item(**changes):
    result = dict(station="TAUNSA", provider="GLOFAS", measurement="river_discharge",
                  value=1200, unit="m3/s", value_type="forecast", value_at="2026-10-12T00:00:00Z",
                  forecast_issued_at="2026-10-11T00:00:00Z")
    result.update(changes)
    return result


def test_only_four_tables_and_no_monitoring_fields(storage):
    engine, factory = storage
    assert set(inspect(engine).get_table_names()) == {"stations", "providers", "station_values", "thresholds"}
    assert inspect(engine).get_view_names() == []
    assert all("status" not in column["name"] and "poll" not in column["name"]
               for table in inspect(engine).get_table_names() for column in inspect(engine).get_columns(table))
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Station)) == 24
        assert session.scalar(select(func.count()).select_from(StationValue)) == 0


def test_models_stations_and_issue_times_remain_separate(storage):
    _, factory = storage
    with factory.begin() as session:
        for provider in ["GLOFAS", "MODEL_A", "MODEL_B"]:
            for station in ["TAUNSA", "MARALA"]:
                for issue in ["2026-10-10T00:00:00Z", "2026-10-11T00:00:00Z"]:
                    store_value(session, **item(provider=provider, station=station, forecast_issued_at=issue))
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(StationValue)) == 12


def test_native_units_values_timestamps_and_idempotence(storage):
    _, factory = storage
    with factory.begin() as session:
        row, inserted = store_value(session, **item(provider="FFD", value_type="observed",
                                   forecast_issued_at=None, value_at="2026-10-11T12:00:00+05:00",
                                   measurement="discharge_inflow", value=84000, unit="cusecs"))
        assert inserted and row.value == 84000 and row.unit == "cusecs"
        assert row.value_at.hour == 7
        assert store_value(session, **item())[1]
        assert not store_value(session, **item())[1]
        assert store_value(session, **item(value=1250))[1]  # Preserve corrected output as a new capture.
        assert store_value(session, **item(measurement="discharge_outflow"))[1]


@pytest.mark.parametrize("change", [
    {"value": float("nan")}, {"value": float("inf")}, {"value": True},
    {"provider": "MISSING"}, {"station": "MISSING"}, {"value_type": "alarm"},
    {"value_at": "2026-10-12T00:00:00"}, {"measurement": ""}, {"unit": ""},
    {"p25": 1300, "p75": 1100}, {"measurement": "water_level"},
    {"provider": "MODEL_A", "value_type": "observed", "forecast_issued_at": None},
])
def test_bad_or_mislabelled_values_rejected(storage, change):
    _, factory = storage
    with factory.begin() as session, pytest.raises(ValueError):
        store_value(session, **item(**change))


def test_level_reference_and_api_simulated_history(storage):
    _, factory = storage
    with factory.begin() as session:
        row, _ = store_value(session, **item(measurement="water_level", value=7.4, unit="m",
                                             level_reference="mMSL"))
        assert row.level_reference == "mMSL"
        row, _ = store_value(session, **item(value_type="simulated", forecast_issued_at=None,
                                             value_at="2026-10-10T00:00:00Z"))
        assert row.value_type == "simulated"


def test_import_atomicity(storage, tmp_path):
    _, factory = storage
    path = tmp_path / "values.json"
    path.write_text(json.dumps([item()]), encoding="utf-8")
    assert import_values(factory, path) == 1
    assert import_values(factory, path) == 0
    path.write_text(json.dumps([item(value=1400), item(station="UNKNOWN")]), encoding="utf-8")
    with pytest.raises(ValueError):
        import_values(factory, path)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(StationValue)) == 1


def test_planned_models_are_not_trained_outputs(storage):
    _, factory = storage
    with factory.begin() as session:
        planned = list(session.scalars(select(Provider).where(Provider.code.like("PLANNED_%"))))
        assert len(planned) == 6
        assert all(row.kind == "model" and row.model_version is None and "(planned)" in row.name for row in planned)
        with pytest.raises(ValueError, match="no trained version"):
            store_value(session, **item(provider=planned[0].code))


def test_threshold_slots_are_unknown_and_seed_preserves_configured_data(storage):
    _, factory = storage
    with factory.begin() as session:
        limits = list(session.scalars(select(Threshold)))
        assert len(limits) == 144
        assert all(row.value is None and row.provider_id is None and row.source_reference is None
                   and row.level_reference is None for row in limits)
        assert {row.measurement for row in limits} == {"discharge_inflow", "discharge_outflow", "water_level"}
        # Synthetic test-only value: never seeded into the real database.
        limits[0].value = 123
        limits[0].provider_id = session.scalar(select(Provider.id).where(Provider.code == "FFD"))
        limits[0].source_reference = "Synthetic test bulletin"
        seed(session)
        assert session.scalar(select(func.count()).select_from(Threshold)) == 144
        assert limits[0].value == 123 and limits[0].source_reference == "Synthetic test bulletin"
