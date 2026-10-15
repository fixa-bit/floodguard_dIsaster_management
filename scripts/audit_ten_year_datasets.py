"""Audit local outlook inputs without downloading data or changing runtime behavior.

Run: .venv/Scripts/python.exe scripts/audit_ten_year_datasets.py
Only features/ten-year-dataset-audit.json is written; input files and databases
are opened read-only. Run while ingestion is idle for an exact DB snapshot.
"""
import csv
import hashlib
import json
import math
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.gis.geometry import geometry_bounds, point_in_geometry, representative_point


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def signature(path):
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def normalize(name):
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def csv_audit(path):
    with path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    fields = list(rows[0])
    dates = sorted(row["date"] for row in rows if row.get("date"))
    missing = {field: sum(row[field].strip().lower() in {"", "nan", "null", "none"} for row in rows)
               for field in fields}
    nonfinite = Counter()
    for row in rows:
        for field, value in row.items():
            try:
                if value and not math.isfinite(float(value)):
                    nonfinite[field] += 1
            except ValueError:
                pass
    key_fields = [field for field in ("district", "event_id", "date") if field in fields]
    report = {**signature(path), "rows": len(rows), "columns": fields,
              "date_min": dates[0] if dates else None, "date_max": dates[-1] if dates else None,
              "rows_by_year": dict(sorted(Counter(day[:4] for day in dates).items())),
              "missing_by_column": {key: value for key, value in missing.items() if value},
              "nonfinite_by_column": dict(nonfinite)}
    for field in ("district", "event_type", "label", "source", "validation_source", "target_station"):
        if field in fields:
            report[f"counts_by_{field}"] = dict(sorted(Counter(row[field] for row in rows).items()))
    if key_fields:
        report["duplicate_identity_rows"] = len(rows) - len({tuple(row[f] for f in key_fields) for row in rows})
    if "district" in fields:
        per_district = defaultdict(Counter)
        for row in rows:
            per_district[row["district"]][row["date"][:4]] += 1
        report["district_year_rows"] = {name: dict(sorted(counts.items())) for name, counts in sorted(per_district.items())}
    if "event_id" in fields:
        report["unique_events"] = len({row["event_id"] for row in rows})
    return report, rows


def geographic_audit(path):
    from shapely.geometry import shape
    from shapely.validation import explain_validity
    data = load(path)
    features = data.get("features", [])
    invalid = []
    for index, feature in enumerate(features):
        geometry = shape(feature["geometry"])
        if not geometry.is_valid or geometry.is_empty:
            invalid.append({"index": index, "properties": feature.get("properties", {}),
                            "reason": explain_validity(geometry)})
    return {**signature(path), "features": len(features),
            "metadata": data.get("metadata"), "crs": data.get("crs", "GeoJSON longitude/latitude convention"),
            "geometry_types": dict(Counter(feature["geometry"]["type"] for feature in features)),
            "invalid_or_empty_geometries": invalid}, data


def cache_audit(events, old_geo):
    """Reconstruct existing request hashes to identify districts despite snapped cells."""
    coordinates = {}
    legacy_coordinates = {}
    legacy_outside = []
    for feature in old_geo["features"]:
        lon, lat = representative_point(feature["geometry"])
        coordinates[feature["properties"]["shapeName"]] = (lon, lat)
        west, south, east, north = geometry_bounds(feature["geometry"])
        legacy = (round((west + east) / 2, 5), round((south + north) / 2, 5))
        legacy_coordinates[feature["properties"]["shapeName"]] = legacy
        if not point_in_geometry(*legacy, feature["geometry"]):
            legacy_outside.append(feature["properties"]["shapeName"])
    groups = defaultdict(set)
    for event in events:
        groups[int(event["date"][:4])].add(event["district"])
    identities = {}
    for year, group in groups.items():
        names = sorted(group)
        def register(batch):
            # Initial-commit geometry.py used rounded bounding-box midpoints.
            # Try both definitions to reproduce the original cache request keys.
            for coordinate_method, lookup in (("current_interior_point", coordinates),
                                               ("legacy_rounded_bbox_midpoint", legacy_coordinates)):
                points = [lookup[name] for name in batch]
                common = {"latitude": ",".join(str(p[1]) for p in points),
                          "longitude": ",".join(str(p[0]) for p in points),
                          "start_date": date(year - 1, 11, 25).isoformat(),
                          "end_date": date(year + 1, 1, 2).isoformat(), "timezone": "UTC"}
                for kind, url, extra in (
                    ("weather", "https://archive-api.open-meteo.com/v1/archive",
                     {"daily": "precipitation_sum,soil_moisture_0_to_7cm_mean"}),
                    ("river", "https://flood-api.open-meteo.com/v1/flood",
                     {"daily": "river_discharge", "cell_selection": "nearest"}),
                ):
                    key = hashlib.sha256(json.dumps({"url": url, "params": {**common, **extra}}, sort_keys=True).encode()).hexdigest()
                    identities[key] = (year, batch, kind, coordinate_method)
            if len(batch) > 1:
                mid = len(batch) // 2
                register(batch[:mid])
                register(batch[mid:])
        for index in range(0, len(names), 6):
            register(names[index:index + 6])
    files = sorted((ROOT / "app/ml/data/cache/desinventar").glob("*.json"))
    field_stats = defaultdict(Counter)
    coverage = defaultdict(lambda: {"dates": set(), "valid": defaultdict(set)})
    unmatched, length_mismatch, duplicate_days, all_dates = [], [], 0, set()
    matched_coordinate_methods = Counter()
    for path in files:
        data = load(path)
        payloads = data if isinstance(data, list) else [data]
        identity = identities.get(path.stem)
        if identity is None:
            unmatched.append(path.name)
        elif len(payloads) != len(identity[1]):
            length_mismatch.append(path.name)
            identity = None
        if identity:
            matched_coordinate_methods[identity[3]] += 1
        for index, payload in enumerate(payloads):
            daily = payload.get("daily", {})
            days = daily.get("time", [])
            all_dates.update(days)
            duplicate_days += len(days) - len(set(days))
            record = coverage[(identity[1][index], identity[0], identity[2])] if identity else None
            if record is not None:
                record["dates"].update(day for day in days if day.startswith(str(identity[0])))
            for field, values in daily.items():
                if field == "time":
                    continue
                stats = field_stats[field]
                stats["series"] += 1
                stats["values"] += len(values)
                stats["length_mismatches"] += len(values) != len(days)
                for day, value in zip(days, values):
                    valid = isinstance(value, (int, float)) and math.isfinite(value)
                    stats["null_or_nonfinite"] += not valid
                    stats["negative"] += bool(valid and value < 0)
                    if record is not None and valid and day.startswith(str(identity[0])):
                        record["valid"][field].add(day)
    summary = []
    for (name, year, kind), record in sorted(coverage.items()):
        year_days = (date(year + 1, 1, 1) - date(year, 1, 1)).days
        summary.append({"district": name, "year": year, "kind": kind, "calendar_days": year_days,
                        "cached_days": len(record["dates"]),
                        "valid_days_by_field": {field: len(days) for field, days in record["valid"].items()},
                        "missing_days_by_field": {field: year_days - len(days) for field, days in record["valid"].items()}})
    return {"files": len(files), "field_statistics": dict(field_stats),
            "duplicate_dates_within_series": duplicate_days,
            "date_min": min(all_dates) if all_dates else None,
            "date_max": max(all_dates) if all_dates else None,
            "unmatched_request_hashes": unmatched, "payload_length_mismatches": length_mismatch,
            "matched_coordinate_methods": dict(matched_coordinate_methods),
            "legacy_sample_points_outside_own_polygon": sorted(legacy_outside),
            "district_year_coverage": summary,
            "unique_weather_district_years": sum(row["kind"] == "weather" for row in summary),
            "unique_river_district_years": sum(row["kind"] == "river" for row in summary)}


def database_audit():
    result = {}
    selections = {
        "floodguard.db": [("district_risk_snapshots", "observed_at", None),
                          ("observations", "observed_at", None),
                          ("river_gauge_observations", "recorded_at", None),
                          ("typed_river_gauge_observations", "recorded_at", "source"),
                          ("station_observations", "observed_at", "source"),
                          ("model_forecast_points", "valid_at", "model_name")],
        "monitoring/data/monitoring.db": [("station_values", "value_at", "value_type")],
    }
    for name, tables in selections.items():
        path = ROOT / name
        if not path.exists():
            result[name] = {"available": False}
            continue
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            existing = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            summary = {}
            for table, time_column, group in tables:
                if table not in existing:
                    summary[table] = {"available": False}
                    continue
                columns = f'{group},' if group else ''
                sql = f'SELECT {columns}COUNT(*), MIN({time_column}), MAX({time_column}) FROM {table}'
                if group:
                    sql += f' GROUP BY {group}'
                rows = db.execute(sql).fetchall()
                summary[table] = [{"group": row[0] if group else "all", "rows": row[-3],
                                   "time_min": row[-2], "time_max": row[-1]} for row in rows]
            result[name] = summary
        finally:
            db.close()
    return result


def main():
    report = {"audited_at": datetime.now(timezone.utc).isoformat(), "scope": "Read-only local dataset readiness audit; no model training",
              "csv": {}, "geography": {}}
    csv_rows = {}
    for name in ("pakistan_desinventar_cleaned_events.csv", "pakistan_desinventar_training.csv",
                 "pakistan_real_flood_training.csv", "riverine_station_training.csv"):
        summary, rows = csv_audit(ROOT / "app/ml/data" / name)
        report["csv"][name] = summary
        csv_rows[name] = rows
    geography = {}
    for name in ("app/gis/data/pakistan_districts.geojson", "frontend/src/data/pakistan/pakistan_districts.geojson",
                 "frontend/src/data/pakistan/pakistan_admin1.geojson", "frontend/src/data/pakistan/catchment_areas.geojson",
                 "app/gis/data/rainfall_coverage.geojson"):
        summary, data = geographic_audit(ROOT / name)
        report["geography"][name] = summary
        geography[name] = data
    events = csv_rows["pakistan_desinventar_cleaned_events.csv"]
    training = csv_rows["pakistan_desinventar_training.csv"]
    recorded = {row["district"] for row in events}
    old = {f["properties"]["shapeName"] for f in geography["app/gis/data/pakistan_districts.geojson"]["features"]}
    display_features = geography["frontend/src/data/pakistan/pakistan_districts.geojson"]["features"]
    modern = {f["properties"]["district"] for f in display_features if f["properties"].get("district")}
    normalized_modern = {normalize(name) for name in modern}
    report["district_matching"] = {
        "recorded_districts": len(recorded), "legacy_geometry_districts": len(old), "display_geometry_districts": len(modern),
        "display_features_without_district_name": sum(not f["properties"].get("district") for f in display_features),
        "recorded_not_in_legacy_geometry": sorted(recorded - old),
        "legacy_districts_without_recorded_events": sorted(old - recorded),
        "recorded_names_without_exact_normalized_display_match": sorted(name for name in recorded if normalize(name) not in normalized_modern),
        "display_districts_without_exact_normalized_event_match": sorted(name for name in modern if normalize(name) not in {normalize(n) for n in recorded}),
        "warning": "Name matches alone do not establish historical boundary equivalence; no crosswalk was applied."}
    positive_dates = {(row["district"], row["date"]) for row in training if row["label"] == "1"}
    report["cleaned_events_not_in_training"] = dict(sorted(Counter(row["date"][:4] for row in events if (row["district"], row["date"]) not in positive_dates).items()))
    report["historical_cache"] = cache_audit(events, geography["app/gis/data/pakistan_districts.geojson"])
    covered = {(row["district"], str(row["year"])) for row in report["historical_cache"]["district_year_coverage"] if row["kind"] == "weather"}
    report["historical_cache"]["recorded_district_years_without_weather_cache"] = [
        {"district": district, "year": year, "recorded_days": count}
        for district, years in report["csv"]["pakistan_desinventar_cleaned_events.csv"]["district_year_rows"].items()
        for year, count in years.items() if (district, year) not in covered]
    report["database_snapshot"] = database_audit()
    report["existing_model_cards"] = {}
    for path in sorted((ROOT / "app/ml/artifacts").glob("*.model-card.json")):
        card = load(path)
        report["existing_model_cards"][path.name] = {key: card[key] for key in ("model_name", "operational_status", "deployment_eligible", "dataset_type", "coverage_status") if key in card}
    # Metadata-only inspection of the existing external exposure integration.
    from app.core.config import get_settings
    configured = get_settings().exposure_dataset_root
    exposure_root = Path(configured).resolve() if configured else ROOT.parent / "flood_model/exposure_infrastructure/datasets/exposure"
    report["external_exposure"] = {"root": str(exposure_root), "exists": exposure_root.exists(), "regions": {}}
    processed = exposure_root / "processed"
    if processed.exists():
        for path in sorted(processed.iterdir()):
            if path.is_dir():
                files = [str(p.relative_to(path)).replace('\\', '/') for p in path.rglob('*') if p.is_file() and p.suffix in {'.tif', '.gpkg'}]
                region = {"data_files": files}
                verification_path = path / "validation_reports/source_verification.json"
                if verification_path.exists():
                    verification = load(verification_path)
                    reference = verification.get("flood_reference", {})
                    region["historical_reference"] = {key: reference[key] for key in ("status", "source", "observation_period", "resolution_m", "limitations") if key in reference}
                report["external_exposure"]["regions"][path.name] = region
    report["readiness"] = {"historical_report_explorer": "usable with source coverage limitations",
                           "annual_flood_probability": "not supported by sampled labels",
                           "validated_ten_year_climate_projection": "future climate inputs absent",
                           "national_future_inundation_or_impact": "not supported by available historical labels and pilot exposure files"}
    output = ROOT / "features/ten-year-dataset-audit.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    cache = report["historical_cache"]
    print(json.dumps({"report": str(output.relative_to(ROOT)), "events": len(events), "training_rows": len(training),
                      "recorded_districts": len(recorded), "legacy_districts_without_records": len(old - recorded),
                      "cache_files": cache["files"],
                      "unmatched_cache_files": len(cache["unmatched_request_hashes"]),
                      "cache_field_statistics": cache["field_statistics"],
                      "weather_district_years": cache["unique_weather_district_years"],
                      "river_district_years": cache["unique_river_district_years"],
                      "geometries_invalid": {name: len(data["invalid_or_empty_geometries"]) for name,data in report["geography"].items()}}, indent=2))


if __name__ == "__main__":
    main()
