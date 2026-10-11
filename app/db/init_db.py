from datetime import datetime, timedelta, timezone

from app.db.base import Base
from sqlalchemy import func, inspect, select, text

from app.core.enums import VerificationStatus
from app.db.session import engine
from app.models.citizen_report import CitizenReport
from app.models.flood_data_layer import (
    DataRetentionPolicy,
    FloodLocation,
    FloodSource,
    FloodVariable,
    ForecastModelRegistry,
    ModelCoverage,
    RecordValue,
    Threshold,
)
from app.models.model_forecast import ModelForecastPoint
from app.models import river_gauge_observation
from app.models import station_observation
from app.models import citizen_report, district_risk_snapshot, flood_data_layer, incident, model_forecast, prediction, system_event, system_state, upstream_forecast_snapshot
from app.simulation.model_forecasts import build_dummy_model_forecasts


def init_db() -> None:
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    Base.metadata.create_all(bind=engine)
    _migrate_prediction_columns()
    _migrate_citizen_report_columns()
    _seed_flood_data_layer()
    _create_flood_data_views()
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


def _seed_flood_data_layer() -> None:
    """Seed registry rows only; operational thresholds remain NULL until official values arrive."""
    from app.db.session import SessionLocal

    variables = [
        ("discharge", "m3/s", "River discharge"),
        ("stage", "m", "River stage"),
        ("rainfall", "mm", "Rainfall accumulation"),
        ("reservoir_level", "ft", "Reservoir level"),
        ("reservoir_inflow", "m3/s", "Reservoir inflow"),
        ("reservoir_outflow", "m3/s", "Reservoir outflow"),
        ("tide_level", "m", "Tide level"),
        ("soil_moisture", "fraction", "Soil moisture fraction"),
        ("temperature", "C", "Air temperature"),
        ("snowmelt", "mm", "Snowmelt equivalent"),
    ]
    sources = [
        ("irsa", "agency"),
        ("open_meteo_flood", "external"),
        ("open_meteo_weather", "external"),
        ("pmd", "agency"),
        ("wapda", "agency"),
        ("glofas_cds", "external"),
        ("manual", "manual"),
        ("citizen", "citizen"),
    ]
    basins = [
        ("BASIN_INDUS", "Indus", "Indus"),
        ("BASIN_KABUL", "Kabul", "Kabul"),
        ("BASIN_JHELUM", "Jhelum", "Jhelum"),
        ("BASIN_CHENAB", "Chenab", "Chenab"),
        ("BASIN_RAVI", "Ravi", "Ravi"),
        ("BASIN_SUTLEJ", "Sutlej", "Sutlej"),
    ]
    stations = [
        ("TARBELA", "Tarbela", "dam", "Indus", "BASIN_INDUS", 34.088, 72.698),
        ("MANGLA", "Mangla", "dam", "Jhelum", "BASIN_JHELUM", 33.142, 73.645),
        ("KALABAGH", "Kalabagh", "barrage", "Indus", "BASIN_INDUS", 32.963, 71.548),
        ("TAUNSA", "Taunsa", "barrage", "Indus", "BASIN_INDUS", 30.704, 70.842),
        ("GUDDU", "Guddu", "barrage", "Indus", "BASIN_INDUS", 28.432, 69.708),
        ("SUKKUR", "Sukkur", "barrage", "Indus", "BASIN_INDUS", 27.692, 68.858),
        ("NOWSHERA_KABUL", "Nowshera (Kabul)", "station", "Kabul", "BASIN_KABUL", 34.015, 71.974),
        ("MARALA_CHENAB", "Marala (Chenab)", "barrage", "Chenab", "BASIN_CHENAB", 32.672, 74.466),
    ]
    models = [
        ("glofas_v4", "v4", "riverine", "medium", "external", "active", "Open-Meteo Flood API wrapper for GloFAS v4."),
        ("riverine_ml_short", "planned", "riverine", "short", "ml", "planned", "TODO: implement short-range riverine ML adapter."),
        ("riverine_ml_long", "planned", "riverine", "long", "ml", "planned", "TODO: implement long-range riverine ML adapter."),
        ("flash_flood_nowcast", "planned", "flash_flood", "nowcast", "ml", "planned", "TODO: implement flash-flood nowcast adapter."),
        ("coastal_surge_tide", "planned", "coastal", "short", "physical", "planned", "TODO: implement coastal surge/tide adapter."),
        ("glof_watch", "planned", "glof", "medium", "physical", "planned", "TODO: implement GLOF watch adapter."),
        ("urban_flood_rain", "planned", "urban", "short", "ml", "planned", "TODO: implement urban flood rainfall adapter."),
        ("baseline_persistence", "v1", "riverine", "short", "baseline", "active", "Persistence benchmark computed from latest observations."),
    ]

    with SessionLocal() as db:
        for code, unit, description in variables:
            if not db.scalar(select(FloodVariable).where(FloodVariable.code == code)):
                db.add(FloodVariable(code=code, unit=unit, description=description))

        for code, kind in sources:
            if not db.scalar(select(FloodSource).where(FloodSource.code == code)):
                db.add(FloodSource(code=code, kind=kind, meta={}))

        db.flush()
        for code, name, river in basins:
            if not db.scalar(select(FloodLocation).where(FloodLocation.code == code)):
                db.add(
                    FloodLocation(
                        code=code,
                        name=name,
                        kind="basin",
                        river=river,
                        meta={"todo": "Tune basin geometry from official hydrologic boundary."},
                    )
                )

        db.flush()
        basin_ids = {location.code: location.id for location in db.scalars(select(FloodLocation)).all()}
        for code, name, kind, river, parent_code, lat, lon in stations:
            if not db.scalar(select(FloodLocation).where(FloodLocation.code == code)):
                db.add(
                    FloodLocation(
                        code=code,
                        name=name,
                        kind=kind,
                        river=river,
                        parent_id=basin_ids.get(parent_code),
                        geom=f"POINT({lon} {lat})",
                        glofas_lat=lat,
                        glofas_lon=lon,
                        meta={"todo": "Tune GloFAS point to nearest river cell and replace approximate coordinates if needed."},
                    )
                )

        for name, version, hazard, horizon, kind, status, notes in models:
            if not db.scalar(select(ForecastModelRegistry).where(ForecastModelRegistry.name == name, ForecastModelRegistry.version == version)):
                db.add(
                    ForecastModelRegistry(
                        name=name,
                        version=version,
                        hazard=hazard,
                        horizon=horizon,
                        kind=kind,
                        status=status,
                        artifact_uri=None,
                        input_spec={},
                        output_spec={},
                        training={},
                        metrics={},
                        owner="FloodGuard AI",
                        notes=notes,
                    )
                )

        db.flush()
        discharge = db.scalar(select(FloodVariable).where(FloodVariable.code == "discharge"))
        station_rows = db.scalars(select(FloodLocation).where(FloodLocation.kind.in_(["station", "barrage", "dam"]))).all()
        active_models = db.scalars(select(ForecastModelRegistry).where(ForecastModelRegistry.name.in_(["glofas_v4", "baseline_persistence"]))).all()
        if discharge:
            for location in station_rows:
                if not db.scalar(select(RecordValue).where(RecordValue.location_id == location.id, RecordValue.variable_id == discharge.id)):
                    db.add(
                        RecordValue(
                            location_id=location.id,
                            variable_id=discharge.id,
                            value=None,
                            occurred_on=None,
                            source="TODO: official highest recorded value from FFD/WAPDA",
                        )
                    )
                for level, name in [(1, "watch"), (2, "warning"), (3, "flood"), (4, "severe"), (5, "extreme")]:
                    existing = db.scalar(
                        select(Threshold).where(
                            Threshold.location_id == location.id,
                            Threshold.variable_id == discharge.id,
                            Threshold.hazard == "riverine",
                            Threshold.level == level,
                        )
                    )
                    if not existing:
                        db.add(
                            Threshold(
                                location_id=location.id,
                                variable_id=discharge.id,
                                hazard="riverine",
                                level=level,
                                name=name,
                                value=None,
                                source="TODO: official FFD/WAPDA threshold",
                                meta={"todo": "Replace NULL with official threshold before alerting."},
                            )
                        )
                for model in active_models:
                    if not db.scalar(
                        select(ModelCoverage).where(
                            ModelCoverage.model_id == model.id,
                            ModelCoverage.location_id == location.id,
                            ModelCoverage.variable_id == discharge.id,
                        )
                    ):
                        db.add(ModelCoverage(model_id=model.id, location_id=location.id, variable_id=discharge.id))

        for dataset, policy, config in [
            ("observations", "Keep observations forever.", {"retention": "forever"}),
            (
                "forecast_values",
                "Keep forecast values for 2 years for non-active models and 5 years for active models; no hard deletion is performed by this task.",
                {"non_active_years": 2, "active_years": 5, "hard_delete_enabled": False},
            ),
        ]:
            if not db.scalar(select(DataRetentionPolicy).where(DataRetentionPolicy.dataset == dataset)):
                db.add(DataRetentionPolicy(dataset=dataset, policy=policy, config=config))

        db.commit()


def _create_flood_data_views() -> None:
    dialect = engine.dialect.name
    create_prefix = "CREATE OR REPLACE VIEW" if dialect == "postgresql" else "CREATE VIEW"
    source_priority = "case s.code when 'manual' then 1 when 'irsa' then 2 when 'wapda' then 3 when 'pmd' then 4 when 'open_meteo_weather' then 5 when 'open_meteo_flood' then 6 when 'citizen' then 9 else 8 end"
    lead_hours = (
        "extract(epoch from (fv.valid_at - fr.issued_at)) / 3600.0"
        if dialect == "postgresql"
        else "(julianday(fv.valid_at) - julianday(fr.issued_at)) * 24.0"
    )
    recent_cutoff = "now() - interval '7 days'" if dialect == "postgresql" else "datetime('now', '-7 days')"

    views = {
        "latest_observation": f"""
            {create_prefix} latest_observation AS
            SELECT location_id, variable_id, observed_at, value, source
            FROM (
                SELECT
                    o.location_id,
                    o.variable_id,
                    o.observed_at,
                    o.value,
                    s.code AS source,
                    row_number() over (
                        partition by o.location_id, o.variable_id
                        order by o.observed_at desc, {source_priority}, o.quality
                    ) AS rn
                FROM observations o
                JOIN sources s ON s.id = o.source_id
                WHERE o.quality <> 3
            ) ranked
            WHERE rn = 1
        """,
        "latest_forecast": f"""
            {create_prefix} latest_forecast AS
            SELECT
                fr.model_id,
                fv.run_id,
                fv.location_id,
                fv.variable_id,
                fv.valid_at,
                fv.value,
                fv.p10,
                fv.p25,
                fv.p50,
                fv.p75,
                fv.p90,
                fv.prob_exceed,
                {lead_hours} AS lead_hours
            FROM forecast_values fv
            JOIN forecast_runs fr ON fr.id = fv.run_id
            JOIN (
                SELECT model_id, max(issued_at) AS issued_at
                FROM forecast_runs
                WHERE status = 'complete'
                GROUP BY model_id
            ) latest ON latest.model_id = fr.model_id AND latest.issued_at = fr.issued_at
            WHERE fr.status = 'complete'
        """,
        "observation_trend": f"""
            {create_prefix} observation_trend AS
            SELECT
                lo.location_id,
                lo.variable_id,
                lo.observed_at,
                lo.value,
                lo.value - (
                    SELECT o3.value FROM observations o3
                    WHERE o3.location_id = lo.location_id AND o3.variable_id = lo.variable_id
                      AND o3.quality <> 3 AND o3.observed_at <= lo.observed_at
                    ORDER BY abs({lead_hours.replace('fv.valid_at', 'lo.observed_at').replace('fr.issued_at', 'o3.observed_at') } - 3) ASC
                    LIMIT 1
                ) AS change_3h,
                lo.value - (
                    SELECT o24.value FROM observations o24
                    WHERE o24.location_id = lo.location_id AND o24.variable_id = lo.variable_id
                      AND o24.quality <> 3 AND o24.observed_at <= lo.observed_at
                    ORDER BY abs({lead_hours.replace('fv.valid_at', 'lo.observed_at').replace('fr.issued_at', 'o24.observed_at') } - 24) ASC
                    LIMIT 1
                ) AS change_24h
            FROM latest_observation lo
        """,
        "station_status": f"""
            {create_prefix} station_status AS
            SELECT
                l.id AS location_id,
                l.code,
                l.name,
                lo.variable_id,
                lo.observed_at,
                lo.value,
                rv.value AS highest_recorded,
                coalesce(max(CASE WHEN t.value IS NOT NULL AND lo.value >= t.value THEN t.level END), 0) AS level,
                CASE
                    WHEN coalesce(max(CASE WHEN t.value IS NOT NULL AND lo.value >= t.value THEN t.level END), 0) >= 4 THEN 'severe'
                    WHEN coalesce(max(CASE WHEN t.value IS NOT NULL AND lo.value >= t.value THEN t.level END), 0) = 3 THEN 'flood'
                    WHEN coalesce(max(CASE WHEN t.value IS NOT NULL AND lo.value >= t.value THEN t.level END), 0) >= 1 THEN 'warning'
                    ELSE 'normal'
                END AS status
            FROM locations l
            LEFT JOIN latest_observation lo ON lo.location_id = l.id
            LEFT JOIN thresholds t ON t.location_id = l.id AND t.variable_id = lo.variable_id
            LEFT JOIN record_values rv ON rv.location_id = l.id AND rv.variable_id = lo.variable_id
            WHERE l.kind in ('station','barrage','dam')
            GROUP BY l.id, l.code, l.name, lo.variable_id, lo.observed_at, lo.value, rv.value
        """,
        "hydrograph_feed": f"""
            {create_prefix} hydrograph_feed AS
            SELECT
                o.location_id,
                o.variable_id,
                o.observed_at AS at,
                o.value,
                'observed:' || s.code AS series,
                'observed' AS kind,
                NULL AS model_id,
                NULL AS run_id
            FROM observations o
            JOIN sources s ON s.id = o.source_id
            WHERE o.quality <> 3 AND o.observed_at >= {recent_cutoff}
            UNION ALL
            SELECT
                lf.location_id,
                lf.variable_id,
                lf.valid_at AS at,
                lf.value,
                'forecast:' || m.name AS series,
                'forecast' AS kind,
                lf.model_id,
                lf.run_id
            FROM latest_forecast lf
            JOIN models m ON m.id = lf.model_id
            WHERE m.status in ('active','shadow')
        """,
    }

    with engine.begin() as connection:
        for name, sql in views.items():
            if dialect != "postgresql":
                connection.execute(text(f"DROP VIEW IF EXISTS {name}"))
            connection.execute(text(sql))


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
