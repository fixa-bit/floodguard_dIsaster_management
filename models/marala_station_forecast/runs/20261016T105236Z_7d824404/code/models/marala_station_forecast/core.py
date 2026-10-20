"""Gauge-only causal features, small-data estimators, and portable inference."""
import csv
import hashlib
import json
import math
import re
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import xgboost as xgb

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
CUSEC_TO_CUMECS = 0.028316846592
FEATURES = [
    "log_flow", "log_lag_1d", "log_lag_2d", "log_lag_3d", "log_lag_7d",
    "log_change_1d", "log_change_3d", "log_change_7d", "log_outflow",
    "outflow_inflow_ratio", "log_retained_flow", "log_mean_3d", "relative_std_3d",
    "log_mean_7d", "relative_std_7d", "log_max_7d", "available_days_7d",
    "season_sin", "season_cos", "flow_cumecs", "change_1d_cumecs",
]


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"No records for {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_observations(paths):
    by_day, sources = {}, []
    for path in map(Path, paths):
        if path.suffix == ".csv":
            with path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
        else:
            rows = json.loads(path.read_text(encoding="utf-8"))
        sources.append({"path": str(path.resolve()), "sha256": sha256(path), "rows": len(rows)})
        for row in rows:
            day = date.fromisoformat(row["date"])
            if row["station_id"] != "MARALA" or row["measurement_kind"] != "FFD_reported_observation":
                raise ValueError("Only FFD-reported MARALA measurements may enter this model")
            if datetime.fromisoformat(row["observed_at"]).isoformat() != f"{day}T06:00:00+05:00":
                raise ValueError(f"Unexpected observation time on {day}")
            values = [float(row[key]) for key in ("inflow_cumecs", "outflow_cumecs")]
            if not all(math.isfinite(value) and value >= 0 for value in values):
                raise ValueError(f"Invalid gauge measurement on {day}")
            if urlparse(row["source_url"]).hostname != "ffd.pmd.gov.pk" or not re.fullmatch(r"[a-f0-9]{64}", row["source_sha256"]):
                raise ValueError("Measurement provenance is missing")
            if day in by_day and any(abs(float(by_day[day][key]) - float(row[key])) > 1e-5 for key in ("inflow_cumecs", "outflow_cumecs")):
                raise ValueError(f"Conflicting measurements on {day}; resolve sources explicitly")
            by_day.setdefault(day, {**row, "inflow_cumecs": values[0], "outflow_cumecs": values[1]})
    return dict(sorted(by_day.items())), sources


def feature_row(history, issue_day):
    """No lookup later than issue_day. Missing older dates remain missing."""
    if issue_day not in history or issue_day - timedelta(days=1) not in history:
        raise ValueError("Current and previous-day measured inflows are required")
    current = history[issue_day]
    q = float(current["inflow_cumecs"])
    outflow = float(current["outflow_cumecs"])
    lag = {offset: float(history[issue_day - timedelta(days=offset)]["inflow_cumecs"]) if issue_day - timedelta(days=offset) in history else np.nan for offset in range(1, 8)}
    logq = math.log1p(q)
    loglag = {offset: float(np.log1p(value)) for offset, value in lag.items()}
    summaries = []
    for window in (3, 7):
        values = np.asarray([q] + [lag[offset] for offset in range(1, window)])
        summaries.extend([float(np.log1p(np.mean(values))), float(np.std(values) / (np.mean(values) + 1))])
    angle = 2 * math.pi * issue_day.timetuple().tm_yday / 365.25
    values = [logq, *[loglag[offset] for offset in (1, 2, 3, 7)],
              logq - loglag[1], logq - loglag[3], logq - loglag[7], math.log1p(outflow),
              outflow / (q + 1), math.log1p(max(0, q - outflow)), *summaries,
              float(np.log1p(np.max([q] + [lag[offset] for offset in range(1, 7)]))),
              float(sum(math.isfinite(value) for value in [q] + [lag[offset] for offset in range(1, 7)])),
              math.sin(angle), math.cos(angle), q, q - lag[1]]
    assert len(values) == len(FEATURES)
    return {"issue_date": issue_day.isoformat(), "issued_at": current["observed_at"],
            "current_cumecs": q, "previous_cumecs": lag[1], "features": values,
            "source_url": current["source_url"]}


def build_rows(history, horizon):
    rows, skipped = [], {"missing_previous_day": 0, "missing_target_day": 0}
    for day in history:
        if day - timedelta(days=1) not in history:
            skipped["missing_previous_day"] += 1
            continue
        target_day = day + timedelta(days=horizon)
        if target_day not in history:
            skipped["missing_target_day"] += 1
            continue
        rows.append({**feature_row(history, day), "target_date": target_day.isoformat(),
                     "target_at": history[target_day]["observed_at"],
                     "target_cumecs": float(history[target_day]["inflow_cumecs"]),
                     "target_source_url": history[target_day]["source_url"]})
    return rows, skipped


def matrix(rows):
    return np.asarray([row["features"] for row in rows], dtype=np.float64)


def candidate_specs():
    specs = [{"id": "persistence", "family": "persistence"}, {"id": "training_median", "family": "median"}]
    for damping in (.1, .25, .5, 1.):
        specs.append({"id": f"trend_{damping}", "family": "trend", "damping": damping})
    for target in ("delta", "log_return"):
        for penalty in (.1, 1., 10., 100., 1000.):
            specs.append({"id": f"ridge_{target}_{penalty}", "family": "ridge", "target": target, "penalty": penalty})
        for depth in (1, 2):
            for penalty in (10, 100):
                for child in (5, 15):
                    for rounds in (60, 160):
                        specs.append({"id": f"xgb_{target}_d{depth}_l{penalty}_m{child}_n{rounds}",
                                      "family": "xgboost", "target": target, "depth": depth,
                                      "penalty": penalty, "child": child, "rounds": rounds})
    return specs


def fit(spec, rows, horizon):
    current = np.asarray([row["current_cumecs"] for row in rows])
    actual = np.asarray([row["target_cumecs"] for row in rows])
    model = {"spec": spec, "horizon_days": horizon, "training_rows": len(rows),
             "training_last_target": max(row["target_at"] for row in rows)}
    if spec["family"] == "median":
        model["median"] = float(np.median(actual))
    elif spec["family"] in ("ridge", "xgboost"):
        x = matrix(rows)
        target = actual - current if spec["target"] == "delta" else np.log1p(actual) - np.log1p(current)
        if spec["family"] == "ridge":
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                medians = np.nanmedian(x, axis=0)
            medians = np.where(np.isfinite(medians), medians, 0)
            filled = np.where(np.isfinite(x), x, medians)
            mean, scale = np.mean(filled, axis=0), np.std(filled, axis=0)
            scale = np.where(scale > 1e-8, scale, 1)
            design = np.column_stack([np.ones(len(rows)), (filled - mean) / scale])
            penalty = np.eye(design.shape[1]) * spec["penalty"]
            penalty[0, 0] = 0
            weights = np.linalg.solve(design.T @ design + penalty, design.T @ target)
            model.update(medians=medians.tolist(), mean=mean.tolist(), scale=scale.tolist(), weights=weights.tolist())
        else:
            params = {"objective": "reg:squarederror", "max_depth": spec["depth"], "eta": .05,
                      "min_child_weight": spec["child"], "lambda": spec["penalty"], "seed": 42,
                      "subsample": 1, "colsample_bytree": 1, "nthread": 2, "tree_method": "hist"}
            model["booster"] = xgb.train(params, xgb.DMatrix(x, label=target, feature_names=FEATURES), num_boost_round=spec["rounds"])
    return model


def predict(model, rows):
    spec = model["spec"]
    current = np.asarray([row["current_cumecs"] for row in rows])
    if spec["family"] == "persistence":
        result = current
    elif spec["family"] == "median":
        result = np.full(len(rows), model["median"])
    elif spec["family"] == "trend":
        previous = np.asarray([row["previous_cumecs"] for row in rows])
        result = current + spec["damping"] * model["horizon_days"] * (current - previous)
    else:
        x = matrix(rows)
        if spec["family"] == "ridge":
            filled = np.where(np.isfinite(x), x, model["medians"])
            design = np.column_stack([np.ones(len(rows)), (filled - model["mean"]) / model["scale"]])
            correction = design @ model["weights"]
        else:
            correction = model["booster"].predict(xgb.DMatrix(x, feature_names=FEATURES))
        with np.errstate(over="ignore", invalid="ignore"):
            result = current + correction if spec["target"] == "delta" else np.expm1(np.log1p(current) + correction)
    result = np.maximum(0, result)
    if not np.isfinite(result).all():
        raise ValueError("Nonfinite forecast; candidate rejected")
    return result


def metrics(actual, predicted):
    actual, predicted = np.asarray(actual), np.asarray(predicted)
    error = predicted - actual
    with np.errstate(over="ignore"):
        mse = float(np.mean(error ** 2))
    if not math.isfinite(mse):
        raise ValueError("Nonfinite validation error")
    low = 100000 * CUSEC_TO_CUMECS
    truth, alarm = actual >= low, predicted >= low
    tp, fp, fn = (int(np.sum(mask)) for mask in (truth & alarm, ~truth & alarm, truth & ~alarm))
    peak = int(np.argmax(actual))
    variance = float(np.sum((actual - np.mean(actual)) ** 2))
    peak_error = float(predicted[peak] - actual[peak])
    return {"rows": len(actual), "mae_cumecs": float(np.mean(np.abs(error))), "rmse_cumecs": math.sqrt(mse),
            "bias_cumecs": float(np.mean(error)), "nse": 1 - mse * len(actual) / variance if variance else None,
            "peak_actual_cumecs": float(actual[peak]), "prediction_at_peak_cumecs": float(predicted[peak]),
            "peak_error_percent": 100 * peak_error / float(actual[peak]) if actual[peak] else None,
            "low_flood_threshold_cumecs": low, "flood_events_days": int(np.sum(truth)),
            "hits": tp, "false_alarms": fp, "misses": fn,
            "flood_recall": tp / (tp + fn) if tp + fn else None,
            "flood_precision": tp / (tp + fp) if tp + fp else None}


def save_model(model, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    metadata = {key: value for key, value in model.items() if key != "booster"}
    metadata["features"] = FEATURES
    if "booster" in model:
        model["booster"].save_model(folder / "booster.json")
        metadata["booster_sha256"] = sha256(folder / "booster.json")
    write_json(folder / "model.json", metadata)


def load_model(folder):
    folder = Path(folder)
    model = json.loads((folder / "model.json").read_text(encoding="utf-8"))
    if model["features"] != FEATURES:
        raise ValueError("Model feature schema does not match this code")
    if model["spec"]["family"] == "xgboost":
        if sha256(folder / "booster.json") != model["booster_sha256"]:
            raise ValueError("Model checksum mismatch")
        model["booster"] = xgb.Booster()
        model["booster"].load_model(folder / "booster.json")
    return model
