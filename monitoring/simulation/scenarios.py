from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from monitoring.models import Provider
from monitoring.repository import finite, store_value, utc


SIMULATED_FLOW_PROVIDER_PREFIX = "SIMULATED_FLOW"
LEVEL_MEASUREMENTS = {
    "water_level",
    "sea_level",
    "reservoir_level",
    "glacial_lake_level",
    "drainage_level",
    "groundwater_level",
}


@dataclass(frozen=True)
class SimulationResult:
    scenarios: int
    records: int
    inserted: int
    provider_codes: tuple[str, ...]


def load_scenarios(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list) and all(isinstance(item, dict) for item in payload):
        return payload
    raise ValueError("Simulation file must be a scenario object or an array of scenario objects")


def provider_code_from_name(name):
    label = str(name or "").strip()
    if not label:
        return SIMULATED_FLOW_PROVIDER_PREFIX
    slug = re.sub(r"[^A-Z0-9]+", "_", label.upper()).strip("_")
    if not slug:
        return SIMULATED_FLOW_PROVIDER_PREFIX
    return f"{SIMULATED_FLOW_PROVIDER_PREFIX}_{slug}"[:120].rstrip("_")


def build_records(scenario):
    if not isinstance(scenario, dict):
        raise ValueError("Simulation scenario must be an object")
    provider_code = _provider_code(scenario)
    records = []
    for series in _series_payloads(scenario):
        records.extend(_series_records(series, provider_code))
    return records


def store_scenarios(session, scenarios):
    if isinstance(scenarios, dict):
        scenarios = [scenarios]
    if not isinstance(scenarios, list) or not all(isinstance(item, dict) for item in scenarios):
        raise ValueError("Scenarios must be a scenario object or a list of scenario objects")

    inserted = 0
    records = 0
    provider_codes = set()
    for scenario in scenarios:
        provider_code = _provider_code(scenario)
        ensure_simulation_provider(session, provider_code, _provider_name(scenario))
        provider_codes.add(provider_code)
        for record in build_records({**scenario, "provider_code": provider_code}):
            records += 1
            inserted += int(store_value(session, **record)[1])
    return SimulationResult(
        scenarios=len(scenarios),
        records=records,
        inserted=inserted,
        provider_codes=tuple(sorted(provider_codes)),
    )


def ensure_simulation_provider(session, code, name=None):
    if not isinstance(code, str) or not code.strip() or len(code) > 120:
        raise ValueError("Simulation provider code must have 1-120 characters")
    code = code.strip()
    provider = session.scalar(select(Provider).where(Provider.code == code))
    if provider is not None:
        if provider.kind != "import":
            raise ValueError(f"Simulation provider code {code} already exists with kind {provider.kind}")
        return provider
    provider = Provider(code=code, name=(name or "Simulated flow")[:160], kind="import")
    session.add(provider)
    session.flush()
    return provider


def _provider_code(scenario):
    override = scenario.get("provider_code")
    if override is not None:
        if not isinstance(override, str) or not override.strip() or len(override.strip()) > 120:
            raise ValueError("provider_code must have 1-120 characters")
        return override.strip()
    return provider_code_from_name(scenario.get("name"))


def _provider_name(scenario):
    name = str(scenario.get("name") or "").strip()
    return f"Simulated flow - {name}" if name else "Simulated flow"


def _series_payloads(scenario):
    series = scenario.get("series")
    if series is None:
        return [scenario]
    if not isinstance(series, list) or not series or not all(isinstance(item, dict) for item in series):
        raise ValueError("series must be a non-empty array of objects")
    defaults = {key: value for key, value in scenario.items() if key != "series"}
    return [{**defaults, **item} for item in series]


def _series_records(series, provider_code):
    station = _required_string(series, "station")
    measurement = _string(series.get("measurement", "discharge_inflow"), "measurement")
    unit = _string(series.get("unit", "cusecs"), "unit")
    level_reference = series.get("level_reference")
    if measurement in LEVEL_MEASUREMENTS and not level_reference:
        raise ValueError(f"{measurement} simulations require level_reference")

    start_at = utc(_required(series, "start_at"))
    interval = timedelta(minutes=_positive_int(series.get("interval_minutes", 60), "interval_minutes"))
    values = _profile_values(series)
    records = []
    for index, value in enumerate(values):
        p25, p75 = _uncertainty_band(series, value)
        records.append({
            "station": station,
            "provider": provider_code,
            "measurement": measurement,
            "value": value,
            "unit": unit,
            "value_type": "simulated",
            "value_at": start_at + (interval * index),
            "forecast_issued_at": None,
            "p25": p25,
            "p75": p75,
            "level_reference": level_reference,
        })
    return records


def _profile_values(series):
    explicit = series.get("step_values")
    if explicit is not None:
        if not isinstance(explicit, list) or not explicit:
            raise ValueError("step_values must be a non-empty array")
        return [finite(value) for value in explicit]

    baseline = finite(_required(series, "baseline_value"))
    peak = finite(_required(series, "peak_value"))
    recovery = finite(series.get("recovery_value", baseline))
    rise_steps = _positive_int(series.get("rise_steps", 4), "rise_steps")
    hold_steps = _non_negative_int(series.get("hold_steps", 1), "hold_steps")
    recession_steps = _non_negative_int(series.get("recession_steps", 4), "recession_steps")

    if rise_steps == 1:
        values = [peak]
    else:
        values = [baseline + ((peak - baseline) * (index / (rise_steps - 1))) for index in range(rise_steps)]
    values.extend(peak for _ in range(hold_steps))
    if recession_steps:
        values.extend(peak + ((recovery - peak) * ((index + 1) / recession_steps))
                      for index in range(recession_steps))
    return [finite(value) for value in values]


def _uncertainty_band(series, value):
    has_specific_band = any(key in series for key in ["p25_ratio", "p25_offset", "p75_ratio", "p75_offset"])
    if has_specific_band:
        p25 = _band_value(series, value, "p25_ratio", "p25_offset", -1)
        p75 = _band_value(series, value, "p75_ratio", "p75_offset", 1)
        return p25, p75
    if "uncertainty_ratio" in series:
        ratio = _non_negative_float(series["uncertainty_ratio"], "uncertainty_ratio")
        return finite(value * (1 - ratio)), finite(value * (1 + ratio))
    return None, None


def _band_value(series, value, ratio_key, offset_key, direction):
    if ratio_key in series and offset_key in series:
        raise ValueError(f"Use either {ratio_key} or {offset_key}, not both")
    if ratio_key in series:
        ratio = _non_negative_float(series[ratio_key], ratio_key)
        return finite(value * (1 + (direction * ratio)))
    if offset_key in series:
        offset = _non_negative_float(series[offset_key], offset_key)
        return finite(value + (direction * offset))
    return None


def _required(payload, key):
    if key not in payload:
        raise ValueError(f"Missing required simulation field: {key}")
    return payload[key]


def _required_string(payload, key):
    return _string(_required(payload, key), key)


def _string(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _positive_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _non_negative_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _non_negative_float(value, field):
    number = finite(value)
    if number < 0:
        raise ValueError(f"{field} must be non-negative")
    return number
