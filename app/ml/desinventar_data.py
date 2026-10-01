import csv
import hashlib
import io
import json
import math
import re
import time
import threading
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import numpy as np

from app.gis.geometry import representative_point


DESINVENTAR_URL = "https://www.desinventar.net/DesInventar/download/DI_export_pak.zip"
WEATHER_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FLOOD_ARCHIVE_URL = "https://flood-api.open-meteo.com/v1/flood"
DISTRICT_PATH = Path(__file__).parents[1] / "gis" / "data" / "pakistan_districts.geojson"
CACHE_PATH = Path(__file__).parent / "data" / "cache" / "desinventar"
_REQUEST_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0
V2_FEATURE_NAMES = [
    "rainfall_1d", "rainfall_3d", "rainfall_7d", "rainfall_14d", "rainfall_30d",
    "forecast_rainfall_1d", "soil_moisture", "river_discharge", "discharge_change_1d",
    "discharge_ratio_7d", "discharge_ratio_30d", "discharge_zscore_30d",
    "elevation_m", "month_sin", "month_cos",
]
AJK_DISTRICTS = {"bagh", "bhimber", "hattian", "haveli", "kotli", "mirpur", "muzaffarabad", "neelum", "poonch", "sudhnoti"}
ALIASES = {
    "batagram": "Battagram", "diamir": "Diamer", "islamabad": "Islamabad Capital Territory",
    "jaffarabad": "Jafarabad", "kachi": "Kachhi", "killa saifullah": "Qilla Saifullah",
    "las bela": "Lasbela", "sheerani": "Zhob", "washuk": "Kharan",
}
COVARIATE_YEARS_EXCLUDED = {2007}


def build_desinventar_dataset(dataset_path: str, cleaned_events_path: str, quality_report_path: str, workers: int = 1) -> Path:
    events, quality = clean_desinventar_events()
    cleaned_path = Path(cleaned_events_path)
    cleaned_path.parent.mkdir(parents=True, exist_ok=True)
    with cleaned_path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=["district", "date", "event_type", "source"])
        writer.writeheader()
        writer.writerows(events)

    districts = _district_coordinates()
    grouped: dict[int, dict[str, set[date]]] = defaultdict(lambda: defaultdict(set))
    for event in events:
        grouped[date.fromisoformat(event["date"]).year][event["district"]].add(date.fromisoformat(event["date"]))

    tasks = []
    for year, district_events in grouped.items():
        if year in COVARIATE_YEARS_EXCLUDED:
            continue
        names = sorted(district_events)
        for index in range(0, len(names), 6):
            batch = names[index : index + 6]
            tasks.append((year, batch, {name: district_events[name] for name in batch}))
    rows = []
    failures = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_batch_rows, *task, districts): task for task in tasks}
        completed = 0
        for future in as_completed(futures):
            try:
                rows.extend(future.result())
                completed += 1
                print(f"Historical batches complete: {completed}/{len(tasks)}", flush=True)
            except Exception as exc:
                year, names, _ = futures[future]
                failures.append({"year": year, "districts": names, "error": str(exc)})
    if failures:
        raise RuntimeError(f"Historical provider batches failed: {failures[:3]}")
    rows.sort(key=lambda row: (row["district"], row["date"]))
    destination = Path(dataset_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fields = ["district", "date", "geographic_block", "label", *V2_FEATURE_NAMES]
    with destination.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    quality.update({
        "dataset_rows": len(rows),
        "positive_rows": sum(row["label"] for row in rows),
        "negative_rows": sum(not row["label"] for row in rows),
        "districts_in_dataset": len({row["district"] for row in rows}),
        "geographic_blocks": len({row["geographic_block"] for row in rows}),
        "feature_names": V2_FEATURE_NAMES,
        "covariate_years_excluded": sorted(COVARIATE_YEARS_EXCLUDED),
        "covariate_exclusion_reason": "The free Open-Meteo hourly quota was exhausted before complete national coverage; the whole year was excluded to avoid partial-district selection bias.",
        "negative_sampling": "Matched same-district dates at +/-7, 14, 21, and 28 days, excluding +/-3 days around a recorded event.",
    })
    report_path = Path(quality_report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(quality, indent=2), encoding="utf-8")
    return destination


def clean_desinventar_events(min_year: int = 2000) -> tuple[list[dict], dict]:
    response = httpx.get(DESINVENTAR_URL, timeout=90, follow_redirects=True)
    response.raise_for_status()
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    xml_name = next(name for name in archive.namelist() if name.lower().endswith(".xml"))
    canonical = _canonical_districts()
    quality = defaultdict(int)
    records: dict[tuple[str, date], dict] = {}
    with archive.open(xml_name) as source:
        for _, element in ET.iterparse(source, events=("end",)):
            if element.tag != "TR":
                continue
            row = {child.tag: (child.text or "").strip() for child in element}
            event_type = row.get("evento", "").upper()
            if event_type not in {"FLOOD", "FLASH FLOOD"}:
                element.clear()
                continue
            quality["raw_flood_records"] += 1
            try:
                event_date = date(int(row["fechano"]), int(row["fechames"]), int(row["fechadia"]))
            except (KeyError, TypeError, ValueError):
                quality["invalid_date_records"] += 1
                element.clear()
                continue
            if event_date.year < min_year:
                quality["pre_2000_records_excluded"] += 1
                element.clear()
                continue
            district = _map_district(row.get("name1", ""), canonical)
            if district is None:
                quality["unmapped_district_records"] += 1
                element.clear()
                continue
            key = district, event_date
            records[key] = {
                "district": district,
                "date": event_date.isoformat(),
                "event_type": event_type,
                "source": row.get("fuentes", "") or "DesInventar",
            }
            element.clear()
    quality["duplicate_district_dates_removed"] = (
        quality["raw_flood_records"] - quality["invalid_date_records"] - quality["pre_2000_records_excluded"]
        - quality["unmapped_district_records"] - len(records)
    )
    quality["cleaned_positive_district_dates"] = len(records)
    quality["source_url"] = DESINVENTAR_URL
    quality["minimum_year"] = min_year
    return sorted(records.values(), key=lambda item: (item["district"], item["date"])), dict(quality)


def load_desinventar_dataset(path: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    with Path(path).open(encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    features = np.asarray([[float(row[name]) for name in V2_FEATURE_NAMES] for row in rows], dtype=np.float32)
    labels = np.asarray([int(row["label"]) for row in rows], dtype=np.float32)
    districts = np.asarray([row["district"] for row in rows])
    blocks = np.asarray([row["geographic_block"] for row in rows])
    dates = np.asarray([date.fromisoformat(row["date"]) for row in rows])
    return features, labels, districts, blocks, dates


def _batch_rows(year: int, names: list[str], events: dict[str, set[date]], districts: dict[str, dict]) -> list[dict]:
    start, end = date(year - 1, 11, 25), date(year + 1, 1, 2)
    coordinates = [districts[name] for name in names]
    common = {
        "latitude": ",".join(str(item["latitude"]) for item in coordinates),
        "longitude": ",".join(str(item["longitude"]) for item in coordinates),
        "start_date": start.isoformat(), "end_date": end.isoformat(), "timezone": "UTC",
    }
    try:
        weather = _get_payloads(
            WEATHER_ARCHIVE_URL,
            {**common, "daily": "precipitation_sum,soil_moisture_0_to_7cm_mean"},
        )
        river = _get_payloads(FLOOD_ARCHIVE_URL, {**common, "daily": "river_discharge", "cell_selection": "nearest"})
    except RuntimeError:
        if len(names) == 1:
            raise
        midpoint = len(names) // 2
        left, right = names[:midpoint], names[midpoint:]
        return (
            _batch_rows(year, left, {name: events[name] for name in left}, districts)
            + _batch_rows(year, right, {name: events[name] for name in right}, districts)
        )
    rows = []
    for name, weather_payload, river_payload in zip(names, weather, river, strict=True):
        weather_days = _weather_days(weather_payload)
        river_days = _river_days(river_payload)
        positives = events[name]
        excluded = {day + timedelta(days=offset) for day in positives for offset in range(-3, 4)}
        negatives = {
            candidate
            for day in positives
            for offset in (-28, -21, -14, -7, 7, 14, 21, 28)
            if (candidate := day + timedelta(days=offset)).year == year and candidate not in excluded
        }
        for day, label in [(value, 1) for value in positives] + [(value, 0) for value in negatives]:
            features = _features_for_day(day, weather_days, river_days, float(weather_payload.get("elevation", 0)))
            if features is None:
                continue
            point = districts[name]
            rows.append({
                "district": name, "date": day.isoformat(),
                "geographic_block": f"N{int(point['latitude'] // 2) * 2:02d}_E{int(point['longitude'] // 2) * 2:02d}",
                "label": label, **features,
            })
    return rows


def _features_for_day(day: date, weather: dict[date, dict], river: dict[date, float], elevation: float) -> dict | None:
    if day not in weather or day not in river or day + timedelta(days=1) not in weather:
        return None
    rain = lambda days: sum(weather.get(day - timedelta(days=offset), {}).get("rain", 0) for offset in range(days))
    discharge_window = [river.get(day - timedelta(days=offset)) for offset in range(30)]
    if any(value is None for value in discharge_window):
        return None
    discharge = river[day]
    mean7, mean30 = float(np.mean(discharge_window[:7])), float(np.mean(discharge_window))
    std30 = float(np.std(discharge_window))
    angle = 2 * math.pi * day.month / 12
    return {
        "rainfall_1d": round(rain(1), 3), "rainfall_3d": round(rain(3), 3),
        "rainfall_7d": round(rain(7), 3), "rainfall_14d": round(rain(14), 3), "rainfall_30d": round(rain(30), 3),
        "forecast_rainfall_1d": round(weather[day + timedelta(days=1)]["rain"], 3),
        "soil_moisture": round(weather[day]["soil"], 3), "river_discharge": round(discharge, 3),
        "discharge_change_1d": round(discharge - river[day - timedelta(days=1)], 3),
        "discharge_ratio_7d": round(discharge / max(mean7, 0.001), 5),
        "discharge_ratio_30d": round(discharge / max(mean30, 0.001), 5),
        "discharge_zscore_30d": round((discharge - mean30) / max(std30, 0.001), 5),
        "elevation_m": elevation, "month_sin": round(math.sin(angle), 6), "month_cos": round(math.cos(angle), 6),
    }


def _weather_days(payload: dict) -> dict[date, dict]:
    daily = payload["daily"]
    return {
        date.fromisoformat(day): {"rain": float(rain or 0), "soil": float(soil or 0) * 100}
        for day, rain, soil in zip(
            daily["time"], daily["precipitation_sum"], daily["soil_moisture_0_to_7cm_mean"], strict=True
        )
    }


def _river_days(payload: dict) -> dict[date, float]:
    return {date.fromisoformat(day): float(value) for day, value in zip(payload["daily"]["time"], payload["daily"]["river_discharge"], strict=True) if value is not None}


def _get_payloads(url: str, params: dict) -> list[dict]:
    cache_key = hashlib.sha256(
        json.dumps({"url": url, "params": params}, sort_keys=True).encode("utf-8")
    ).hexdigest()
    cache_file = CACHE_PATH / f"{cache_key}.json"
    if cache_file.exists():
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
        return payload if isinstance(payload, list) else [payload]

    last_error = None
    for attempt in range(3):
        try:
            response = _paced_get(url, params)
            response.raise_for_status()
            payload = response.json()
            CACHE_PATH.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(payload), encoding="utf-8")
            return payload if isinstance(payload, list) else [payload]
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
            retry_after = 0
            if isinstance(exc, httpx.HTTPStatusError):
                retry_after = int(exc.response.headers.get("Retry-After", "0") or 0)
            time.sleep(max(retry_after, 2 ** attempt))
    detail = str(last_error)
    if isinstance(last_error, httpx.HTTPStatusError):
        detail = f"HTTP {last_error.response.status_code}: {last_error.response.text[:300]}"
    raise RuntimeError(f"Provider failed: {url} ({detail})") from last_error


def _paced_get(url: str, params: dict) -> httpx.Response:
    global _LAST_REQUEST_AT
    with _REQUEST_LOCK:
        delay = 0.75 - (time.monotonic() - _LAST_REQUEST_AT)
        if delay > 0:
            time.sleep(delay)
        timeout = httpx.Timeout(30, connect=15)
        response = httpx.get(url, params=params, timeout=timeout, follow_redirects=True)
        _LAST_REQUEST_AT = time.monotonic()
        return response


def _canonical_districts() -> dict[str, str]:
    with DISTRICT_PATH.open(encoding="utf-8") as source:
        geojson = json.load(source)
    return {_normalize(feature["properties"]["shapeName"]): feature["properties"]["shapeName"] for feature in geojson["features"]}


def _district_coordinates() -> dict[str, dict]:
    with DISTRICT_PATH.open(encoding="utf-8") as source:
        geojson = json.load(source)
    result = {}
    for feature in geojson["features"]:
        name = feature["properties"]["shapeName"]
        longitude, latitude = representative_point(feature["geometry"])
        result[name] = {"longitude": longitude, "latitude": latitude}
    return result


def _map_district(value: str, canonical: dict[str, str]) -> str | None:
    normalized = _normalize(value)
    if normalized in AJK_DISTRICTS:
        return "Azad Kashmir"
    if normalized in ALIASES:
        return ALIASES[normalized]
    return canonical.get(normalized)


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
