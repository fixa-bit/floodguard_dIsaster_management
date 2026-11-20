"""Live extended GloFAS outlook and saved Marala climate-scenario summary."""
import asyncio
import copy
import time
from datetime import datetime, timedelta, timezone

import httpx

URL = "https://flood-api.open-meteo.com/v1/flood"
MARALA = {"station_id": "MARALA", "station_name": "Marala", "river": "Chenab", "latitude": 32.675, "longitude": 74.425}
DAILY_FIELDS = "river_discharge_mean,river_discharge_median,river_discharge_p25,river_discharge_p75"
CACHE_SECONDS = 60 * 60
_cache: dict | None = None
_cache_at = 0.0
_lock = asyncio.Lock()

ANNUAL_SCENARIOS = {
    "period": "2026–2040",
    "baseline_period": "1986–2014",
    "model": "8-GCM CMIP6 ensemble with projection-mode TFT",
    "annual_mean_flow_change": [
        {"scenario": "SSP2-4.5", "median_percent": 7.3, "low_percent": 0.5, "high_percent": 13.0,
         "annual_very_high_flood_probability_baseline": 0.29, "annual_very_high_flood_probability_projected": 0.33,
         "annual_very_high_flood_probability_low": 0.23, "annual_very_high_flood_probability_high": 0.44},
        {"scenario": "SSP5-8.5", "median_percent": 9.3, "low_percent": 4.8, "high_percent": 12.1,
         "annual_very_high_flood_probability_baseline": 0.29, "annual_very_high_flood_probability_projected": 0.34,
         "annual_very_high_flood_probability_low": 0.29, "annual_very_high_flood_probability_high": 0.42},
    ],
    "note": "Exploratory scenario medians across eight GCMs for 2026–2040 versus 1986–2014. Assumes unregulated upstream flow; it is not a forecast for the next 365 days or a day-specific flood warning.",
}


def _num(values, index):
    if index >= len(values) or values[index] is None:
        return None
    value = float(values[index])
    return value if value >= 0 else None


async def _fetch_live() -> dict:
    params = {
        "latitude": MARALA["latitude"],
        "longitude": MARALA["longitude"],
        "daily": DAILY_FIELDS,
        "forecast_days": 210,
        "cell_selection": "nearest",
        "timezone": "GMT",
    }
    async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
        response = await client.get(URL, params=params)
        response.raise_for_status()
        payload = response.json()

    daily = payload.get("daily") or {}
    fields = {
        "mean_cumecs": daily.get("river_discharge_mean") or [],
        "median_cumecs": daily.get("river_discharge_median") or [],
        "p25_cumecs": daily.get("river_discharge_p25") or [],
        "p75_cumecs": daily.get("river_discharge_p75") or [],
    }
    dates = daily.get("time") or []
    today = datetime.now(timezone.utc).date().isoformat()
    forecast = []
    for index, day in enumerate(dates):
        if day < today:
            continue
        mean = _num(fields["mean_cumecs"], index)
        median = _num(fields["median_cumecs"], index)
        if mean is None and median is None:
            continue
        forecast.append({"date": day, **{key: _num(values, index) for key, values in fields.items()}})
        if len(forecast) >= 30:
            break
    if not forecast:
        raise ValueError("GloFAS did not return future daily flow values for Marala")

    return {
        **MARALA,
        "status": "live",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "Open-Meteo Flood API · GloFAS modeled reach discharge",
        "source_url": response.url.__str__(),
        "daily_forecast": forecast,
        "annual_projection": ANNUAL_SCENARIOS,
        "limitations": [
            "The 30-day series is provider-modeled discharge at the nearest GloFAS grid cell, not a measured station forecast.",
            "The annual outlook summarizes 2026–2040 climate scenarios and is not a next-year operational forecast.",
        ],
    }


async def get_riverine_extended_forecast() -> dict:
    global _cache, _cache_at
    async with _lock:
        if _cache is not None and time.monotonic() - _cache_at < CACHE_SECONDS:
            return copy.deepcopy(_cache)
        try:
            result = await _fetch_live()
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            if _cache is None:
                raise
            result = copy.deepcopy(_cache)
            result["status"] = "stale"
            result["refresh_error"] = str(exc)
            return result
        _cache = result
        _cache_at = time.monotonic()
        return copy.deepcopy(result)
