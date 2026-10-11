from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text

from app.db.init_db import init_db
from app.models.flood_data_layer import (
    FloodLocation,
    FloodVariable,
    ForecastModelRegistry,
    ForecastRun,
    ForecastValue,
    Threshold,
)


def test_flood_data_layer_seed_is_idempotent(db_session):
    init_db()
    init_db()

    variable_count = db_session.scalar(select(func.count()).select_from(FloodVariable))
    station_count = db_session.scalar(select(func.count()).select_from(FloodLocation).where(FloodLocation.kind.in_(["station", "barrage", "dam"])))
    planned_count = db_session.scalar(select(func.count()).select_from(ForecastModelRegistry).where(ForecastModelRegistry.status == "planned"))
    null_threshold_count = db_session.scalar(select(func.count()).select_from(Threshold).where(Threshold.value.is_(None)))

    assert variable_count == 10
    assert station_count == 8
    assert planned_count == 6
    assert null_threshold_count == 40


def test_latest_forecast_uses_newest_complete_run_and_keeps_old_values(db_session):
    init_db()

    model = db_session.scalar(select(ForecastModelRegistry).where(ForecastModelRegistry.name == "baseline_persistence"))
    location = db_session.scalar(select(FloodLocation).where(FloodLocation.code == "TARBELA"))
    variable = db_session.scalar(select(FloodVariable).where(FloodVariable.code == "discharge"))
    issued_at = datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)

    first_run = ForecastRun(model_id=model.id, issued_at=issued_at, status="complete", started_at=issued_at, finished_at=issued_at)
    second_run = ForecastRun(
        model_id=model.id,
        issued_at=issued_at + timedelta(hours=1),
        status="complete",
        started_at=issued_at + timedelta(hours=1),
        finished_at=issued_at + timedelta(hours=1),
    )
    running_run = ForecastRun(model_id=model.id, issued_at=issued_at + timedelta(hours=2), status="running", started_at=issued_at + timedelta(hours=2))
    db_session.add_all([first_run, second_run, running_run])
    db_session.flush()

    valid_at = issued_at + timedelta(hours=6)
    db_session.add_all(
        [
            ForecastValue(run_id=first_run.id, location_id=location.id, variable_id=variable.id, valid_at=valid_at, value=100.0),
            ForecastValue(run_id=second_run.id, location_id=location.id, variable_id=variable.id, valid_at=valid_at, value=125.0),
            ForecastValue(run_id=running_run.id, location_id=location.id, variable_id=variable.id, valid_at=valid_at, value=999.0),
        ]
    )
    db_session.commit()

    latest = db_session.execute(
        text(
            """
            SELECT run_id, value
            FROM latest_forecast
            WHERE model_id = :model_id AND location_id = :location_id AND variable_id = :variable_id
            """
        ),
        {"model_id": model.id, "location_id": location.id, "variable_id": variable.id},
    ).mappings().one()

    old_value = db_session.scalar(select(ForecastValue.value).where(ForecastValue.run_id == first_run.id))

    assert latest["run_id"] == second_run.id
    assert latest["value"] == 125.0
    assert old_value == 100.0
