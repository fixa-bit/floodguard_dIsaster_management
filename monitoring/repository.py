import math
from datetime import datetime, timezone

from sqlalchemy import select

from .models import Provider, Station, StationValue


def utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must include a timezone")
    return value.astimezone(timezone.utc)


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError("Value must be a finite number")
    return float(value)


def entity(session, model, code):
    item = session.scalar(select(model).where(model.code == code))
    if item is None:
        raise ValueError(f"Unknown {model.__tablename__} code: {code}")
    return item


def store_value(session, *, station, provider, measurement, value, unit, value_type,
                value_at, forecast_issued_at=None, p25=None, p75=None, level_reference=None):
    """Store one station/provider/timestamp value without performing monitoring."""
    station_row = entity(session, Station, station)
    provider_row = entity(session, Provider, provider)
    if provider_row.kind == "model" and not provider_row.model_version:
        raise ValueError("Planned model has no trained version; register a versioned provider before storing output")
    if value_type not in {"observed", "simulated", "forecast"}:
        raise ValueError("Choose observed, simulated or forecast")
    if provider_row.kind == "model" and value_type == "observed":
        raise ValueError("Model output cannot be an observed measurement")
    if not isinstance(measurement, str) or not measurement.strip() or len(measurement) > 80:
        raise ValueError("Measurement name must have 1-80 characters")
    if not isinstance(unit, str) or not unit.strip() or len(unit) > 32:
        raise ValueError("Unit must have 1-32 characters")
    at = utc(value_at)
    issued = utc(forecast_issued_at) if forecast_issued_at is not None else None
    if value_type == "observed" and issued is not None:
        raise ValueError("Observed readings do not have a forecast issue time")
    if value_type == "forecast" and issued is not None and at < issued:
        raise ValueError("Forecast value time cannot precede issue time")
    if measurement in {"water_level", "sea_level", "reservoir_level", "glacial_lake_level",
                       "drainage_level", "groundwater_level"} and not level_reference:
        raise ValueError("Level measurements require a reference such as gauge datum or mMSL")
    value = finite(value)
    p25 = finite(p25) if p25 is not None else None
    p75 = finite(p75) if p75 is not None else None
    if p25 is not None and p75 is not None and p25 > p75:
        raise ValueError("p25 must not exceed p75")
    # Keep source units intact; FloodGuard decides how to compare/convert them.
    latest = session.scalar(select(StationValue).where(
        StationValue.station_id == station_row.id, StationValue.provider_id == provider_row.id,
        StationValue.measurement == measurement, StationValue.unit == unit,
        StationValue.value_type == value_type, StationValue.value_at == at,
        StationValue.forecast_issued_at == issued,
    ).order_by(StationValue.id.desc()).limit(1))
    if latest and (latest.value, latest.p25, latest.p75, latest.level_reference) == (value, p25, p75, level_reference):
        return latest, False
    row = StationValue(station_id=station_row.id, provider_id=provider_row.id, measurement=measurement,
                       unit=unit, value_type=value_type, value_at=at, forecast_issued_at=issued,
                       value=value, p25=p25, p75=p75, level_reference=level_reference)
    session.add(row)
    session.flush()
    return row, True
