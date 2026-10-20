"""Train and run a compact monthly Marala/Chenab flow outlook."""
import argparse
import calendar
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
import xgboost as xgb

from .collect import ROOT, write_csv
from .model import config, read_csv

DATA = ROOT / "data"
ARTIFACTS = ROOT / "artifacts/seasonal"
GLOFAS = "https://flood-api.open-meteo.com/v1/flood"
WEATHER = "https://archive-api.open-meteo.com/v1/archive"
FEATURES = [
    "flow_anomaly_current_cumecs", "flow_anomaly_previous_month_cumecs",
    "flow_anomaly_previous_year_cumecs", "flow_change_1m_cumecs",
    "rainfall_previous_1m_mm", "rainfall_previous_3m_mm",
    "snowfall_previous_1m_cm", "temperature_anomaly_c",
]
HORIZONS = (1, 2, 3, 4)


def month_add(month, steps):
    year, number = map(int, month.split("-"))
    index = year * 12 + number - 1 + steps
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def collect(data_dir=DATA, start="2000-01-01", end="2021-12-31"):
    """Download compact monthly GloFAS and ERA5 features; retain sources and hashes."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    cfg = config()
    provenance, payloads = [], {}
    with httpx.Client(timeout=180, follow_redirects=True) as client:
        def fetch(name, url, params):
            response = client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
            provenance.append({"name": name, "url": str(response.url),
                               "response_sha256": hashlib.sha256(response.content).hexdigest(),
                               "grid_latitude": payload["latitude"], "grid_longitude": payload["longitude"]})
            return payload

        # This coordinate is the nearest modeled Chenab reach, not the physical gauge.
        river = fetch("GloFAS daily modeled discharge", GLOFAS, {
            "latitude": 32.675, "longitude": 74.425, "start_date": start,
            "end_date": end, "daily": "river_discharge", "cell_selection": "nearest", "timezone": "GMT",
        })
        if abs(river["latitude"] - 32.675) > 0.03 or abs(river["longitude"] - 74.425) > 0.03:
            raise ValueError("Unexpected GloFAS grid cell near Marala")
        payloads["glofas"] = river
        for point in cfg["weather_points"]:
            # ERA5-Land has no precipitation variable. ERA5 supplies consistent rain/snow.
            weather = fetch(f"ERA5 weather {point['name']}", WEATHER, {
                "latitude": point["latitude"], "longitude": point["longitude"],
                "start_date": start, "end_date": end,
                "daily": "precipitation_sum,temperature_2m_mean,snowfall_sum",
                "models": "era5", "timezone": "UTC",
            })
            if not weather["daily"]["time"]:
                raise ValueError(f"No ERA5 weather returned for {point['name']}")
            payloads[point["name"]] = weather

    discharge = dict(zip(river["daily"]["time"], river["daily"]["river_discharge"], strict=True))
    weather_by_point = {
        point["name"]: {
            day: {key: payload["daily"][key][i] for key in
                  ("precipitation_sum", "temperature_2m_mean", "snowfall_sum")}
            for i, day in enumerate(payload["daily"]["time"])
        }
        for point, payload in ((p, payloads[p["name"]]) for p in cfg["weather_points"])
    }
    months = sorted({day[:7] for day in discharge})
    rows, omitted = [], []
    for month in months:
        year, number = map(int, month.split("-"))
        days = [f"{month}-{day:02d}" for day in range(1, calendar.monthrange(year, number)[1] + 1)]
        if any(day not in discharge or discharge[day] is None or discharge[day] < 0 for day in days):
            omitted.append({"month": month, "reason": "incomplete GloFAS daily flow"})
            continue
        if any(day not in weather_by_point[point["name"]]
               or any(weather_by_point[point["name"]][day][key] is None
                      for key in ("precipitation_sum", "temperature_2m_mean", "snowfall_sum"))
               for point in cfg["weather_points"] for day in days):
            omitted.append({"month": month, "reason": "incomplete ERA5 daily weather"})
            continue
        point_weather = [weather_by_point[p["name"]] for p in cfg["weather_points"]]
        point_count = len(point_weather)
        rows.append({
            "station_id": "MARALA", "river": "Chenab", "month": month,
            "flow_mean_cumecs": sum(discharge[d] for d in days) / len(days),
            "flow_max_daily_mean_cumecs": max(discharge[d] for d in days),
            "rainfall_mm": sum(sum(point[d]["precipitation_sum"] for d in days) for point in point_weather) / point_count,
            "temperature_c": sum(sum(point[d]["temperature_2m_mean"] for d in days) for point in point_weather) / (point_count * len(days)),
            "snowfall_cm": sum(sum(point[d]["snowfall_sum"] for d in days) for point in point_weather) / point_count,
            "discharge_source": "GloFAS_modeled_reanalysis_not_gauge",
            "weather_source": "ERA5_reanalysis_three_point_upstream_proxy",
        })
    if not rows:
        raise ValueError("No complete monthly rows were collected")
    write_csv(data_dir / "seasonal_monthly.csv", rows)
    manifest = {
        "retrieved_at": datetime.now(timezone.utc).isoformat(), "station_id": "MARALA",
        "rows": len(rows), "first_month": rows[0]["month"], "last_month": rows[-1]["month"],
        "omitted_months": omitted, "requests": provenance,
        "reach": {"latitude": river["latitude"], "longitude": river["longitude"]},
        "target_definition": "Complete-calendar-month mean daily GloFAS modeled river discharge near Marala; not measured headworks flow",
        "weather_definition": "ERA5 daily precipitation, temperature, and snowfall averaged across three upstream sample points",
        "attribution": "GloFAS/Copernicus Emergency Management Service; ERA5/Copernicus Climate Change Service; Open-Meteo API CC BY 4.0",
        "documentation": ["https://open-meteo.com/en/docs/flood-api", "https://open-meteo.com/en/docs/historical-weather-api"],
    }
    (data_dir / "seasonal-sources.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def climatology(history, months):
    flow, temperature = {}, {}
    for month_number in range(1, 13):
        values = [float(row["flow_mean_cumecs"]) for month, row in history.items()
                  if int(month[-2:]) == month_number and month <= months[-1]]
        temps = [float(row["temperature_c"]) for month, row in history.items()
                 if int(month[-2:]) == month_number and month <= months[-1]]
        if not values or not temps:
            raise ValueError(f"Training history does not cover calendar month {month_number}")
        flow[month_number], temperature[month_number] = float(np.mean(values)), float(np.mean(temps))
    return flow, temperature


def features_for(history, month, horizon, flow_climate, temp_climate):
    if horizon not in HORIZONS:
        raise ValueError("Supported monthly horizons: 1, 2, 3, 4")
    now, previous = history[month], history[month_add(month, -1)]
    year_ago = history[month_add(month, -12)]
    flow = float(now["flow_mean_cumecs"])
    prior_flow = float(previous["flow_mean_cumecs"])
    flow_anomaly = flow - flow_climate[int(month[-2:])]
    previous_anomaly = prior_flow - flow_climate[int(month_add(month, -1)[-2:])]
    year_anomaly = float(year_ago["flow_mean_cumecs"]) - flow_climate[int(month[-2:])]
    rainfall_3m = sum(float(history[month_add(month, -lag)]["rainfall_mm"]) for lag in range(3))
    snowfall = float(now["snowfall_cm"])
    temperature_anomaly = float(now["temperature_c"]) - temp_climate[int(month[-2:])]
    return [flow_anomaly, previous_anomaly, year_anomaly, flow - prior_flow,
            float(now["rainfall_mm"]), rainfall_3m, snowfall, temperature_anomaly]


def _rmse(actual, predicted):
    return float(np.sqrt(np.mean((np.asarray(actual) - np.asarray(predicted)) ** 2)))


def _fit_ridge(features, targets, alpha):
    mean = features.mean(axis=0)
    scale = features.std(axis=0)
    scale[scale < 1e-8] = 1.0
    x = (features - mean) / scale
    target_mean = float(targets.mean())
    beta = np.linalg.solve(x.T @ x + alpha * np.eye(x.shape[1]), x.T @ (targets - target_mean))
    return {"feature_mean": mean.tolist(), "feature_scale": scale.tolist(),
            "feature_weights": beta.tolist(), "residual_intercept": target_mean, "ridge_alpha": alpha}


def _ridge_predict(model, features):
    x = (features - np.asarray(model["feature_mean"])) / np.asarray(model["feature_scale"])
    return model["residual_intercept"] + x @ np.asarray(model["feature_weights"])


def _xgb_predict(model, features):
    return model.predict(xgb.DMatrix(features))


def train(data_dir=DATA, output_dir=ARTIFACTS):
    data_dir, output_dir = Path(data_dir), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    history = {row["month"]: row for row in read_csv(data_dir / "seasonal_monthly.csv")}
    months = sorted(history)
    if len(months) < 180:
        raise ValueError("Monthly pilot requires at least 15 complete years")
    if any(month_add(months[i - 1], 1) != months[i] for i in range(1, len(months))):
        raise ValueError("Monthly series contains gaps; collect complete history before training")
    train_months = [month for month in months if month <= "2013-12"]
    val_months = [month for month in months if "2013-12" < month <= "2017-12"]
    test_months = [month for month in months if month > "2017-12"]
    flow_climate, temp_climate = climatology(history, train_months)
    all_predictions, feature_rows, models = [], [], {}

    for horizon in HORIZONS:
        rows = []
        for month in months:
            target_month = month_add(month, horizon)
            if target_month not in history:
                continue
            if month <= "2013-12" and target_month <= "2013-12":
                split = "train"
            elif "2013-12" < month <= "2017-12" and target_month <= "2017-12":
                split = "validation"
            elif month > "2017-12":
                split = "test"
            else:
                continue
            try:
                values = features_for(history, month, horizon, flow_climate, temp_climate)
            except KeyError:
                continue
            rows.append({"issue_month": month, "target_month": target_month, "split": split,
                         "features": values, "target": float(history[target_month]["flow_mean_cumecs"])})
        groups = {name: [row for row in rows if row["split"] == name]
                  for name in ("train", "validation", "test")}
        if any(len(group) < 24 for group in groups.values()):
            raise ValueError(f"Insufficient contiguous monthly samples at {horizon}-month lead")
        train_rows, validation_rows = groups["train"], groups["validation"]
        target_climatology = {f"{number:02d}": float(np.mean([
            row["target"] for row in train_rows if int(row["target_month"][-2:]) == number
        ])) for number in range(1, 13)}
        x_train = np.asarray([row["features"] for row in train_rows], dtype=np.float64)
        y_train = np.asarray([row["target"] - target_climatology[row["target_month"][-2:]] for row in train_rows])
        x_validation = np.asarray([row["features"] for row in validation_rows], dtype=np.float64)
        y_validation = np.asarray([row["target"] for row in validation_rows])

        candidates = {}
        for alpha in (10.0, 100.0, 1000.0):
            candidate = _fit_ridge(x_train, y_train, alpha)
            predicted = np.maximum(0, np.asarray([
                target_climatology[row["target_month"][-2:]] for row in validation_rows
            ]) + _ridge_predict(candidate, x_validation))
            candidates[f"ridge_alpha_{int(alpha)}"] = ("ridge", candidate, predicted)
        for depth in (1, 2):
            for estimators in (50, 100):
                for rate in (0.03, 0.05):
                    candidate = xgb.train({
                        "objective": "reg:squarederror", "max_depth": depth,
                        "eta": rate, "min_child_weight": 3, "subsample": 0.8,
                        "colsample_bytree": 0.8, "lambda": 10.0,
                        "seed": 42, "nthread": 1, "verbosity": 0,
                    }, xgb.DMatrix(x_train, label=y_train), num_boost_round=estimators)
                    predicted = np.maximum(0, np.asarray([
                        target_climatology[row["target_month"][-2:]] for row in validation_rows
                    ]) + _xgb_predict(candidate, x_validation))
                    name = f"xgboost_d{depth}_n{estimators}_lr{rate:.2f}"
                    candidates[name] = ("xgboost", candidate, predicted)
        candidates["seasonal_climatology"] = ("baseline", None, np.asarray([
            target_climatology[row["target_month"][-2:]] for row in validation_rows
        ]))
        candidates["persistence"] = ("baseline", None, np.asarray([row["features"][0] +
            flow_climate[int(row["issue_month"][-2:])] for row in validation_rows]))
        candidates["seasonal_naive"] = ("baseline", None, np.asarray([
            float(history[month_add(row["target_month"], -12)]["flow_mean_cumecs"])
            for row in validation_rows
        ]))
        selected_name, (selected_kind, selected_estimator, _) = min(
            candidates.items(), key=lambda item: _rmse(y_validation, item[1][2]))
        validation_scores = {name: {"mae_cumecs": float(np.mean(np.abs(y_validation - pred))),
                                    "rmse_cumecs": _rmse(y_validation, pred)}
                             for name, (_, _, pred) in candidates.items()}
        family_winners = {}
        for prefix in ("ridge_alpha_", "xgboost_"):
            eligible = [(name, item) for name, item in candidates.items() if name.startswith(prefix)]
            if eligible:
                family_winners[prefix.removesuffix("_")] = min(
                    eligible, key=lambda item: _rmse(y_validation, item[1][2]))
        model_type = ("ridge_climatology_residual" if selected_kind == "ridge" else
                      "xgboost_climatology_residual" if selected_kind == "xgboost" else selected_name)
        selected_model = {"model_type": model_type, "selected_candidate": selected_name,
                          "target_month_climatology_cumecs": target_climatology,
                          "validation_candidate_metrics": validation_scores}
        if selected_kind == "ridge":
            selected_model.update(selected_estimator)
        elif selected_kind == "xgboost":
            artifact_name = f"lead-{horizon}m.xgb.json"
            selected_estimator.save_model(str(output_dir / artifact_name))
            selected_model["model_artifact"] = artifact_name

        score_rows, split_meta = {}, {}
        for split in ("train", "validation", "test"):
            group = groups[split]
            x = np.asarray([row["features"] for row in group], dtype=np.float64)
            actual = np.asarray([row["target"] for row in group], dtype=np.float64)
            climate = np.asarray([target_climatology[row["target_month"][-2:]] for row in group])
            persistence = np.asarray([row["features"][0] + flow_climate[int(row["issue_month"][-2:])] for row in group])
            seasonal_naive = np.asarray([float(history[month_add(row["target_month"], -12)]["flow_mean_cumecs"]) for row in group])
            if selected_kind == "ridge":
                selected = np.maximum(0, climate + _ridge_predict(selected_estimator, x))
            elif selected_kind == "xgboost":
                selected = np.maximum(0, climate + _xgb_predict(selected_estimator, x))
            else:
                selected = {"seasonal_climatology": climate,
                            "persistence": np.maximum(0, persistence),
                            "seasonal_naive": np.maximum(0, seasonal_naive)}[selected_name]
            score_rows[split] = {
                "selected_model": {"rows": len(actual), "mae_cumecs": float(np.mean(np.abs(actual - selected))), "rmse_cumecs": _rmse(actual, selected)},
                "seasonal_climatology": {"rows": len(actual), "mae_cumecs": float(np.mean(np.abs(actual - climate))), "rmse_cumecs": _rmse(actual, climate)},
                "persistence": {"rows": len(actual), "mae_cumecs": float(np.mean(np.abs(actual - persistence))), "rmse_cumecs": _rmse(actual, persistence)},
                "seasonal_naive": {"rows": len(actual), "mae_cumecs": float(np.mean(np.abs(actual - seasonal_naive))), "rmse_cumecs": _rmse(actual, seasonal_naive)},
            }
            comparison = {}
            for family, (candidate_name, (kind, estimator, _)) in family_winners.items():
                residual = (_ridge_predict(estimator, x) if kind == "ridge" else _xgb_predict(estimator, x))
                prediction = np.maximum(0, climate + residual)
                comparison[family] = {
                    "candidate": candidate_name,
                    "rows": len(actual),
                    "mae_cumecs": float(np.mean(np.abs(actual - prediction))),
                    "rmse_cumecs": _rmse(actual, prediction),
                }
            score_rows[split]["candidate_comparison"] = comparison
            split_meta[split] = {"rows": len(group), "first_issue": group[0]["issue_month"],
                                 "last_issue": group[-1]["issue_month"], "last_target": group[-1]["target_month"]}
            for row, prediction in zip(group, selected, strict=True):
                prediction_row = {"station_id": "MARALA", "issue_month": row["issue_month"],
                                  "target_month": row["target_month"], "horizon_months": horizon,
                                  "split": split, "target_month_mean_cumecs": row["target"],
                                  "predicted_monthly_mean_cumecs": float(prediction),
                                  "model_type": selected_name}
                all_predictions.append(prediction_row)
                feature_rows.append({"station_id": "MARALA", "issue_month": row["issue_month"],
                                     "target_month": row["target_month"], "horizon_months": horizon,
                                     "split": split, **dict(zip(FEATURES, row["features"], strict=True)),
                                     "target_monthly_mean_cumecs": row["target"]})
        models[str(horizon)] = {"model": selected_model, "validation_selected_candidate": selected_name,
                                "metrics": score_rows, "splits": split_meta}

    write_csv(data_dir / "seasonal_training.csv", feature_rows)
    write_csv(output_dir / "holdout_predictions.csv", all_predictions)
    card = {
        "model_name": "marala_monthly_flow_outlook_v1", "schema_version": 3,
        "trained_at": datetime.now(timezone.utc).isoformat(), "station_id": "MARALA", "river": "Chenab",
        "forecast_unit": "complete calendar-month mean discharge", "horizons_months": list(HORIZONS),
        "target": "GloFAS daily modeled discharge averaged by month at a grid cell near Marala; not gauge-measured flow",
        "input_period": f"{months[0]} through {months[-1]}", "monthly_records": len(history),
        "features": FEATURES, "feature_count": len(FEATURES), "models": models,
        "validation_policy": "Chronological 2000-2013 train, 2014-2017 validation, 2018-2021 test; select Ridge, XGBoost, climatology, persistence, or seasonal-naive on validation only",
        "deployment_eligible": False, "status": "historical_research_hindcast_only",
        "limitations": ["GloFAS is modeled reach discharge, not a Marala gauge measurement.",
                        "ERA5 is retrospective reanalysis, not weather available to an operational forecast.",
                        "Monthly means do not predict flood peaks, dates, probability, or inundation.",
                        "The monthly archive ends in 2021; this artifact is not a current forecast."],
        "dataset_sha256": hashlib.sha256((data_dir / "seasonal_training.csv").read_bytes()).hexdigest(),
    }
    (output_dir / "model-card.json").write_text(json.dumps(card, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    outlook = predict(history, max(history), output_dir)
    (output_dir / "example_outlook.json").write_text(json.dumps(outlook, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return card


def collect_current_forecast(output_path=ARTIFACTS / "current_provider_outlook.json"):
    """Save daily GloFAS forecasts and complete-month averages from one response."""
    cfg = config()
    params = {
        "latitude": 32.675, "longitude": 74.425,
        "daily": "river_discharge_mean,river_discharge_median,river_discharge_p25,river_discharge_p75",
        "forecast_days": 210, "cell_selection": "nearest", "timezone": "GMT",
    }
    response = httpx.get(GLOFAS, params=params, timeout=120, follow_redirects=True)
    response.raise_for_status()
    payload = response.json()
    if abs(payload["latitude"] - 32.675) > 0.03 or abs(payload["longitude"] - 74.425) > 0.03:
        raise ValueError("Unexpected GloFAS forecast grid cell near Marala")
    daily = payload["daily"]
    daily_forecast = []
    for index, day in enumerate(daily["time"]):
        values = [daily[key][index] for key in ("river_discharge_mean", "river_discharge_median", "river_discharge_p25", "river_discharge_p75")]
        if any(value is None or not math.isfinite(value) or value < 0 for value in values):
            continue
        daily_forecast.append({"date": day, **dict(zip(("mean_cumecs", "median_cumecs", "p25_cumecs", "p75_cumecs"), values, strict=True))})
    grouped = {}
    for index, day in enumerate(daily["time"]):
        month = day[:7]
        grouped.setdefault(month, []).append({
            key: daily[key][index] for key in
            ("river_discharge_mean", "river_discharge_median", "river_discharge_p25", "river_discharge_p75")
        })
    forecast = []
    for month, values in sorted(grouped.items()):
        year, number = map(int, month.split("-"))
        expected_days = calendar.monthrange(year, number)[1]
        if len(values) != expected_days or any(any(row[key] is None for key in row) for row in values):
            continue
        forecast.append({
            "target_month": month, "days": expected_days,
            "monthly_mean_discharge_cumecs": {
                key.removeprefix("river_discharge_"): float(np.mean([row[key] for row in values]))
                for key in values[0]
            },
            "uncertainty_note": "Mean of daily ensemble statistics; p25/p75 are not a calibrated monthly prediction interval.",
        })
    if not forecast:
        raise ValueError("GloFAS returned no complete calendar-month forecast")
    output = {
        "station_id": cfg["station_id"], "river": cfg["river"],
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "forecast_issue_start": daily["time"][0], "forecast_available_through": daily["time"][-1],
        "forecast_source": "Open-Meteo Flood API, GloFAS v4 seamless default",
        "source_url": str(response.url), "response_sha256": hashlib.sha256(response.content).hexdigest(),
        "source_grid": {"latitude": payload["latitude"], "longitude": payload["longitude"]},
        "output_type": "provider_forecast_monthly_mean_modeled_reach_discharge",
        "station_observation": False, "forecast": forecast,
        "daily_forecast": daily_forecast,
        "daily_time_basis": "UTC calendar-day modeled discharge mean; not an instantaneous 06:00 PKT gauge forecast",
    }
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.with_suffix(".daily-source.json").write_text(json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    output_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    return output


def predict(history, issue_month, output_dir=ARTIFACTS):
    """Return monthly modeled-flow outlooks from one complete observed/modelled month."""
    output_dir = Path(output_dir)
    card = json.loads((output_dir / "model-card.json").read_text(encoding="utf-8"))
    if issue_month not in history:
        raise ValueError(f"No input data for issue month {issue_month}")
    train_months = [month for month in sorted(history) if month <= "2013-12"]
    flow_climate, temp_climate = climatology(history, train_months)
    outlook = []
    for horizon in HORIZONS:
        fitted = card["models"][str(horizon)]["model"]
        values = np.asarray([features_for(history, issue_month, horizon, flow_climate, temp_climate)], dtype=np.float64)
        target_month = month_add(issue_month, horizon)
        climate = float(fitted["target_month_climatology_cumecs"][target_month[-2:]])
        model_type = fitted["model_type"]
        if model_type == "ridge_climatology_residual":
            model = {key: fitted[key] for key in ("feature_mean", "feature_scale", "feature_weights", "residual_intercept")}
            predicted = max(0, climate + float(_ridge_predict(model, values)[0]))
        elif model_type == "xgboost_climatology_residual":
            model = xgb.Booster()
            model.load_model(str(output_dir / fitted["model_artifact"]))
            predicted = max(0, climate + float(_xgb_predict(model, values)[0]))
        elif model_type == "persistence":
            predicted = max(0, float(history[issue_month]["flow_mean_cumecs"]))
        elif model_type == "seasonal_naive":
            source_month = month_add(target_month, -12)
            predicted = max(0, float(history[source_month]["flow_mean_cumecs"]))
        else:
            predicted = climate
        outlook.append({"horizon_months": horizon, "target_month": target_month,
                        "predicted_monthly_mean_discharge_cumecs": predicted,
            "model_type": model_type, "selected_candidate": fitted["selected_candidate"]})
    issued = datetime.strptime(issue_month, "%Y-%m").replace(tzinfo=timezone.utc)
    issued_at = datetime(issued.year, issued.month, calendar.monthrange(issued.year, issued.month)[1], 23, 59, 59, tzinfo=timezone.utc)
    return {"station_id": "MARALA", "river": "Chenab", "issued_at": issued_at.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "input_through_month": issue_month, "model_name": card["model_name"],
            "output_type": "monthly_mean_modeled_reach_discharge_outlook", "research_only": True,
            "current_forecast": False, "outlook": outlook}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect", action="store_true")
    parser.add_argument("--current-forecast", action="store_true", help="Fetch current GloFAS monthly forecast separately from the trained hindcast")
    parser.add_argument("--start", default="2000-01-01")
    parser.add_argument("--end", default="2021-12-31")
    args = parser.parse_args()
    if args.collect:
        manifest = collect(start=args.start, end=args.end)
        print(json.dumps({"status": "collected", "months": manifest["rows"],
                          "first_month": manifest["first_month"], "last_month": manifest["last_month"]}, indent=2))
    if not args.current_forecast:
        card = train()
        print(json.dumps({"status": card["status"], "monthly_records": card["monthly_records"],
                          "lead_metrics": {key: value["metrics"]["test"] for key, value in card["models"].items()}}, indent=2))
    else:
        print(json.dumps(collect_current_forecast(), indent=2))
