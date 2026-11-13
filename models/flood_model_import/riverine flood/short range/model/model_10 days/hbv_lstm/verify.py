"""Audit real trained artifacts and replay the two-member inference path."""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
import numpy as np
import pandas as pd
from .data import digest, save_json
from .physical import STATE_NAMES, PARAMETERS, initial_state
from .predict import predict
from .evaluation import evaluate
from .train import write_report
from .forcing import mixture_exceedance


def refresh_probabilities(folder):
    """Use the analytic conditional CDF for the already saved member quantiles."""
    table = pd.read_csv(folder / "forecasts/hydrographs.csv")
    members = pd.read_csv(folder / "forecasts/member_hydrographs.csv.gz")
    thresholds = json.loads((folder / "thresholds.json").read_text())["values_cumecs"]
    for (model, issue), group in members.groupby(["model", "issue_date"]):
        group = group.sort_values(["member", "lead_day"])
        values = group[["p10", "p50", "p90"]].to_numpy().reshape(-1, 10, 3)
        indices = table[(table.model == model) & (table.issue_date == issue)].sort_values("lead_day").index
        for name, threshold in thresholds.items():
            table.loc[indices, f"probability_{name}"] = mixture_exceedance(values, threshold)
    table.to_csv(folder / "forecasts/hydrographs.csv", index=False)
    return table


def verify(run):
    root = Path(run).resolve()
    config = json.loads((root / "config.json").read_text())
    manifest = json.loads((root / "run_manifest.json").read_text())
    if manifest["status"] != "complete":
        raise ValueError("Training run is not complete")
    source_hashes = json.loads((root / "input_manifest.json").read_text())
    assert all(digest(path) == sha for path, sha in source_hashes.items()), "Source mutation"
    recorded = json.loads((root / "artifact_manifest.json").read_text())
    assert all((root / p).exists() and digest(root / p) == spec["sha256"] for p, spec in recorded.items()), "Artifact mutation"
    original = pd.read_csv(root / "data/daily_inputs.csv", parse_dates=["date"]).set_index("date")
    predictions = pd.read_csv(root / "reports/rolling_predictions.csv.gz")
    assert len(predictions) == len(config["test_years"]) * 113 * 10 * 4
    assert not predictions.duplicated(["fold_year", "model", "issue_date", "lead_day"]).any()
    assert np.isfinite(predictions[["p10", "p50", "p90"]]).all().all()
    assert (predictions.p10 >= 0).all()
    assert (predictions.p10 <= predictions.p50).all() and (predictions.p50 <= predictions.p90).all()
    for column in [c for c in predictions if c.startswith("probability_")]:
        assert predictions[column].between(0, 1).all()
    aligned_observed = original.q_cumecs.reindex(pd.to_datetime(predictions.valid_date)).to_numpy()
    np.testing.assert_allclose(predictions.observed, aligned_observed, equal_nan=True)
    checks, derived_daily = [], []
    folders = [root / "folds" / str(y) for y in config["test_years"]] + [root / "final"]
    for folder in folders:
        cal = json.loads((folder / "physical/calibration.json").read_text())
        daily_path = folder / "physical/daily_states.csv"
        daily = pd.read_csv(daily_path, parse_dates=["date"]).set_index("date")
        assert len(daily) == len(original)
        np.testing.assert_allclose(daily.observed_q_cumecs, original.q_cumecs, equal_nan=True)
        par = np.array([cal["parameters"][name] for name in PARAMETERS])
        total = daily[STATE_NAMES].sum(axis=1).to_numpy()
        previous = np.r_[initial_state(par).sum(), total[:-1]]
        error = previous + daily.effective_precipitation_mm.to_numpy() - total - daily.actual_evaporation_mm.to_numpy() - daily.runoff_mm.to_numpy()
        assert np.abs(error).max() < 1e-7
        assert daily[STATE_NAMES].min().min() >= 0
        # Explicit historical flow column is a presentation addition to saved runoff.
        daily["hbv_flow_cumecs"] = daily.runoff_mm * cal["area_km2"] / 86.4
        derived_daily.append((daily_path, daily))
        splits = pd.read_csv(folder / "sample_splits.csv", parse_dates=["first_target", "last_target"])
        assert not (splits.train & splits.validation).any()
        assert (splits.loc[splits.train, "last_target"] <= pd.Timestamp(cal["calibration_cutoff"])).all()
        if folder.name != "final":
            year = int(folder.name)
            assert (splits.loc[splits.validation, "first_target"] >= pd.Timestamp(f"{year-1}-01-01")).all()
            assert (splits.loc[splits.validation, "last_target"] <= pd.Timestamp(f"{year-1}-12-31")).all()
            selected = splits.loc[splits.evaluated_monsoon]
            assert (selected.first_target >= pd.Timestamp(f"{year}-06-01")).all()
            assert (selected.last_target <= pd.Timestamp(f"{year}-09-30")).all()
        assert len(list((folder / "models/lightgbm").glob("lead_*_q*.txt"))) == 30
        assert (folder / "models/lstm/best.pt").stat().st_size > 0
        trajectory = pd.read_csv(folder / "forecasts/hbv_trajectories.csv.gz")
        assert trajectory.water_balance_error_mm.abs().max() < 1e-7
        assert trajectory[STATE_NAMES].min().min() >= 0
        assert (trajectory.groupby(["issue_date", "member"]).size() == 10).all()
        checks.append({"folder": str(folder.relative_to(root)), "daily_rows": len(daily),
                       "max_recomputed_water_balance_error_mm": float(np.abs(error).max()),
                       "calibration_kge": cal["calibration_kge"], "de_converged": cal["converged"],
                       "optimizer_generations": cal["generations"], "lightgbm_models": 30})
    # Replay the final historical example with two identical reanalysis trajectories.
    # Artificial issue/availability labels test archive handling only. No assertion
    # that an archived meteorological forecast ever existed is made or saved.
    final = pd.read_csv(root / "final/forecasts/hydrographs.csv")
    issue = pd.Timestamp(final.issue_date.iloc[0])
    weather = original.loc[issue + pd.Timedelta(days=1):issue + pd.Timedelta(days=10)]
    with tempfile.TemporaryDirectory(prefix="hbv_reload_check_") as temp:
        temp = Path(temp)
        original.to_csv(temp / "history.csv", index_label="date")
        archive = []
        for member in ["synthetic_format_fixture_0", "synthetic_format_fixture_1"]:
            for lead, (date, row) in enumerate(weather.iterrows(), 1):
                archive.append({"issue_date": str(issue.date()), "valid_date": str(date.date()), "member": member,
                                "lead_day": lead, "available_at": str(issue.date()) + "T12:00:00Z",
                                "precipitation_mm": row.rain_era5_mm, "temperature_c": row.temperature_c})
        pd.DataFrame(archive).to_csv(temp / "synthetic_archive_format_fixture.csv", index=False)
        predict(root, temp / "history.csv", temp / "synthetic_archive_format_fixture.csv", str(issue.date()), temp / "output")
        replay = pd.read_csv(temp / "output/hydrographs.csv")
        assert (replay.member_count == 2).all()
        assert len(pd.read_csv(temp / "output/hbv_trajectories.csv")) == 20
        differences = []
        for model in final.model.unique():
            reference = final[final.model == model].sort_values("lead_day")[["p10", "p50", "p90"]].to_numpy()
            actual = replay[replay.model == model].sort_values("lead_day")[["p10", "p50", "p90"]].to_numpy()
            differences.append(float(np.abs(reference-actual).max()))
            print(f"  {model} maximum reload difference: {differences[-1]:.8f} m3/s", flush=True)
            # Mixture quadrature uses exactly the same distribution for duplicate
            # members; preserve quantiles exactly in that degenerate case.
            np.testing.assert_allclose(reference, actual, rtol=1e-5, atol=1e-3)
        forecast_manifest = json.loads((temp / "output/forecast_manifest.json").read_text())
        assert forecast_manifest["trained_on_reanalysis"] and forecast_manifest["historical_replay"]
    output = root / "verification"
    output.mkdir(exist_ok=True)
    unit = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(Path(__file__).parent / "tests"), "-v"],
                          text=True, capture_output=True)
    (output / "unit_tests.txt").write_text(unit.stdout + unit.stderr, encoding="utf-8")
    assert unit.returncode == 0, unit.stderr
    for path, daily in derived_daily:
        daily.to_csv(path, index_label="date")
    updated = [refresh_probabilities(folder) for folder in folders]
    predictions = pd.concat(updated[:-1], ignore_index=True)
    predictions.to_csv(root / "reports/rolling_predictions.csv.gz", index=False)
    manifest["probability_method"] = "Analytic equal-member mixture CDF, piecewise-linear conditional P10/P50/P90 with constant tails"
    manifest["verification_complete"] = True
    save_json(root / "run_manifest.json", manifest)
    save_json(output / "verification.json", {"passed": True, "source_files_unchanged": True,
              "rolling_prediction_rows": len(predictions), "folds_and_final": checks,
              "reload_ensemble_check": {"members": 2, "max_quantile_difference_cumecs": max(differences),
                  "data": "Two duplicate reanalysis trajectories with synthetic archive-format labels, execution test only; not real forecasts"},
              "unit_tests_passed": True})
    # Refresh presentation-only reports; no calibration, model fitting or scoring
    # inputs are changed by this verification command.
    scores, threshold_scores = evaluate(predictions, root / "reports")
    write_report(root, predictions, scores, threshold_scores, config, manifest)
    snapshot = root / "source"
    snapshot.mkdir(exist_ok=True)
    for path in Path(__file__).parent.glob("*.py"):
        shutil.copyfile(path, snapshot / path.name)
    for path in Path(__file__).parent.glob("*.md"):
        shutil.copyfile(path, snapshot / path.name)
    tests = snapshot / "tests"
    tests.mkdir(exist_ok=True)
    for path in (Path(__file__).parent / "tests").glob("*.py"):
        shutil.copyfile(path, tests / path.name)
    save_json(root / "artifact_manifest.json", {str(p.relative_to(root)): {"bytes": p.stat().st_size, "sha256": digest(p)}
              for p in sorted(root.rglob("*")) if p.is_file() and p.name not in ["artifact_manifest.json", "training.log"]})
    print(json.dumps({"passed": True, "rolling_prediction_rows": len(predictions),
                      "trained_lightgbm_models": 30 * len(folders), "trained_lstm_checkpoints": len(folders),
                      "max_reload_difference_cumecs": max(differences)}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    verify(args.run)
