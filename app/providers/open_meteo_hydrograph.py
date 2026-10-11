import asyncio
import copy
import logging
import math
import time
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)
CUSECS_PER_CUMEC = 35.3147
FIELDS = ["river_discharge", "river_discharge_p25", "river_discharge_p75", "river_discharge_min", "river_discharge_max"]


def cusecs(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    converted = value * CUSECS_PER_CUMEC
    return round(converted, 2) if math.isfinite(converted) else None


def normalize(payload):
    daily = payload["daily"]
    units = payload.get("daily_units", {})
    if any(units.get(field) not in {"m\u00b3/s", "m3/s"} for field in FIELDS):
        raise ValueError("Unexpected flood units")
    dates = daily["time"]
    if not dates or any(len(daily.get(field, [])) != len(dates) for field in FIELDS):
        raise ValueError("Incomplete flood series")
    today = datetime.now(timezone.utc).date()
    points = []
    for i, date in enumerate(dates):
        day = datetime.strptime(date, "%Y-%m-%d").date()
        if day < today:
            continue  # Past modeled values must never be presented as observations.
        value = cusecs(daily[FIELDS[0]][i])
        if value is None:
            continue
        low, high = cusecs(daily[FIELDS[1]][i]), cusecs(daily[FIELDS[2]][i])
        if low is None or high is None or low > high:
            low = high = None
        points.append({"t": f"{date}T00:00:00Z", "v": value, "p25": low, "p75": high,
                       "min": cusecs(daily[FIELDS[3]][i]), "max": cusecs(daily[FIELDS[4]][i])})
    if not points:
        raise ValueError("No valid future model values")
    lat, lon = payload.get("latitude"), payload.get("longitude")
    cell = {"lat": lat, "lon": lon} if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180 else None
    return {"forecast": sorted(points, key=lambda p: p["t"]),
            "modelCell": cell,
            "generatedAt": datetime.now(timezone.utc).isoformat(), "stale": False}


class OpenMeteoHydrograph:
    def __init__(self, transport=None):
        self.cache = {}
        self.locks = {}
        self.transport = transport

    async def get(self, station, days):
        key = (station.station_id, days, station.glofas_lat, station.glofas_lon)
        lock = self.locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self.cache.get(key)
            if cached and time.monotonic() - cached[0] < 4 * 3600:
                return copy.deepcopy(cached[1])
            async with httpx.AsyncClient(timeout=6, transport=self.transport) as client:
                for attempt in range(3):
                    try:
                        response = await client.get("https://flood-api.open-meteo.com/v1/flood", params={
                            "latitude": station.glofas_lat, "longitude": station.glofas_lon, "daily": ",".join(FIELDS),
                            "past_days": 7, "forecast_days": days, "timezone": "GMT", "cell_selection": "nearest",
                        })
                        response.raise_for_status()
                        data = normalize(response.json())
                        if len(self.cache) >= 100 and key not in self.cache:
                            oldest = next(iter(self.cache))
                            self.cache.pop(oldest)
                            self.locks.pop(oldest, None)
                        self.cache[key] = (time.monotonic(), data)
                        return copy.deepcopy(data)
                    except (httpx.HTTPError, ValueError, KeyError, TypeError):
                        logger.warning("Experimental hydrograph fetch failed for %s (attempt %s)", station.station_id, attempt + 1)
                        if attempt < 2:
                            await asyncio.sleep(.3 * 2 ** attempt)
            if cached:
                return {**copy.deepcopy(cached[1]), "stale": True}
            return {"forecast": [], "modelCell": None, "generatedAt": datetime.now(timezone.utc).isoformat(), "stale": False, "forecastUnavailable": True}


open_meteo_hydrograph = OpenMeteoHydrograph()
