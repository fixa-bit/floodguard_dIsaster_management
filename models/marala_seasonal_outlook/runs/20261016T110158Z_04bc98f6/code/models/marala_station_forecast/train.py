"""Train direct 06:00 gauge forecasts with a sealed final-year evaluation."""
import argparse
import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import xgboost

from .core import (FEATURES, HERE, PROJECT, build_rows, candidate_specs, feature_row, fit,
                   load_model, load_observations, metrics, predict, save_model, sha256,
                   write_csv, write_json)

DEFAULT_SOURCES = [PROJECT / "app/ml/marala_pilot/data/ffd_observations.json",
                   PROJECT / "app/ml/marala_pilot/artifacts/seasonal/gauge_history_observations.json"]


def split_rows(rows, cfg):
    result = {name: [] for name in ("train", "validation", "test")}
    for row in rows:
        issue, target = date.fromisoformat(row["issue_date"]), date.fromisoformat(row["target_date"])
        for name, key in (("train", "training_years"), ("validation", "validation_years"), ("test", "test_years")):
            if issue.year in cfg[key] and target.year in cfg[key]:
                result[name].append(row)
    if any(len(rows) < 20 for rows in result.values()):
        raise ValueError("Each chronological partition needs at least 20 measured target pairs")
    if max(row["target_at"] for row in result["train"]) >= min(row["issued_at"] for row in result["validation"]):
        raise ValueError("Train labels overlap validation issue times")
    if max(row["target_at"] for row in result["validation"]) >= min(row["issued_at"] for row in result["test"]):
        raise ValueError("Validation labels overlap test issue times")
    return result


def score(rows, values):
    actual = np.asarray([row["target_cumecs"] for row in rows])
    result = metrics(actual, values)
    peak, predicted_peak = int(np.argmax(actual)), int(np.argmax(values))
    result.update(peak_target_date=rows[peak]["target_date"],
                  predicted_peak_target_date=rows[predicted_peak]["target_date"],
                  peak_timing_error_days=(date.fromisoformat(rows[predicted_peak]["target_date"]) - date.fromisoformat(rows[peak]["target_date"])).days)
    return result


def train(output=HERE / "artifacts", sources=DEFAULT_SOURCES):
    from .archive import begin_run, retain_bulletins, seal_run
    latest_output = Path(output)
    run_folder, frozen_sources = begin_run(sources, latest_output)
    output = run_folder / "artifacts"
    cfg = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
    history, provenance = load_observations(frozen_sources)
    data_dir = run_folder / "data"
    write_csv(data_dir / "observations.csv", list(history.values()))
    manifest = {"station_id": "MARALA", "measured_days": len(history),
                "years": {str(year): sum(day.year == year for day in history) for year in sorted({day.year for day in history})},
                "first_day": min(history).isoformat(), "last_day": max(history).isoformat(),
                "sources": provenance, "snapshot_sha256": sha256(data_dir / "observations.csv"),
                "config": cfg, "code_sha256": {name: sha256(HERE / name) for name in ("core.py", "train.py", "config.json")},
                "numpy_version": np.__version__, "xgboost_version": xgboost.__version__}
    write_json(data_dir / "manifest.json", manifest)
    specs = candidate_specs()
    write_json(output / "predeclared_candidates.json", specs)
    selections, prepared, leaderboard = {}, {}, []

    # All model selection finishes before any 2026 test prediction is evaluated.
    for horizon in cfg["horizons_days"]:
        rows, skipped = build_rows(history, horizon)
        groups = split_rows(rows, cfg)
        prepared[horizon] = (rows, groups, skipped)
        candidates = []
        for spec in specs:
            try:
                model = fit(spec, groups["train"], horizon)
                validation = score(groups["validation"], predict(model, groups["validation"]))
                candidates.append({"spec": spec, "validation": validation})
                leaderboard.append({"horizon_days": horizon, "candidate": spec["id"], "family": spec["family"],
                                    "validation_rmse_cumecs": validation["rmse_cumecs"], "validation_mae_cumecs": validation["mae_cumecs"], "status": "valid"})
            except (ValueError, np.linalg.LinAlgError) as exc:
                leaderboard.append({"horizon_days": horizon, "candidate": spec["id"], "family": spec["family"],
                                    "validation_rmse_cumecs": "", "validation_mae_cumecs": "", "status": str(exc)})
        candidates.sort(key=lambda row: (row["validation"]["rmse_cumecs"], row["validation"]["mae_cumecs"], row["spec"]["id"]))
        learned = next(row for row in candidates if row["spec"]["family"] in ("ridge", "xgboost"))
        selections[str(horizon)] = {"champion": candidates[0], "best_learned": learned,
                                    "candidates_scored": len(candidates)}
        print(f"{horizon}d: {len(candidates)} validation candidates; selected {candidates[0]['spec']['id']}; best learned {learned['spec']['id']}", flush=True)
        split_map = {row["issue_date"]: name for name, group in groups.items() for row in group}
        write_csv(data_dir / f"supervised_{horizon}d.csv", [
            {"issue_date": row["issue_date"], "target_date": row["target_date"], "split": split_map.get(row["issue_date"], "purged"),
             **dict(zip(FEATURES, row["features"], strict=True)), "target_cumecs": row["target_cumecs"],
             "issue_source": row["source_url"], "target_source": row["target_source_url"]} for row in rows])
    write_json(output / "selection.json", {"criterion": cfg["selection_metric"], "test_used_for_selection": False, "selections": selections})
    write_csv(output / "validation_leaderboard.csv", leaderboard)

    results, holdout, forecasts = {}, [], []
    for horizon in cfg["horizons_days"]:
        rows, groups, skipped = prepared[horizon]
        selected = selections[str(horizon)]
        eval_specs = {"champion": selected["champion"]["spec"], "best_learned": selected["best_learned"]["spec"],
                      "persistence": {"id": "persistence", "family": "persistence"},
                      "linear_trend": {"id": "linear_trend", "family": "trend", "damping": 1.}}
        train_validation = groups["train"] + groups["validation"]
        scores, predictions = {}, {}
        for name, spec in eval_specs.items():
            model = fit(spec, train_validation, horizon)
            values = predict(model, groups["test"])
            scores[name], predictions[name] = score(groups["test"], values), values
            folder = output / "evaluation_models" / f"{horizon}d" / name
            save_model(model, folder)
            np.testing.assert_allclose(predict(load_model(folder), groups["test"]), values, rtol=1e-7)
        for index, row in enumerate(groups["test"]):
            holdout.append({"horizon_days": horizon, "origin_observed_at": row["issued_at"], "target_at": row["target_at"],
                            "actual_cumecs": row["target_cumecs"], **{name + "_cumecs": float(values[index]) for name, values in predictions.items()},
                            "issue_source": row["source_url"], "target_source": row["target_source_url"]})
        baseline_rmse = scores["persistence"]["rmse_cumecs"]
        results[str(horizon)] = {"selection": selected, "splits": {
            name: {"rows": len(group), "first_origin": group[0]["issued_at"], "last_target": group[-1]["target_at"]}
            for name, group in groups.items()}, "skipped": skipped, "test": scores,
            "test_rmse_improvement_over_persistence_percent": 100 * (baseline_rmse - scores["champion"]["rmse_cumecs"]) / baseline_rmse,
            "test_beats_persistence": scores["champion"]["rmse_cumecs"] < baseline_rmse}
        latest = feature_row(history, max(history))
        for name in ("champion", "best_learned"):
            production = fit(eval_specs[name], rows, horizon)
            save_model(production, output / "models" / f"{horizon}d" / name)
            forecast = float(predict(production, [latest])[0])
            forecasts.append({"horizon_days": horizon, "candidate_role": name, "candidate": eval_specs[name]["id"],
                              "origin_observed_at": latest["issued_at"],
                              "target_at": (datetime.fromisoformat(latest["issued_at"]) + timedelta(days=horizon)).isoformat(),
                              "predicted_inflow_cumecs": forecast, "last_measured_inflow_cumecs": latest["current_cumecs"],
                              "research_only": True, "production_refit_uses_test_season_after_evaluation": True})
        print(f"{horizon}d held-out 2026: champion RMSE {scores['champion']['rmse_cumecs']:.2f}; persistence {baseline_rmse:.2f}", flush=True)

    card = {"model_name": "marala_station_gauge_forecast_v1", "trained_at": datetime.now(timezone.utc).isoformat(),
            "target": "Direct future instantaneous FFD-reported Marala inflow at 06:00 PKT, in m3/s",
            "horizons_days": cfg["horizons_days"], "features": FEATURES, "data": manifest,
            "model_selection": "2024 fits evaluated on 2025; every horizon frozen before looking at 2026 scores",
            "evaluation": "Frozen candidates refit on 2024+2025, evaluated on rolling 2026 origins using only measurements at or before each origin",
            "production_refit": "Same frozen candidates refit on all eligible 2024-2026 pairs only after evaluation; no fresh independent test for that final refit",
            "deployment_eligible": False, "status": "research_only_independent_validation_required", "results": results,
            "limitations": [
                "Only 322 measured days across three short, incomplete flood seasons at training time; no year-round coverage.",
                "No observed upstream Akhnur flow, rainfall forecasts, snowmelt, reservoir releases, or subdaily gauge series.",
                "One extreme 2025 flood is in validation; a single held-out 2026 season does not establish rare-event skill.",
                "06:00 is the measurement time, not guaranteed publication time; bulletin latency reduces operational lead time.",
                "Missing gauge dates are never interpolated; older optional feature gaps use training-only imputation for ridge.",
                "Outputs are discharge estimates, not calibrated flood probabilities, inundation, or damage estimates.",
                "1-, 3-, 7-day direct targets do not justify recursive seven-month instantaneous predictions.",
                "The existing dashboard GloFAS feed has not been replaced.",
            ]}
    write_json(output / "model-card.json", card)
    write_csv(output / "holdout_predictions_2026.csv", holdout)
    write_json(output / "latest_predictions.json", {"computed_at": card["trained_at"], "origin_source": history[max(history)]["source_url"],
               "observation_time_is_not_publication_time": True, "predictions": forecasts})
    write_report(card, output / "REPORT.md")
    retain_bulletins(history, run_folder)
    seal_run(run_folder, data_dir, output)
    latest_data = HERE / "data" if latest_output == HERE / "artifacts" else latest_output.parent / "data"
    shutil.copytree(data_dir, latest_data, dirs_exist_ok=True)
    shutil.copytree(output, latest_output, dirs_exist_ok=True)
    print(f"Sealed reproducible run: {run_folder}", flush=True)
    return card


def write_report(card, path):
    text = ["# Marala measured-gauge forecasting experiment", "", "Target: future **06:00 PKT instantaneous inflow**, not a daily mean or a GloFAS grid value.",
            "", f"Data: {card['data']['measured_days']} unique FFD readings ({card['data']['first_day']} to {card['data']['last_day']}).",
            "", "2024 trains candidates; 2025 selects them. Frozen candidates are refit on 2024+2025 before the untouched 2026 evaluation. No random split or future weather is used.",
            "", "| Lead | Validation-selected candidate | 2026 rows | RMSE | Persistence RMSE | Improvement | MAE | Flood recall |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for horizon, result in card["results"].items():
        model, baseline = result["test"]["champion"], result["test"]["persistence"]
        recall = f"{100 * model['flood_recall']:.1f}%" if model["flood_recall"] is not None else "unavailable"
        text.append(f"| {horizon} days | {result['selection']['champion']['spec']['id']} | {model['rows']} | {model['rmse_cumecs']:.2f} | {baseline['rmse_cumecs']:.2f} | {result['test_rmse_improvement_over_persistence_percent']:.1f}% | {model['mae_cumecs']:.2f} | {recall} |")
    text.extend(["", "All discharge errors are in m³/s. Positive improvement means lower RMSE than persistence. A high score in one season does not establish general flood-warning skill.",
                 "", "The best learned ridge/XGBoost candidate is also saved separately from the overall champion; a simple baseline is retained when it wins validation. See model-card.json and validation_leaderboard.csv for the complete comparisons.",
                 "", "Flood recall uses the [FFD Marala low-flood threshold](https://ffd.pmd.gov.pk/flood-limits) of 100,000 cusecs; it is discharge-threshold screening, not a flood probability.",
                 "", "The final inference artifacts refit the frozen candidates on all three seasons after evaluation. The 2026 CSV evaluates the separate pre-2026 fit, not that final refit.", "", "## Limits", ""])
    text.extend("- " + limitation for limitation in card["limitations"])
    text.extend(["", "## Artifacts", "", "- `models/<lead>d/champion/`: final inference models.", "- `models/<lead>d/best_learned/`: best validation-selected learned model.",
                 "- `evaluation_models/`: fits that generated the held-out 2026 predictions.", "- `holdout_predictions_2026.csv`: actual, champion, learned, persistence and trend values with source links.",
                 "- `latest_predictions.json`: as-of forecasts from the latest available measured input; target timestamps are explicit.", ""])
    path.write_text("\n".join(text), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=HERE / "artifacts")
    args = parser.parse_args()
    train(args.output_dir)
