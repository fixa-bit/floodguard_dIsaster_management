import json

import pytest
from sqlalchemy import inspect, select

from monitoring.database import create_monitoring_engine, session_factory
from monitoring.migrations.runner import upgrade
from monitoring.models import Provider, StationValue
from monitoring.seed import seed
from monitoring.simulation import build_records, load_scenarios, store_scenarios


@pytest.fixture
def storage(tmp_path):
    engine = create_monitoring_engine(f"sqlite:///{(tmp_path / 'simulation.db').as_posix()}")
    upgrade(engine)
    factory = session_factory(engine)
    with factory.begin() as session:
        seed(session)
    yield engine, factory
    engine.dispose()


def scenario(**changes):
    result = {
        "name": "taunsa danger surge",
        "start_at": "2026-10-12T00:00:00Z",
        "interval_minutes": 60,
        "uncertainty_ratio": 0.1,
        "series": [
            {
                "station": "TAUNSA",
                "measurement": "discharge_inflow",
                "unit": "cusecs",
                "baseline_value": 120000,
                "peak_value": 650000,
                "recovery_value": 180000,
                "rise_steps": 3,
                "hold_steps": 1,
                "recession_steps": 2,
            },
            {
                "station": "TAUNSA",
                "measurement": "water_level",
                "unit": "m",
                "level_reference": "synthetic gauge datum",
                "baseline_value": 3.2,
                "peak_value": 8.1,
                "recovery_value": 4.0,
                "rise_steps": 3,
                "hold_steps": 1,
                "recession_steps": 2,
            },
        ],
    }
    result.update(changes)
    return result


def test_flow_simulation_writes_original_station_value_schema(storage):
    engine, factory = storage
    with factory.begin() as session:
        result = store_scenarios(session, scenario())
        assert result.scenarios == 1
        assert result.records == 12
        assert result.inserted == 12
        assert result.provider_codes == ("SIMULATED_FLOW_TAUNSA_DANGER_SURGE",)

    assert set(inspect(engine).get_table_names()) == {"stations", "providers", "station_values", "thresholds"}
    with factory() as session:
        provider = session.scalar(select(Provider).where(Provider.code == "SIMULATED_FLOW_TAUNSA_DANGER_SURGE"))
        values = list(session.scalars(select(StationValue).where(StationValue.provider_id == provider.id)))
        first_flow = session.scalar(select(StationValue).where(
            StationValue.provider_id == provider.id,
            StationValue.measurement == "discharge_inflow",
        ).order_by(StationValue.value_at))
        assert provider.kind == "import"
        assert provider.name == "Simulated flow - taunsa danger surge"
        assert {row.value_type for row in values} == {"simulated"}
        assert {row.measurement for row in values} == {"discharge_inflow", "water_level"}
        assert all(row.forecast_issued_at is None for row in values)
        assert first_flow.value == 120000
        assert first_flow.p25 == 108000
        assert first_flow.p75 == 132000


def test_flow_simulation_is_idempotent_for_same_scenario(storage):
    _, factory = storage
    with factory.begin() as session:
        assert store_scenarios(session, scenario()).inserted == 12
    with factory.begin() as session:
        assert store_scenarios(session, scenario()).inserted == 0


def test_explicit_step_values_can_create_custom_testing_shape(storage):
    _, factory = storage
    custom = scenario(
        name="marala sharp pulse",
        series=[{
            "station": "MARALA",
            "measurement": "discharge_inflow",
            "unit": "cusecs",
            "step_values": [70000, 110000, 260000, 90000],
            "p25_offset": 5000,
            "p75_offset": 7000,
        }],
    )
    records = build_records(custom)
    assert [record["value"] for record in records] == [70000, 110000, 260000, 90000]
    assert records[2]["p25"] == 255000 and records[2]["p75"] == 267000
    with factory.begin() as session:
        assert store_scenarios(session, custom).inserted == 4


def test_water_level_simulation_requires_reference(storage):
    _, factory = storage
    bad = scenario(series=[{
        "station": "TAUNSA",
        "measurement": "water_level",
        "unit": "m",
        "baseline_value": 3.2,
        "peak_value": 8.1,
    }])
    with factory.begin() as session, pytest.raises(ValueError, match="level_reference"):
        store_scenarios(session, bad)


def test_load_scenarios_accepts_single_object_or_array(tmp_path):
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario()), encoding="utf-8")
    assert len(load_scenarios(path)) == 1
    path.write_text(json.dumps([scenario(), scenario(name="second")]), encoding="utf-8")
    assert len(load_scenarios(path)) == 2
