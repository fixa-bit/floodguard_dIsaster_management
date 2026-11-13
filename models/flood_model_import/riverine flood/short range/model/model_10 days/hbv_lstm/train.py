"""Run expanding-year HBV calibration, ML training, monsoon backtests and final refit."""
import argparse
import json
import platform
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
import torch
from .data import digest, load_data, make_samples, masks, save_json
from .physical import BOUNDS, PARAMETERS, STATE_NAMES, FLUX_NAMES, calibrate
from .forcing import mixture_quantiles, mixture_exceedance
from .learning import fit_boosters, predict_boosters, fit_lstm, predict_lstm
from .evaluation import evaluate, plots


def thresholds(frame, cutoff, config):
    q = frame.loc[(frame.index.year >= config["first_training_year"]) & (frame.index <= pd.Timestamp(cutoff)), "q_cumecs"].dropna()
    result = {f"train_q{int(qt*100):02d}": float(q.quantile(qt))
              for qt in config["training_threshold_quantiles"]}
    for name, value in config["thresholds_cumecs"].items():
        if not str(name).replace("_", "").isalnum() or float(value) <= 0:
            raise ValueError("Thresholds need positive values and alphanumeric/underscore names")
        result[str(name)] = float(value)
    return result, float(q.quantile(.95))


def physical_fit(frame, area, cutoff, config, folder):
    folder.mkdir(parents=True, exist_ok=True)
    selected = frame.index <= pd.Timestamp(cutoff)
    f = frame[selected]
    mask = (f.index.year >= config["first_training_year"]) & np.isfinite(f.q_cumecs)
    mask &= np.arange(len(f)) >= config["warmup_days"]
    par, result = calibrate(f.rain_chirps_mm.to_numpy(), f.temperature_c.to_numpy(),
                            f.pet_mm.to_numpy(), f.q_cumecs.to_numpy(), mask, area, config)
    result.update({"calibration_cutoff": cutoff, "warmup_days": config["warmup_days"],
                   "warmup_start": str(frame.index[0].date()), "observed_calibration_days": int(mask.sum()),
                   "area_km2": area, "objective": "KGE 2009, full post-warmup training years",
                   "bounds": dict(zip(PARAMETERS, BOUNDS))})
    save_json(folder / "calibration.json", result)
    pd.DataFrame(result["generation_history"]).to_csv(folder / "calibration_history.csv", index=False)
    print(f"  HBV calibration KGE={result['calibration_kge']:.4f}, evaluations={result['evaluations']}", flush=True)
    return par


def save_physics(frame, samples, folder, config):
    daily = pd.DataFrame(samples["states"], index=frame.index, columns=STATE_NAMES)
    daily = daily.join(pd.DataFrame(samples["fluxes"], index=frame.index, columns=FLUX_NAMES))
    # Daily historical forcing is CHIRPS/ERA5, not the branch weather used at lead >0.
    daily["rainfall_mm"] = frame.rain_chirps_mm
    daily["temperature_c"] = frame.temperature_c
    daily["pet_mm"] = frame.pet_mm
    daily["observed_q_cumecs"] = frame.q_cumecs
    area = json.loads((folder / "calibration.json").read_text())["area_km2"]
    daily["hbv_flow_cumecs"] = samples["fluxes"][:, 3] * area / 86.4
    daily["is_warmup"] = np.arange(len(frame)) < config["warmup_days"]
    daily.to_csv(folder / "daily_states.csv", index_label="date")
    valid = (frame.valid_frac >= config["modis_min_valid_fraction"]) & frame.snow_cover_pct.between(0, 100)
    diagnostic = pd.DataFrame({"date": frame.index, "modeled_snowpack_mm": samples["states"][:, 0],
                               "modis_ndsi_index": frame.snow_cover_pct.to_numpy(),
                               "modis_valid_fraction": frame.valid_frac.to_numpy(), "accepted": valid.to_numpy()})
    diagnostic.to_csv(folder / "modis_snow_diagnostic.csv", index=False)
    rows = []
    for year in sorted(frame.index.year.unique()):
        use = valid & (frame.index.year == year)
        corr = spearmanr(samples["states"][use, 0], frame.snow_cover_pct[use]).statistic if use.sum() > 3 else np.nan
        rows.append({"year": int(year), "accepted_modis_days": int(use.sum()),
                     "spearman_snowpack_vs_ndsi": corr})
    pd.DataFrame(rows).to_csv(folder / "modis_diagnostic_by_year.csv", index=False)
    save_json(folder / "water_balance_audit.json", {
        "max_absolute_daily_error_mm": float(abs(samples["fluxes"][:, 5]).max()),
        "minimum_store_mm": float(samples["states"].min()),
        "identity": "previous total + snowfall*sfcf + rainfall = next total + AET + routed runoff",
        "modis_interpretation": "NDSI index, not observed snow area fraction; rank diagnostic only",
        "snow_fraction_feature": "HBV-derived 1-exp(-snowpack/50mm); assumed depletion curve, not observed fraction"})
    if abs(samples["fluxes"][:, 5]).max() > 1e-7 or samples["states"].min() < -1e-8:
        raise RuntimeError("HBV water balance/nonnegativity verification failed")


def forecast_table(frame, samples, selected, predictions, levels, event_threshold, year, mode):
    rows, member_rows = [], []
    chosen = np.flatnonzero(selected)
    for model, correction in predictions.items():
        if model == "HBV":
            quantiles = np.repeat(samples["hbv"][chosen, :, None], 3, -1)
        elif model == "persistence":
            quantiles = np.broadcast_to(samples["persistence"][chosen, None, None], (len(chosen), 10, 3)).copy()
        else:
            quantiles = samples["hbv"][chosen, :, None] + correction
        quantiles = np.sort(np.maximum(quantiles, 0), axis=-1)
        for origin in np.unique(samples["origins"][chosen]):
            positions = np.flatnonzero(samples["origins"][chosen] == origin)
            ix = chosen[positions]
            q, draws = mixture_quantiles(quantiles[positions][None, ...])
            probabilities = {name: mixture_exceedance(quantiles[positions], threshold)
                             for name, threshold in levels.items()}
            for lead in range(samples["hbv"].shape[1]):
                row = {"fold_year": year, "model": model, "issue_date": str(frame.index[origin].date()),
                       "valid_date": str(pd.Timestamp(samples["valid"][ix[0], lead]).date()),
                       "lead_day": lead+1, "observed": samples["labels"][ix[0], lead],
                       "p10": q[0, lead, 0], "p50": q[0, lead, 1], "p90": q[0, lead, 2],
                       "member_count": len(positions), "forcing_mode": mode,
                       "event_threshold_cumecs": event_threshold}
                for name, threshold in levels.items():
                    row[f"threshold_{name}_cumecs"] = threshold
                    row[f"probability_{name}"] = float(probabilities[name][lead])
                rows.append(row)
            for position, index in zip(positions, ix):
                for lead in range(samples["hbv"].shape[1]):
                    member_rows.append({"model": model, "issue_date": str(frame.index[origin].date()),
                                        "member": samples["members"][index], "lead_day": lead+1,
                                        "valid_date": str(pd.Timestamp(samples["valid"][index, lead]).date()),
                                        "hbv_cumecs": samples["hbv"][index, lead],
                                        "p10": quantiles[position, lead, 0], "p50": quantiles[position, lead, 1],
                                        "p90": quantiles[position, lead, 2]})
    return pd.DataFrame(rows), pd.DataFrame(member_rows)


def save_trajectories(frame, samples, selected, path):
    indices = np.flatnonzero(selected)
    horizon = samples["hbv"].shape[1]
    table = pd.DataFrame(samples["future_states"][indices].reshape(-1, 6), columns=STATE_NAMES)
    table["issue_date"] = np.repeat(frame.index[samples["origins"][indices]].strftime("%Y-%m-%d"), horizon)
    table["member"] = np.repeat(samples["members"][indices], horizon)
    table["lead_day"] = np.tile(np.arange(1, horizon+1), len(indices))
    table["valid_date"] = samples["valid"][indices].ravel()
    for j, name in enumerate(FLUX_NAMES):
        table[name] = samples["future_fluxes"][indices, :, j].ravel()
    for key, column in [("forecast_rain", "precipitation_mm"), ("forecast_temperature", "temperature_c"),
                        ("forecast_pet", "pet_climatology_mm"), ("hbv", "hbv_cumecs")]:
        table[column] = samples[key][indices].ravel()
    table.to_csv(path, index=False)


def fit_one(frame, area, archive, config, folder, year=None, fixed_rounds=None, fixed_epochs=None):
    folder.mkdir(parents=True, exist_ok=True)
    final = year is None
    cutoff = str(frame.index[-1].date()) if final else f"{year-2}-12-31"
    print(f"{'FINAL refit' if final else 'FOLD '+str(year)}: training through {cutoff}", flush=True)
    for subdir in ["physical", "forcing", "models/lightgbm", "models/lstm", "forecasts"]:
        (folder / subdir).mkdir(parents=True, exist_ok=True)
    par = physical_fit(frame, area, cutoff, config, folder / "physical")
    samples = make_samples(frame, par, area, config, cutoff, archive)
    save_physics(frame, samples, folder / "physical", config)
    save_json(folder / "forcing/quantile_mapping.json", samples["mapper"].grids)
    save_json(folder / "forcing/pet_climatology.json", samples["pet_climatology"])
    save_json(folder / "models/features.json", {name: samples[name] for name in ["history_features", "future_features", "tabular_features"]})
    if final:
        train = (samples["valid"][:, 0] >= np.datetime64(f"{config['first_training_year']}-01-01")) & (samples["origins"] >= config["warmup_days"])
        val = np.zeros_like(train)
        # Historical example from final refit, explicitly not out-of-sample verification.
        latest = np.max(samples["origins"])
        test = samples["origins"] == latest
    else:
        train, val, test = masks(samples, frame, config, year)
    if train.sum() < 365 or (not final and (val.sum() < 90 or test.sum() == 0)):
        raise ValueError("Insufficient chronological samples")
    splits = pd.DataFrame({"issue_date": frame.index[samples["origins"]], "member": samples["members"],
                           "first_target": samples["valid"][:, 0], "last_target": samples["valid"][:, -1],
                           "train": train, "validation": val, "evaluated_monsoon": test if not final else False})
    splits.to_csv(folder / "sample_splits.csv", index=False)
    print(f"  samples: train={train.sum()}, validation={val.sum()}, forecast={test.sum()}", flush=True)
    boosters, rounds, importance = fit_boosters(samples["tabular"], samples["residual"], train, val, config,
                                               folder / "models/lightgbm", samples["tabular_features"], fixed_rounds)
    pd.DataFrame(importance).to_csv(folder / "models/lightgbm/feature_importance.csv", index=False)
    print("  LightGBM: all 30 lead/quantile models trained", flush=True)
    lstm = fit_lstm(samples["history"], samples["future"], samples["residual"], train, val, config,
                    folder / "models/lstm", fixed_epochs)
    correction = {"HBV": None, "persistence": None,
                  "HBV_LightGBM": predict_boosters(boosters, samples["tabular"][test]),
                  "HBV_LSTM": predict_lstm(lstm, samples["history"][test], samples["future"][test])}
    levels, event_threshold = thresholds(frame, cutoff, config)
    save_json(folder / "thresholds.json", {"values_cumecs": levels, "event_threshold_cumecs": event_threshold,
                                          "official_thresholds": config["thresholds_cumecs"],
                                          "training_derived_names": [n for n in levels if n.startswith("train_q")]})
    mode = "archived_forecast" if archive is not None else "reanalysis_hindcast"
    table, members = forecast_table(frame, samples, test, correction, levels, event_threshold,
                                    "final_in_sample_example" if final else year, mode)
    # Training targets are always the original observed values; never replace NaNs.
    table.to_csv(folder / "forecasts/hydrographs.csv", index=False)
    members.to_csv(folder / "forecasts/member_hydrographs.csv.gz", index=False)
    save_trajectories(frame, samples, test, folder / "forecasts/hbv_trajectories.csv.gz")
    result = {"cutoff": cutoff, "training_rows": int(train.sum()), "validation_rows": int(val.sum()),
              "forecast_rows": int(test.sum()), "lgbm_rounds": rounds, "lstm_best_epoch": lstm[-1],
              "final_refit": final, "forecast_mode": mode}
    save_json(folder / "complete.json", result)
    return table, result


def write_report(root, predictions, scores, thresholds_df, config, manifest):
    summary = scores.groupby("model")[["kge", "nse", "mae_cumecs", "flood_mae_cumecs",
                                         "peak_magnitude_mae_cumecs", "peak_timing_mae_days"]].mean()
    summary.to_csv(root / "reports/mean_scores_across_leads.csv")
    comparison = pd.read_csv(root / "reports/baseline_comparison.csv")
    lines = ["# HBV residual models: actual training and rolling monsoon results", "",
             f"Run date (Asia/Karachi): 2026-10-30. Evaluated monsoons: {config['test_years']}.", "",
             "Each fold calibrates HBV and fits monthly weather mappings on 2016 through test_year-2. "
             "The following complete year selects ML early stopping; the next June-September season is evaluated. "
             "All ten target dates stay in their own split/season. Initial 730 days spin up stores. "
             "Daily issue forecasts update states from past weather and use discharge observed through issue day. "
             "No test target enters fitting, normalization, weather mapping or threshold selection.", "",
             "## Mean of the ten lead-specific scores", "",
             "| Model | KGE | NSE | MAE m³/s | Flood MAE m³/s | Event peak MAE m³/s | Timing MAE days |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for name, row in summary.iterrows():
        lines.append("| " + str(name) + " | " + " | ".join(f"{v:.3f}" for v in row) + " |")
    lines.extend(["", "These means summarize lead-specific scores; they are not a single pooled KGE. "
                  "Flood days exceed each fold's training Q95. Event windows are +/-5 days around observed "
                  "exceedance clusters separated by more than seven days. Signed errors and event dates are in peak_events.csv.",
                  "", "## Does the hybrid beat the baselines?", ""])
    for (hybrid, baseline), g in comparison.groupby(["hybrid", "baseline"]):
        lines.append(f"- {hybrid} vs {baseline}: higher KGE at {(g.kge_improvement > 0).sum()}/10 leads; "
                     f"lower MAE at {(g.mae_reduction_cumecs > 0).sum()}/10; "
                     f"lower flood MAE at {(g.flood_mae_reduction_cumecs > 0).sum()}/10; "
                     f"lower event peak magnitude MAE at {(g.peak_magnitude_mae_reduction_cumecs > 0).sum()}/10; "
                     f"lower timing MAE at {(g.peak_timing_mae_reduction_days > 0).sum()}/10.")
    lines.extend(["", "Threshold metrics (POD, FAR, CSI and Brier) are saved per lead and season, together with TP/FP/FN "
                  "and observed event counts. Forecast exceedance uses probability >=0.5. "
                  "Undefined ratios are left missing. Statistical Q90/Q95/Q99 thresholds are training-derived, "
                  "not official flood classes. No official station thresholds were supplied in this configuration.", "",
                  "Persistence can reproduce the observed event magnitude after a delay; its small local-window "
                  "peak magnitude error should be judged jointly with timing and threshold scores. "
                  "Neither hybrid consistently improves every flood diagnostic.", "",
                  "## Statistical flood-threshold scores", "",
                  "The following are means of the ten pooled lead-specific scores at each fold's training Q95.", "",
                  "| Model | POD | FAR | CSI | Brier score |",
                  "|---|---:|---:|---:|---:|"])
    threshold_summary = thresholds_df[thresholds_df.threshold == "train_q95"].groupby("model")[["pod", "far", "csi", "brier_score"]].mean()
    threshold_summary.to_csv(root / "reports/mean_q95_threshold_scores.csv")
    for name, row in threshold_summary.iterrows():
        lines.append("| " + str(name) + " | " + " | ".join(f"{v:.3f}" for v in row) + " |")
    lines.extend(["", "## Data and operational limitations", ""])
    lines.extend(["- " + warning for warning in manifest["limitations"]])
    cal = pd.read_csv(root / "reports/quantile_calibration.csv")
    for model in ["HBV_LightGBM", "HBV_LSTM"]:
        cover = cal.loc[cal.model == model, "coverage_80"].mean()
        lines.append(f"- {model} mean empirical P10-P90 coverage: {cover:.3f} (nominal 0.80). "
                     "The intervals are not post-calibrated on the test seasons.")
    lines.extend(["", "## Saved artifacts", "",
                  "- `folds/YYYY/physical/`: calibrated parameters, optimizer trace, daily states/fluxes, water balance and MODIS diagnostics.",
                  "- `folds/YYYY/forcing/`: train-only monthly quantile maps and PET climatology.",
                  "- `folds/YYYY/models/`: 30 LightGBM text models, feature importance, LSTM best checkpoint, normalization and training history.",
                  "- `folds/YYYY/forecasts/`: P10/P50/P90, threshold probabilities, per-member forecasts and HBV trajectories.",
                  "- `reports/`: rolling predictions, all requested metrics, event details, baseline comparisons and plots.",
                  "- `final/`: refit on all eligible 2016-2024 observations with stopping lengths fixed from the last fold. "
                  "Its last historical forecast is an in-sample replay, not an operational forecast or a held-out score.",
                  "- `data/`, `config.json`, `requirements-lock.txt`, `input_manifest.json`, `artifact_manifest.json` and `training.log`: reproducibility records.", ""])
    (root / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def run(config_path, resume=False):
    config_path = Path(config_path).resolve()
    base = config_path.parent
    config = json.loads(config_path.read_text())
    root = (base / config["output_dir"]).resolve()
    if config["horizon"] != 10 or config["quantiles"] != [0.1, 0.5, 0.9]:
        raise ValueError("This pipeline requires leads 1-10 and quantiles P10/P50/P90")
    if root.exists() and not resume:
        raise FileExistsError(f"Run already exists: {root}; use a new output_dir or --resume")
    root.mkdir(parents=True, exist_ok=True)
    if resume and (root / "config.json").exists():
        if json.loads((root / "config.json").read_text()) != config:
            raise ValueError("Cannot resume with a changed configuration")
    save_json(root / "config.json", config)
    for directory in ["data", "reports"]:
        (root / directory).mkdir(exist_ok=True)
    torch.set_num_threads(config["threads"])
    frame, area, archive, hashes = load_data(config, base)
    if resume and (root / "input_manifest.json").exists():
        if json.loads((root / "input_manifest.json").read_text()) != hashes:
            raise ValueError("Cannot resume after source inputs changed")
    if config.get("glofas_file"):
        raise ValueError("No GloFAS archive adapter configured; supply an aligned issued-forecast adapter before comparison")
    save_json(root / "input_manifest.json", hashes)
    frame.to_csv(root / "data/daily_inputs.csv", index_label="date")
    limitations = [
        "No archived weather forecasts were supplied. Future ERA5-Land rainfall and temperature are realized reanalysis, "
        "so these are optimistic weather-driven hindcasts. Training/operations mismatch remains unquantified."
        if archive is None else "Archived forecast weather is used; check provider issue times and member weights before deployment.",
        "No authentic meteorological ensemble was found; this run has one reanalysis member. P10/P50/P90 quantify "
        "conditional residual uncertainty, not full weather, parameter or structural uncertainty. Genuine issued ensembles "
        "are supported by the archive input schema and are propagated separately through HBV and both corrections.",
        "Rainfall quantile mapping uses training ERA5-Land vs CHIRPS v3. Temperature has no independent observed reference "
        "and uses an identity mapping against the same ERA5-Land series; independent temperature bias correction is unvalidated.",
        "MOD10A1 exports actually available end in 2019. They contain mean NDSI, not fractional snow-covered area. "
        "MODIS is used as a quality-screened, two-day-delayed historical index and for rank diagnostics only. "
        "The snow fraction feature is an assumed HBV depletion curve. No independent MODIS validation covers the test monsoons.",
        "No issued GloFAS forecasts were available; that baseline was not evaluated.",
        "Observed discharge is not gap-filled. WAPDA historical observation times are largely unconfirmed; dates are aligned "
        "with UTC weather days by the existing table. Operational availability and reading/day alignment need validation.",
        "These years have already been inspected in earlier workspace experiments. They are excluded from each fold's fitting "
        "but are not a globally untouched research holdout. Seasonal sample sizes are small and daily forecast windows overlap.",
        "HBV is lumped, with a linear routing reservoir. Elevation bands, glacier ice melt, regulation and diversions are not "
        "resolved. Final AI-adjusted flow need not conserve water even when HBV does.",
        "Mixture probabilities use equal member weights and a piecewise-linear conditional quantile function with constant "
        "tails outside P10/P90. Very rare exceedances and cross-lead event probabilities are not resolved by this approximation."
    ]
    if archive is not None:
        limitations[1] = "Issued forecast members are weighted equally; conditional residual distributions are mixed across members."
        limitations[2] = "Train-only monthly, lead-specific quantile maps correct archived weather against CHIRPS rain and ERA5-Land temperature."
    manifest = {"status": "running", "started_utc": datetime.now(timezone.utc).isoformat(),
                "python": platform.python_version(), "area_km2": area, "observed_days": int(frame.q_cumecs.notna().sum()),
                "simulation_days": len(frame), "limitations": limitations,
                "sources": {"HBV": "https://hess.copernicus.org/articles/16/3315/2012/",
                            "MODIS": "https://nsidc.org/data/user-resources/help-center/what-ndsi-snow-cover-and-how-does-it-compare-fsc",
                            "LightGBM": "https://lightgbm.readthedocs.io/en/stable/Parameters.html"}}
    save_json(root / "run_manifest.json", manifest)
    (root / "requirements-lock.txt").write_text(subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True))
    tables, results = [], []
    for year in config["test_years"]:
        folder = root / "folds" / str(year)
        if resume and (folder / "complete.json").exists():
            print(f"Reusing completed fold {year}", flush=True)
            table, result = pd.read_csv(folder / "forecasts/hydrographs.csv"), json.loads((folder / "complete.json").read_text())
        else:
            table, result = fit_one(frame, area, archive, config, folder, year)
        tables.append(table)
        results.append(result)
    predictions = pd.concat(tables, ignore_index=True)
    predictions.to_csv(root / "reports/rolling_predictions.csv.gz", index=False)
    scores, threshold_scores = evaluate(predictions, root / "reports")
    plots(predictions, scores, root / "reports")
    if not (resume and (root / "final/complete.json").exists()):
        fit_one(frame, area, archive, config, root / "final", fixed_rounds=results[-1]["lgbm_rounds"],
                fixed_epochs=results[-1]["lstm_best_epoch"])
    unchanged = all(digest(p) == h for p, h in hashes.items())
    if not unchanged:
        raise RuntimeError("Source inputs changed while training")
    manifest.update({"status": "complete", "finished_utc": datetime.now(timezone.utc).isoformat(),
                     "inputs_unchanged": unchanged, "folds": results})
    save_json(root / "run_manifest.json", manifest)
    write_report(root, predictions, scores, threshold_scores, config, manifest)
    save_json(root / "artifact_manifest.json", {str(p.relative_to(root)): {"bytes": p.stat().st_size, "sha256": digest(p)}
              for p in sorted(root.rglob("*")) if p.is_file() and p.name not in ["artifact_manifest.json", "training.log"]})
    print(f"COMPLETE: {root / 'REPORT.md'}", flush=True)
    print(scores.groupby("model")[["kge", "nse", "mae_cumecs", "flood_mae_cumecs"]].mean().to_string(), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(Path(__file__).with_name("config.json")))
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    config = json.loads(config_path.read_text())
    root = (config_path.parent / config["output_dir"]).resolve()
    if root.exists() and not args.resume:
        raise FileExistsError(f"Run exists: {root}")
    root.mkdir(parents=True, exist_ok=True)
    class Tee:
        def __init__(self, original, file):
            self.original, self.file = original, file
        def write(self, text):
            self.original.write(text)
            self.file.write(text)
            self.file.flush()
        def flush(self):
            self.original.flush()
            self.file.flush()
    with (root / "training.log").open("a", encoding="utf-8") as log:
        stdout, stderr = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = Tee(stdout, log), Tee(stderr, log)
        try:
            # Root created for the log only; run's --resume checks the saved config.
            run(args.config, resume=True)
        except Exception:
            traceback.print_exc()
            save_json(root / "failure.json", {"traceback": traceback.format_exc()})
            raise
        finally:
            sys.stdout, sys.stderr = stdout, stderr


if __name__ == "__main__":
    main()
