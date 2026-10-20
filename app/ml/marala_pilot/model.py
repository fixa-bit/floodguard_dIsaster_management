"""Causal daily features, chronological training, honest baselines, and inference."""
import argparse
import csv
import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import xgboost as xgb

from .collect import CUSEC_TO_CUMECS, ROOT, write_csv

FEATURES = [
    "q_t_cumecs", "q_lag_1d_cumecs", "q_lag_2d_cumecs", "q_lag_3d_cumecs", "q_lag_7d_cumecs",
    "q_change_1d_cumecs", "q_change_3d_cumecs", "inflow_minus_outflow_cumecs",
    "rainfall_previous_1d_mm", "rainfall_previous_3d_mm", "rainfall_previous_7d_mm",
    "soil_moisture_m3_m3", "temperature_c", "snow_depth_m", "snow_depth_change_3d_m",
    "day_of_year_sin", "day_of_year_cos",
]


def config():
    return json.loads((ROOT / "config.json").read_text())


def flood_class(cumecs):
    if not math.isfinite(cumecs) or cumecs < 0:
        raise ValueError("Discharge must be finite and nonnegative")
    result = "Below Low"
    for label, threshold in config()["thresholds_cusecs"].items():
        if cumecs >= threshold * CUSEC_TO_CUMECS:
            result = label
    return result


def read_csv(path):
    with Path(path).open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build_rows(observations, weather):
    cfg = config()
    by_day = {}
    for row in observations:
        if row["station_id"] != cfg["station_id"]:
            raise ValueError("Unsupported station in pilot dataset")
        day = date.fromisoformat(row["date"])
        if day in by_day:
            raise ValueError("Duplicate observation date")
        if datetime.fromisoformat(row["observed_at"]).isoformat() != f"{day}T06:00:00+05:00":
            raise ValueError("Observations must be recorded at 06:00 PKT")
        by_day[day] = row
    weather_by_day = {}
    expected_points = {point["name"] for point in cfg["weather_points"]}
    for row in weather:
        point_day = weather_by_day.setdefault(date.fromisoformat(row["date"]), {})
        if row["point"] in point_day:
            raise ValueError("Duplicate weather point/day")
        point_day[row["point"]] = row

    def weather_value(day, field):
        points = weather_by_day.get(day, {})
        if set(points) != expected_points or any(points[name][field] == "" for name in expected_points):
            return float("nan")
        return sum(float(points[name][field]) for name in expected_points) / len(expected_points)

    rows = []
    skipped = {"missing_daily_gauge_history_or_target": 0, "warmup_or_nonseason": 0}
    for day, observation in sorted(by_day.items()):
        if not "07-01" <= day.strftime("%m-%d") <= "09-30":
            skipped["warmup_or_nonseason"] += 1
            continue
        required = [day - timedelta(days=lag) for lag in (1, 2, 3, 7)] + [day + timedelta(days=1)]
        if any(previous not in by_day for previous in required):
            skipped["missing_daily_gauge_history_or_target"] += 1
            continue
        q = float(observation["inflow_cumecs"])
        q_lags = {lag: float(by_day[day - timedelta(days=lag)]["inflow_cumecs"]) for lag in (1, 2, 3, 7)}
        weather_day = day - timedelta(days=1)
        # Yesterday's UTC weather ends at 05:00 PKT, before the 06:00 gauge reading.
        # Reanalysis is retrospective context, not an archived real-time forecast.
        rain = {lag: sum(weather_value(day - timedelta(days=offset), "rainfall_mm")
                         for offset in range(1, lag + 1)) for lag in (1, 3, 7)}
        snow = weather_value(weather_day, "snow_depth_m")
        target = by_day[day + timedelta(days=1)]
        angle = 2 * math.pi * day.timetuple().tm_yday / 365.25
        values = [
            q, *[q_lags[lag] for lag in (1, 2, 3, 7)], q - q_lags[1], q - q_lags[3],
            q - float(observation["outflow_cumecs"]), rain[1], rain[3], rain[7],
            weather_value(weather_day, "soil_moisture_m3_m3"), weather_value(weather_day, "temperature_c"),
            snow, snow - weather_value(weather_day - timedelta(days=3), "snow_depth_m"), math.sin(angle), math.cos(angle),
        ]
        row = {"station_id": cfg["station_id"], "issued_at": observation["observed_at"],
               "target_at": target["observed_at"], "weather_latest_date_utc": weather_day.isoformat(),
               "horizon_hours": cfg["horizon_hours"], **dict(zip(FEATURES, values, strict=True)),
               "target_discharge_cumecs": float(target["inflow_cumecs"]),
               "target_flood_class": flood_class(float(target["inflow_cumecs"])),
               "observation_source_url": observation["source_url"], "target_source_url": target["source_url"]}
        row.update({name: "" for name in cfg["optional_unavailable_features"]})
        rows.append(row)
    return rows, skipped


def split_rows(rows):
    cfg = config()
    train_end = date.fromisoformat(cfg["training_end"])
    val_end = date.fromisoformat(cfg["validation_end"])
    groups = {"train": [], "validation": [], "test": []}
    for row in rows:
        issued = datetime.fromisoformat(row["issued_at"]).date()
        target = datetime.fromisoformat(row["target_at"]).date()
        if issued <= train_end and target <= train_end:
            groups["train"].append(row)
        elif train_end < issued <= val_end and target <= val_end:
            groups["validation"].append(row)
        elif issued > val_end:
            groups["test"].append(row)
    if any(len(group) < 10 for group in groups.values()):
        raise ValueError("Need at least 10 rows in each chronological split")
    for earlier, later in (("train", "validation"), ("validation", "test")):
        if max(row["target_at"] for row in groups[earlier]) >= min(row["issued_at"] for row in groups[later]):
            raise ValueError("Forecast labels overlap the next split's issue time")
    return groups


def matrix(rows):
    return np.asarray([[float(row[name]) if row[name] not in (None, "") else np.nan for name in FEATURES] for row in rows], dtype=np.float32)


def metrics(actual, predicted):
    error = predicted - actual
    denominator = float(np.sum((actual - np.mean(actual)) ** 2))
    low = config()["thresholds_cusecs"]["Low"] * CUSEC_TO_CUMECS
    truth, positive = actual >= low, predicted >= low
    tp, fp, fn, tn = (int(np.sum(mask)) for mask in (truth & positive, ~truth & positive, truth & ~positive, ~truth & ~positive))
    return {
        "rows": len(actual), "mae_cumecs": float(np.mean(np.abs(error))),
        "rmse_cumecs": float(np.sqrt(np.mean(error ** 2))), "bias_cumecs": float(np.mean(error)),
        "nash_sutcliffe_efficiency": 1 - float(np.sum(error ** 2)) / denominator if denominator else None,
        "flood_threshold_confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "flood_precision": tp / (tp + fp) if tp + fp else None,
        "flood_recall": tp / (tp + fn) if tp + fn else None,
        "flood_class_accuracy": float(np.mean([flood_class(float(a)) == flood_class(float(p)) for a, p in zip(actual, predicted, strict=True)])),
    }


def train(data_dir=ROOT / "data", output_dir=ROOT / "artifacts"):
    data_dir, output_dir = Path(data_dir), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows, skipped = build_rows(read_csv(data_dir / "observations.csv"), read_csv(data_dir / "weather_daily.csv"))
    groups = split_rows(rows)
    split_lookup = {row["issued_at"]: name for name, group in groups.items() for row in group}
    for row in rows:
        row["split"] = split_lookup.get(row["issued_at"], "purged_boundary")
    write_csv(data_dir / "training.csv", rows)
    datasets = {}
    for name, group in groups.items():
        x = matrix(group)
        # Learn a correction to persistence, rather than make trees extrapolate flow levels.
        y = np.asarray([row["target_discharge_cumecs"] - row["q_t_cumecs"] for row in group], dtype=np.float32)
        datasets[name] = xgb.DMatrix(x, label=y, feature_names=FEATURES)
    parameters = {"objective": "reg:squarederror", "eval_metric": "rmse", "max_depth": 2,
                  "eta": 0.03, "min_child_weight": 5, "lambda": 10, "subsample": 1,
                  "colsample_bytree": 1, "seed": 42, "nthread": 2, "tree_method": "hist"}
    booster = xgb.train(parameters, datasets["train"], num_boost_round=250,
                        evals=[(datasets["validation"], "validation")], early_stopping_rounds=25, verbose_eval=False)
    # Save only the selected trees, so normal inference matches the evaluated model.
    booster = booster[:booster.best_iteration + 1]
    model_path = output_dir / "marala_next_day.xgb.json"
    booster.save_model(model_path)
    scores, predictions = {}, []
    for name in ("validation", "test"):
        group = groups[name]
        current = np.asarray([row["q_t_cumecs"] for row in group])
        actual = np.asarray([row["target_discharge_cumecs"] for row in group])
        predicted = np.maximum(0, current + booster.predict(datasets[name]))
        persistence = current
        trend = np.maximum(0, current + np.asarray([row["q_change_1d_cumecs"] for row in group]))
        scores[name] = {"xgboost": metrics(actual, predicted), "persistence": metrics(actual, persistence),
                        "linear_trend": metrics(actual, trend)}
        for row, forecast in zip(group, predicted, strict=True):
            predictions.append({"station_id": row["station_id"], "issued_at": row["issued_at"],
                                "target_at": row["target_at"], "split": name,
                                "actual_cumecs": row["target_discharge_cumecs"], "predicted_cumecs": float(forecast),
                                "persistence_cumecs": row["q_t_cumecs"],
                                "predicted_class": flood_class(float(forecast)), "actual_class": row["target_flood_class"]})
    write_csv(output_dir / "holdout_predictions.csv", predictions)
    metadata = {}
    for name, group in groups.items():
        counts = {}
        for row in group:
            counts[row["target_flood_class"]] = counts.get(row["target_flood_class"], 0) + 1
        metadata[name] = {"rows": len(group), "first_issue": group[0]["issued_at"], "last_issue": group[-1]["issued_at"],
                          "last_target": group[-1]["target_at"], "target_classes": counts}
    test = scores["test"]
    beats_persistence = test["xgboost"]["rmse_cumecs"] < test["persistence"]["rmse_cumecs"]
    card = {
        "model_name": "marala_daily_riverine_pilot_v1", "schema_version": 1,
        "trained_at": datetime.now(timezone.utc).isoformat(), "station": config(),
        "purpose": "24-hour-ahead measured station inflow regression, followed by FFD discharge class; not inundation mapping",
        "dataset_type": "real_FFD_gauge_observations_with_ERA5_Land_reanalysis_covariates",
        "features": FEATURES, "optional_features_not_trained": config()["optional_unavailable_features"],
        "feature_missing_counts": {feature: sum(not math.isfinite(float(row[feature])) for row in rows) for feature in FEATURES},
        "feature_availability": "All weather windows end yesterday UTC, before issue time. Reanalysis has retrospective latency; hindcast research only.",
        "splits": metadata, "skipped_rows": skipped, "boundary_rows_purged": sum(row["split"] == "purged_boundary" for row in rows),
        "metrics": scores, "test_beats_persistence_rmse": beats_persistence,
        "deployment_eligible": False,
        "status": "research_candidate_requires_external_validation" if beats_persistence else "research_baseline_does_not_beat_persistence",
        "parameters": parameters, "boosting_rounds": booster.num_boosted_rounds(), "xgboost_version": xgb.__version__,
        "feature_gain": booster.get_score(importance_type="gain"),
        "dataset_sha256": hashlib.sha256((data_dir / "training.csv").read_bytes()).hexdigest(),
        "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "limitations": [
            "Only two short monsoon seasons; one station; observations rounded to 0.1 thousand cusecs.",
            "ERA5-Land is modeled reanalysis, not local rain-gauge observations or archived issued forecasts.",
            "Three weather points are a sparse upstream proxy, not a delineated basin mean.",
            "No measured Akhnur discharge, reservoir releases, gauge heights, or subdaily hydrographs are supplied.",
            "Gauge gaps are not interpolated; source/parser exclusions are recorded in data/sources.json.",
            "Flood classes describe discharge thresholds, not calibrated flood probabilities or mapped flood extent.",
            "No operational feed replacement; live predictions require availability-aligned weather and independent validation.",
        ],
    }
    (output_dir / "model-card.json").write_text(json.dumps(card, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    example = predict(rows[-1], model_path)
    example.update(example_kind="historical_holdout_prediction", observed_target_cumecs=rows[-1]["target_discharge_cumecs"])
    (output_dir / "example_prediction.json").write_text(json.dumps(example, indent=2) + "\n", encoding="utf-8")
    return card


def predict(row, model_path=ROOT / "artifacts/marala_next_day.xgb.json"):
    if row["station_id"] != config()["station_id"] or int(row["horizon_hours"]) != 24:
        raise ValueError("Pilot supports MARALA / 24 hours only")
    issued = datetime.fromisoformat(row["issued_at"])
    if issued.tzinfo is None:
        raise ValueError("Issue time must include a timezone")
    if date.fromisoformat(row["weather_latest_date_utc"]) >= issued.astimezone(timezone.utc).date():
        raise ValueError("Weather must end before the issue day's UTC midnight")
    values = matrix([row])
    if not np.isfinite(values[0, :8]).all() or values[0, 0] < 0:
        raise ValueError("Observed discharge features are required and must be finite")
    if np.isinf(values).any():
        raise ValueError("Infinite covariates are invalid")
    booster = xgb.Booster()
    booster.load_model(model_path)
    q = max(0, float(row["q_t_cumecs"]) + float(booster.predict(xgb.DMatrix(values, feature_names=FEATURES))[0]))
    return {"station_id": "MARALA", "river": "Chenab", "issued_at": issued.isoformat(),
            "target_at": (issued + timedelta(hours=24)).isoformat(), "horizon_hours": 24,
            "predicted_discharge_cumecs": q, "predicted_discharge_cusecs": q / CUSEC_TO_CUMECS,
            "flood_class": flood_class(q), "model_name": "marala_daily_riverine_pilot_v1", "research_only": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts")
    parser.add_argument("--predict-json", type=Path, help="Predict from a JSON object with station, issue time, horizon, and named features")
    args = parser.parse_args()
    if args.predict_json:
        print(json.dumps(predict(json.loads(args.predict_json.read_text()), args.output_dir / "marala_next_day.xgb.json"), indent=2))
    else:
        card = train(args.data_dir, args.output_dir)
        print(json.dumps({"status": card["status"], "splits": card["splits"], "metrics": card["metrics"]}, indent=2))
