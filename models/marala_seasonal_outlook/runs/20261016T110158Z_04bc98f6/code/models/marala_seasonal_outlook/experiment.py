"""Train and replay a daily, 365-day research outlook on an archived modeled reach."""
import argparse
import calendar
import csv
import json
import math
import shutil
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import xgboost as xgb

from models.marala_station_forecast.core import sha256, write_csv, write_json
from models.marala_station_forecast.validate import verify_inventory

HERE = Path(__file__).resolve().parent
FEATURES = ["lead_fraction", "log_current", "log_previous_7d_mean", "log_previous_30d_mean",
            "log_previous_90d_mean", "log_previous_year_target", "log_previous_year_target_7d_mean",
            "current_7d_log_change", "current_30d_log_change"] + [
                f"target_{fn}_{harmonic}" for harmonic in (1, 2, 3) for fn in ("sin", "cos")]


def load_history(raw, manifest):
    meta = json.loads(Path(manifest).read_text(encoding="utf-8"))
    if sha256(raw) != meta["response_sha256"]:
        raise ValueError("Provider source checksum changed")
    payload = json.loads(Path(raw).read_text(encoding="utf-8"))
    if abs(payload["latitude"] - 32.675) > .001 or abs(payload["longitude"] - 74.425) > .001:
        raise ValueError("Different modeled river reach")
    if payload["utc_offset_seconds"] != 0 or payload["daily_units"]["river_discharge"] != "m\u00b3/s":
        raise ValueError("Unexpected provider time basis or discharge units")
    history, ledger = {}, []
    last = None
    for stamp, value in zip(payload["daily"]["time"], payload["daily"]["river_discharge"], strict=True):
        day = date.fromisoformat(stamp)
        if last and day != last + timedelta(days=1):
            raise ValueError("Provider dates are not consecutive")
        last = day
        if value is not None:
            if not math.isfinite(value) or value < 0:
                raise ValueError("Invalid provider discharge")
            history[day] = float(value)
        ledger.append({"date": stamp, "daily_mean_cumecs": value if value is not None else "",
                       "status": "modeled_value" if value is not None else "missing_not_interpolated"})
    return history, ledger, meta


def row_at(history, origin, lead):
    if not 1 <= lead <= 365:
        raise ValueError("Supported direct leads are 1 through 365 days")
    target = origin + timedelta(days=lead)
    previous_year = target - timedelta(days=365)
    # Every lookup is at or before the origin, including seasonal reference dates.
    def q(day):
        if day > origin:
            raise ValueError("Future feature access")
        return history[day]
    def logmean(end, count):
        return math.log1p(sum(q(end - timedelta(days=i)) for i in range(count)) / count)
    logq = math.log1p(q(origin))
    phase = 2 * math.pi * (target - date(target.year, 1, 1)).days / (366 if calendar.isleap(target.year) else 365)
    features = [lead / 365, logq, logmean(origin, 7), logmean(origin, 30), logmean(origin, 90),
                math.log1p(q(previous_year)), logmean(previous_year, 7),
                logq - math.log1p(q(origin - timedelta(days=7))),
                logq - math.log1p(q(origin - timedelta(days=30)))]
    features += [fn(phase * harmonic) for harmonic in (1, 2, 3) for fn in (math.sin, math.cos)]
    return {"origin": origin.isoformat(), "target": target.isoformat(), "lead": lead,
            "current": q(origin), "seasonal": q(previous_year), "features": features}


def make_rows(history):
    rows = []
    for origin in history:
        if origin.day != calendar.monthrange(origin.year, origin.month)[1]:
            continue
        # Full one-year history is required; gaps are never filled.
        if any(origin - timedelta(days=i) not in history for i in range(371)):
            continue
        for lead in range(1, 366):
            target = origin + timedelta(days=lead)
            if target in history:
                rows.append({**row_at(history, origin, lead), "actual": history[target]})
    return rows


def partitions(rows, cfg):
    groups = {name: [] for name in ("train", "validation", "test")}
    for row in rows:
        issue_year, target_year = int(row["origin"][:4]), int(row["target"][:4])
        if target_year <= cfg["training_last_year"]:
            groups["train"].append(row)
        elif issue_year in cfg["validation_years"] and target_year in cfg["validation_years"]:
            groups["validation"].append(row)
        elif issue_year in cfg["test_years"] and target_year in cfg["test_years"]:
            groups["test"].append(row)
    for before, after in (("train", "validation"), ("validation", "test")):
        if not groups[before] or not groups[after] or max(r["target"] for r in groups[before]) >= min(r["origin"] for r in groups[after]):
            raise ValueError("Evaluation partitions overlap or are empty")
    return groups


def specs():
    result = [{"id": name, "family": name} for name in ("seasonal_naive", "persistence", "seasonal_climatology")]
    for penalty in (1, 10, 100, 1000):
        result.append({"id": f"ridge_log_correction_{penalty}", "family": "ridge", "penalty": penalty})
    for depth in (2, 3):
        for penalty in (10, 100):
            for rounds in (60, 160):
                result.append({"id": f"xgb_log_correction_d{depth}_p{penalty}_n{rounds}", "family": "xgboost",
                               "depth": depth, "penalty": penalty, "rounds": rounds})
    return result


def fit(spec, rows):
    model = {"spec": spec, "features": FEATURES, "training_last_target": max(r["target"] for r in rows), "training_rows": len(rows)}
    family = spec["family"]
    if family in ("seasonal_naive", "persistence"):
        return model
    x = np.asarray([r["features"] for r in rows])
    actual = np.asarray([r["actual"] for r in rows])
    if family == "seasonal_climatology":
        # Fit smooth annual harmonic means, weighting each target date once.
        unique = {r["target"]: r for r in rows}
        xx = np.asarray([[1] + r["features"][-6:] for r in unique.values()])
        yy = np.asarray([r["actual"] for r in unique.values()])
        model["weights"] = np.linalg.lstsq(xx, yy, rcond=None)[0].tolist()
        return model
    target = np.log1p(actual) - np.log1p([r["seasonal"] for r in rows])
    if family == "ridge":
        mean, scale = x.mean(axis=0), x.std(axis=0)
        scale = np.where(scale > 1e-8, scale, 1)
        design = np.column_stack([np.ones(len(rows)), (x - mean) / scale])
        penalty = np.eye(design.shape[1]) * spec["penalty"]
        penalty[0, 0] = 0
        weights = np.linalg.solve(design.T @ design + penalty, design.T @ target)
        model.update(mean=mean.tolist(), scale=scale.tolist(), weights=weights.tolist())
    else:
        model["booster"] = xgb.train({"objective": "reg:squarederror", "max_depth": spec["depth"], "eta": .05,
                                     "lambda": spec["penalty"], "min_child_weight": 100, "seed": 42,
                                     "nthread": 2, "tree_method": "hist"},
                                    xgb.DMatrix(x, label=target, feature_names=FEATURES), num_boost_round=spec["rounds"])
    return model


def predict(model, rows):
    family = model["spec"]["family"]
    if family == "persistence":
        values = np.asarray([r["current"] for r in rows])
    elif family == "seasonal_naive":
        values = np.asarray([r["seasonal"] for r in rows])
    else:
        x = np.asarray([r["features"] for r in rows])
        if family == "seasonal_climatology":
            values = np.column_stack([np.ones(len(rows)), x[:, -6:]]) @ model["weights"]
        else:
            correction = (np.column_stack([np.ones(len(rows)), (x - model["mean"]) / model["scale"]]) @ model["weights"]
                          if family == "ridge" else model["booster"].predict(xgb.DMatrix(x, feature_names=FEATURES)))
            values = np.expm1(np.log1p([r["seasonal"] for r in rows]) + correction)
    values = np.maximum(values, 0)
    if not np.isfinite(values).all():
        raise ValueError("Nonfinite forecast")
    return values


def save(model, folder):
    folder.mkdir(parents=True, exist_ok=True)
    meta = {k: v for k, v in model.items() if k != "booster"}
    if "booster" in model:
        model["booster"].save_model(folder / "booster.json")
        meta["booster_sha256"] = sha256(folder / "booster.json")
    write_json(folder / "model.json", meta)


def load(folder):
    model = json.loads((folder / "model.json").read_text(encoding="utf-8"))
    if model["features"] != FEATURES:
        raise ValueError("Feature schema changed")
    if model["spec"]["family"] == "xgboost":
        if sha256(folder / "booster.json") != model["booster_sha256"]:
            raise ValueError("Booster checksum changed")
        model["booster"] = xgb.Booster()
        model["booster"].load_model(folder / "booster.json")
    return model


def metric(actual, values):
    error = np.asarray(values) - np.asarray(actual)
    return {"rows": len(error), "rmse_cumecs": float(np.sqrt(np.mean(error ** 2))),
            "mae_cumecs": float(np.mean(np.abs(error))), "bias_cumecs": float(error.mean())}


def outlook(history, model):
    origin = max(history)
    if model["training_last_target"] > origin.isoformat():
        raise ValueError("Inference origin precedes fitting labels")
    rows = [row_at(history, origin, lead) for lead in range(1, 366)]
    values = predict(model, rows)
    daily = [{"date": r["target"], "lead_days": r["lead"], "predicted_daily_mean_cumecs": float(value)} for r, value in zip(rows, values, strict=True)]
    monthly = []
    for month in sorted({r["date"][:7] for r in daily}):
        group = [r for r in daily if r["date"].startswith(month)]
        year, number = map(int, month.split("-"))
        monthly.append({"month": month, "mean_of_forecast_daily_means_cumecs": float(np.mean([r["predicted_daily_mean_cumecs"] for r in group])),
                        "forecast_days": len(group), "calendar_days": calendar.monthrange(year, number)[1],
                        "complete_calendar_month": len(group) == calendar.monthrange(year, number)[1]})
    return {"origin": origin.isoformat(), "maximum_horizon_days": 365,
            "target_kind": "modeled_reach_daily_mean_NOT_instantaneous_gauge_inflow", "research_only": True,
            "model": model["spec"], "daily": daily, "monthly": monthly,
            "limitation": "Statistical seasonal outlook without future rainfall, upstream releases or event timing. Not a calibrated flood warning."}


def train():
    cfg = json.loads((HERE / "config.json").read_text())
    manifest = HERE / "data/download_manifest_20261015.json"
    raw = HERE / "data/provider_daily_20261015.json"
    run = HERE / "runs" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8])
    (run / "data").mkdir(parents=True, exist_ok=False)
    shutil.copy2(raw, run / "data" / raw.name)
    shutil.copy2(manifest, run / "data" / manifest.name)
    code = run / "code/models/marala_seasonal_outlook"
    code.mkdir(parents=True)
    for source in list(HERE.glob("*.py")) + [HERE / "config.json", HERE / "README.md"]:
        shutil.copy2(source, code / source.name)
    # Shared helpers are also retained so this run can be replayed independently.
    shared = run / "code/models/marala_station_forecast"
    shutil.copytree(HERE.parent / "marala_station_forecast", shared,
                    ignore=shutil.ignore_patterns("data", "artifacts", "runs", "evidence_cache", "__pycache__", "LATEST_RUN.json"))
    (run / "code/requirements.txt").write_text(f"numpy=={np.__version__}\nxgboost=={xgb.__version__}\n", encoding="utf-8")
    history, ledger, source = load_history(run / "data" / raw.name, run / "data" / manifest.name)
    write_csv(run / "data/daily_source_ledger.csv", ledger)
    rows = make_rows(history)
    groups = partitions(rows, cfg)
    split = {id(row): name for name, group in groups.items() for row in group}
    write_csv(run / "data/training_rows.csv", [{"origin": r["origin"], "target": r["target"], "lead_days": r["lead"],
               "split": split.get(id(r), "later_refit_or_purged"), "actual_cumecs": r["actual"],
               **dict(zip(FEATURES, r["features"], strict=True))} for r in rows])
    candidates = specs()
    out = run / "artifacts"
    write_json(out / "predeclared_candidates.json", candidates)
    validation_actual = [r["actual"] for r in groups["validation"]]
    ranked = []
    for spec in candidates:
        model = fit(spec, groups["train"])
        scores = metric(validation_actual, predict(model, groups["validation"]))
        ranked.append({"spec": spec, "validation": scores})
        print(f"Validation {spec['id']}: RMSE {scores['rmse_cumecs']:.2f}", flush=True)
    ranked.sort(key=lambda r: (r["validation"]["rmse_cumecs"], r["validation"]["mae_cumecs"]))
    selected = ranked[0]
    learned = next(r for r in ranked if r["spec"]["family"] in ("ridge", "xgboost"))
    write_json(out / "selection.json", {"champion": selected, "best_learned": learned, "test_used_for_selection": False, "leaderboard": ranked})
    # Selection has been persisted before computing any held-out score.
    roles = {"champion": selected["spec"], "best_learned": learned["spec"],
             "seasonal_naive": candidates[0], "persistence": candidates[1], "seasonal_climatology": candidates[2]}
    scores, predicted = {}, {}
    for role, spec in roles.items():
        model = fit(spec, groups["train"] + groups["validation"])
        save(model, out / "evaluation_models" / role)
        values = predict(load(out / "evaluation_models" / role), groups["test"])
        predicted[role] = values
        scores[role] = metric([r["actual"] for r in groups["test"]], values)
        scores[role]["by_lead_window"] = {}
        for start, end in ((1, 30), (31, 90), (91, 180), (181, 365)):
            indices = [i for i, r in enumerate(groups["test"]) if start <= r["lead"] <= end]
            scores[role]["by_lead_window"][f"{start}-{end}"] = metric([groups["test"][i]["actual"] for i in indices], values[indices])
        print(f"Held-out {role}: RMSE {scores[role]['rmse_cumecs']:.2f}", flush=True)
    write_csv(out / "holdout_predictions_2018_2021.csv", [{"origin": r["origin"], "target": r["target"], "lead_days": r["lead"],
                "actual_cumecs": r["actual"], **{role + "_cumecs": float(values[i]) for role, values in predicted.items()}}
               for i, r in enumerate(groups["test"])])
    for role in ("champion", "best_learned"):
        final = fit(roles[role], rows)
        save(final, out / "models" / role)
    forecast = outlook(history, load(out / "models/champion"))
    write_json(out / "outlook_365_days.json", forecast)
    write_csv(out / "daily_forecast.csv", forecast["daily"])
    write_csv(out / "monthly_forecast.csv", forecast["monthly"])
    write_json(out / "model-card.json", {"config": cfg, "source": source, "numpy": np.__version__, "xgboost": xgb.__version__,
               "available_modeled_days": len(history), "first_available_day": min(history).isoformat(), "last_available_day": max(history).isoformat(),
               "missing_days": len(ledger) - len(history), "selection": selected, "test": scores,
               "splits": {name: {"rows": len(group), "first_origin": min(r["origin"] for r in group), "last_target": max(r["target"] for r in group)} for name, group in groups.items()},
               "deployment_eligible": False,
               "limitations": ["Target and test truth are GloFAS modeled reach daily means, never real gauge readings.",
                               "Historic modeled values may be retrospective reanalysis; rolling tests do not prove real-time input availability.",
                               "Historical provider model versions may differ; the response has no per-day version metadata.",
                               "Overlapping monthly origins share target days; rows are correlated, not independent flood events.",
                               "Long-lead event timing cannot be inferred from past discharge alone; output is a seasonal statistical outlook.",
                               "365 values do not imply 365-day weather or flood-event prediction skill.",
                               "Final refits include data after the holdout period and have no new independent evaluation."]})
    lines = ["# 365-day modeled-reach outlook", "", "One daily mean estimate per date, for the next 365 days. Research only.", "",
             "These targets are modeled GloFAS reach discharge, not measured Marala inflow or 06:00 instantaneous readings.", "",
             f"Forecast: {forecast['daily'][0]['date']} through {forecast['daily'][-1]['date']}. Selected: {selected['spec']['id']}.", "",
             "Fit candidates through 2013, select on 2014-2017, freeze selection, refit through 2017, evaluate 2018-2021.", "",
             "| Candidate role | Held-out RMSE (m3/s) | MAE (m3/s) |", "|---|---:|---:|"]
    lines += [f"| {role} | {s['rmse_cumecs']:.2f} | {s['mae_cumecs']:.2f} |" for role, s in scores.items()]
    lines += ["", "Do not choose a new candidate using this final test. Compare errors by lead window in model-card.json.", "",
              "Daily forecasts are aggregated into monthly averages, with partial first/last months explicitly flagged.",
              "No artificial noise, daily-to-subdaily interpolation, or gauge/proxy mixing is used.", "",
              "The dashboard feed has not been replaced. This does not establish operational gauge or flood-warning accuracy.", ""]
    (out / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    files = {str(p.relative_to(run)).replace("\\", "/"): {"sha256": sha256(p), "bytes": p.stat().st_size} for p in sorted(run.rglob("*")) if p.is_file()}
    write_json(run / "RUN_MANIFEST.json", {"run_id": run.name, "files": files, "policy": "Do not edit sealed runs. New inputs or experiments require a new run."})
    write_json(HERE / "LATEST_RUN.json", {"path": str(run.relative_to(HERE)).replace("\\", "/"), "manifest_sha256": sha256(run / "RUN_MANIFEST.json")})
    shutil.copytree(out, HERE / "artifacts", dirs_exist_ok=True)
    print(f"Sealed run: {run}", flush=True)
    return run


def validate(run):
    count = verify_inventory(run)
    history, _, _ = load_history(run / "data/provider_daily_20261015.json", run / "data/download_manifest_20261015.json")
    cfg = json.loads((run / "code/models/marala_seasonal_outlook/config.json").read_text())
    test = partitions(make_rows(history), cfg)["test"]
    with (run / "artifacts/holdout_predictions_2018_2021.csv").open(encoding="utf-8", newline="") as handle:
        saved = list(csv.DictReader(handle))
    for row, expected in zip(test, saved, strict=True):
        if row["origin"] != expected["origin"] or row["target"] != expected["target"] or row["lead"] != int(expected["lead_days"]):
            raise ValueError("Held-out dates changed")
        np.testing.assert_allclose(row["actual"], float(expected["actual_cumecs"]), rtol=1e-10)
    for role in ("champion", "best_learned", "seasonal_naive", "persistence", "seasonal_climatology"):
        model = load(run / "artifacts/evaluation_models" / role)
        if model["training_last_target"] >= test[0]["origin"]:
            raise ValueError("Evaluation fit contains future labels")
        np.testing.assert_allclose(predict(model, test), [float(r[role + "_cumecs"]) for r in saved], rtol=1e-7, atol=1e-7)
    forecast = outlook(history, load(run / "artifacts/models/champion"))
    retained = json.loads((run / "artifacts/outlook_365_days.json").read_text())
    if forecast != retained:
        raise ValueError("Forecast replay changed")
    return {"verified_files": count, "replayed_holdout_rows": len(test), "daily_forecasts": len(forecast["daily"]), "status": "passed"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["train", "validate", "predict"])
    parser.add_argument("--run", type=Path)
    args = parser.parse_args()
    if args.action == "train":
        train()
    else:
        run = args.run or HERE / json.loads((HERE / "LATEST_RUN.json").read_text())["path"]
        if args.action == "validate":
            print(json.dumps(validate(run), indent=2))
        else:
            history, _, _ = load_history(run / "data/provider_daily_20261015.json", run / "data/download_manifest_20261015.json")
            print(json.dumps(outlook(history, load(run / "artifacts/models/champion")), indent=2))
