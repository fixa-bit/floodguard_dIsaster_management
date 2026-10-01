import csv
import io
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import numpy as np

from app.ml.synthetic_data import FEATURE_NAMES


EVENT_CATALOG_URL = "https://storage.googleapis.com/event_stats/gfd_event_stats_20215_13_error_fixed_2.csv"
WEATHER_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FLOOD_ARCHIVE_URL = "https://flood-api.open-meteo.com/v1/flood"
HOURLY_FIELDS = "precipitation,temperature_2m,relative_humidity_2m,soil_moisture_0_to_7cm"


@dataclass(frozen=True)
class FloodEvent:
    event_id: str
    latitude: float
    longitude: float
    began: date
    ended: date
    validation: str


def fetch_pakistan_events() -> list[FloodEvent]:
    response = httpx.get(EVENT_CATALOG_URL, timeout=60, follow_redirects=True)
    response.raise_for_status()
    events = []
    for row in csv.DictReader(io.StringIO(response.text)):
        countries = f"{row['dfo_country']} {row['dfo_other_country']}"
        if "Pakistan" not in countries:
            continue
        events.append(FloodEvent(
            event_id=row["system:index"],
            latitude=float(row["dfo_centroid_y"]),
            longitude=float(row["dfo_centroid_x"]),
            began=datetime.strptime(row["dfo_began"], "%m/%d/%y").date(),
            ended=datetime.strptime(row["dfo_ended"], "%m/%d/%y").date(),
            validation=row["dfo_validation"],
        ))
    return events


def build_real_dataset(output_path: str, workers: int = 6) -> Path:
    events = fetch_pakistan_events()
    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_event_rows, event): event for event in events}
        for future in as_completed(futures):
            rows.extend(future.result())
    rows.sort(key=lambda row: (row["event_id"], row["date"]))
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["event_id", "date", "latitude", "longitude", "geographic_block", "label", "validation_source", *FEATURE_NAMES]
    with destination.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return destination


def load_real_dataset(path: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    with Path(path).open(encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    features = np.asarray([
        [float(row[name]) if row[name] else np.nan for name in FEATURE_NAMES]
        for row in rows
    ], dtype=np.float32)
    labels = np.asarray([int(row["label"]) for row in rows], dtype=np.float32)
    groups = np.asarray([row["event_id"] for row in rows])
    geographic_blocks = np.asarray([row["geographic_block"] for row in rows])
    return features, labels, groups, geographic_blocks


def _event_rows(event: FloodEvent) -> list[dict]:
    start = event.began - timedelta(days=31)
    end = event.ended + timedelta(days=31)
    weather = _get_json(WEATHER_ARCHIVE_URL, {
        "latitude": event.latitude,
        "longitude": event.longitude,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "hourly": HOURLY_FIELDS,
        "timezone": "UTC",
    })
    river = _get_json(FLOOD_ARCHIVE_URL, {
        "latitude": event.latitude,
        "longitude": event.longitude,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": "river_discharge",
        "cell_selection": "nearest",
    })
    weather_days = _daily_weather(weather)
    river_days = {
        date.fromisoformat(day): float(value)
        for day, value in zip(river["daily"]["time"], river["daily"]["river_discharge"], strict=True)
        if value is not None
    }
    rows = []
    current = start + timedelta(days=1)
    while current < end:
        if current not in weather_days or current not in river_days or current - timedelta(days=1) not in river_days:
            current += timedelta(days=1)
            continue
        in_event = event.began <= current <= event.ended
        values = weather_days[current]
        tomorrow = weather_days.get(current + timedelta(days=1), values)
        rows.append({
            "event_id": event.event_id,
            "date": current.isoformat(),
            "latitude": event.latitude,
            "longitude": event.longitude,
            "geographic_block": f"N{int(event.latitude // 2) * 2:02d}_E{int(event.longitude // 2) * 2:02d}",
            "label": int(in_event),
            "validation_source": event.validation,
            "rainfall_last_1h": values["rainfall_1h"],
            "rainfall_last_6h": values["rainfall_6h"],
            "rainfall_last_24h": values["rainfall_24h"],
            "forecast_rainfall_24h": tomorrow["rainfall_24h"],
            "river_level": "",
            "river_level_relative_to_warning": "",
            "river_rise_rate": "",
            "river_discharge": river_days[current],
            "river_discharge_change": river_days[current] - river_days[current - timedelta(days=1)],
            "soil_moisture": values["soil_moisture"],
        })
        current += timedelta(days=1)
    return rows


def _get_json(url: str, params: dict) -> dict:
    last_error: Exception | None = None
    for _ in range(3):
        try:
            response = httpx.get(url, params=params, timeout=90, follow_redirects=True)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            last_error = exc
    raise RuntimeError(f"Historical provider failed for {url}") from last_error


def _daily_weather(payload: dict) -> dict[date, dict[str, float]]:
    hourly = payload["hourly"]
    buckets: dict[date, dict[str, list[float]]] = {}
    for index, timestamp in enumerate(hourly["time"]):
        day = datetime.fromisoformat(timestamp).date()
        bucket = buckets.setdefault(day, {"rain": [], "soil": []})
        bucket["rain"].append(float(hourly["precipitation"][index] or 0))
        soil = hourly["soil_moisture_0_to_7cm"][index]
        if soil is not None:
            bucket["soil"].append(float(soil) * 100)
    result = {}
    for day, bucket in buckets.items():
        rain = bucket["rain"]
        result[day] = {
            "rainfall_1h": max(rain, default=0),
            "rainfall_6h": max((sum(rain[index : index + 6]) for index in range(max(1, len(rain) - 5))), default=0),
            "rainfall_24h": sum(rain),
            "soil_moisture": float(np.mean(bucket["soil"])) if bucket["soil"] else 0,
        }
    return result
