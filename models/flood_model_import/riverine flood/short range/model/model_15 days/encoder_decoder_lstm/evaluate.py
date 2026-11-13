"""Matched 15-lead evaluation and explicit reporting of leads 7-15."""
# Model workspace import path.
import sys as _layout_sys
from pathlib import Path as _LayoutPath
for _layout_parent in _LayoutPath(__file__).resolve().parents:
    if (_layout_parent / 'evaluation comparison' / 'common').is_dir():
        _layout_sys.path.insert(0, str(_layout_parent / 'model' / 'model_15 days'))
        _layout_sys.path.insert(0, str(_layout_parent / 'model' / 'model_10 days'))
        _layout_sys.path.insert(0, str(_layout_parent / 'evaluation comparison' / 'common'))
        break

import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader
from data import DataStore, StreamflowDataset, inverse_flow, load_config, years
from lstm.train import load_checkpoint, check_evaluation_years, seed_everything
from encoder_decoder_lstm.model import HindcastForecastLSTM
from encoder_decoder_lstm.train import save_json, sha
from evaluate import metrics, markdown
from persistence.model import Persistence
from climatology.model import Climatology


def predict(cfg, store, checkpoint, split):
    check_evaluation_years(cfg, checkpoint)
    dataset = StreamflowDataset(store, split, checkpoint["statistics"])
    model = HindcastForecastLSTM(cfg, *dataset.dimensions())
    model.load_state_dict(checkpoint["model_state"])
    model.eval()
    values = []
    with torch.no_grad():
        for batch in DataLoader(dataset, batch_size=cfg["training"]["batch_size"]):
            result = model(batch["history"], batch["future"], batch["static"])
            assert result.shape[1:] == (15, 5)
            values.append(inverse_flow(result.numpy(), checkpoint["statistics"]))
    predictions = np.concatenate(values)
    assert np.isfinite(predictions).all() and (np.diff(predictions, axis=-1) >= 0).all()
    return dataset, predictions


def evaluate(cfg):
    root = Path(cfg["_root"])
    out = root / cfg["experiment"]["report_dir"]
    out.mkdir(parents=True, exist_ok=True)
    seed_everything(42, cfg["training"]["cpu_threads"])
    torch.set_flush_denormal(True)
    stages = json.loads((root / "runs/stages.json").read_text())
    store = DataStore(cfg)
    checkpoints = {stage: load_checkpoint(path) for stage, path in stages.items()}
    result = {stage: predict(cfg, store, ckpt, "test") for stage, ckpt in checkpoints.items()}
    dataset = result["finetuned"][0]
    assert all(other.samples == dataset.samples for other, _ in result.values())
    quantiles = {stage: values for stage, (_, values) in result.items()}
    point = {stage: values[:, :, 2] for stage, values in quantiles.items()}
    point["persistence"] = Persistence().predict(dataset)
    point["climatology"] = Climatology().fit(store).predict(dataset)
    train_frame = store.frames["marala"]
    threshold = float(train_frame.loc[train_frame.index.year.isin(years(cfg["splits"]["train"])), "q_cumecs"].quantile(.95))
    rows = []
    for index, (basin, origin) in enumerate(dataset.samples):
        frame = store.frames[basin]
        issue = frame.index[origin]
        for lead in range(15):
            date = issue + pd.Timedelta(days=lead+1)
            row = {"issue_date": issue, "target_date": date, "lead_day": lead+1,
                   "year": date.year, "monsoon": date.month in [6, 7, 8, 9],
                   "observed_cumecs": frame.q_cumecs.loc[date]}
            row.update({stage: prediction[index, lead] for stage, prediction in point.items()})
            for stage, prediction in quantiles.items():
                row.update({f"{stage}_q{q:g}": prediction[index, lead, j] for j, q in enumerate(cfg["model"]["quantiles"])})
                row[f"{stage}_probability_exceedance"] = 1 - np.interp(
                    threshold, prediction[index, lead], cfg["model"]["quantiles"], left=0., right=1.)
            rows.append(row)
    table = pd.DataFrame(rows)
    table.to_csv(out / "predictions.csv.gz", index=False)
    scores, seasonal, calibration = [], [], []
    for lead, group in table.groupby("lead_day"):
        for stage in point:
            for season, use in [("all", group), ("monsoon", group[group.monsoon])]:
                valid = use[np.isfinite(use.observed_cumecs) & np.isfinite(use[stage])]
                score = {"model": stage, "lead_day": lead, "season": season,
                         **metrics(valid.observed_cumecs, valid[stage], threshold, threshold)}
                if not len(valid):
                    continue
                actual, predicted = valid.observed_cumecs >= threshold, valid[stage] >= threshold
                tp, fp, fn = int((actual & predicted).sum()), int((~actual & predicted).sum()), int((actual & ~predicted).sum())
                probability = valid[f"{stage}_probability_exceedance"] if stage in quantiles else predicted.astype(float)
                score.update({"POD": tp/(tp+fn) if tp+fn else np.nan,
                              "FAR": fp/(tp+fp) if tp+fp else np.nan,
                              "CSI": tp/(tp+fp+fn) if tp+fp+fn else np.nan,
                              "Brier_score": float(((probability-actual)**2).mean()),
                              "threshold_cumecs": threshold})
                (scores if season == "all" else seasonal).append(score)
            if stage in quantiles:
                valid = group[group.observed_cumecs.notna()]
                lower, upper = valid[f"{stage}_q0.05"], valid[f"{stage}_q0.95"]
                calibration.append({"model": stage, "lead_day": lead, "n": len(valid), "nominal_coverage": .9,
                                    "observed_coverage": float(valid.observed_cumecs.between(lower, upper).mean()),
                                    "mean_width_cumecs": float((upper-lower).mean())})
    scores, seasonal, calibration = pd.DataFrame(scores), pd.DataFrame(seasonal), pd.DataFrame(calibration)
    scores.to_csv(out / "scores_by_lead.csv", index=False)
    seasonal.to_csv(out / "scores_monsoon_by_lead.csv", index=False)
    calibration.to_csv(out / "quantile_calibration.csv", index=False)
    focused = scores[scores.lead_day.between(7, 15)]
    focused.to_csv(out / "scores_leads07_15.csv", index=False)
    summary = focused.groupby("model")[["KGE", "NSE", "MAE_cumecs", "RMSE_cumecs", "Brier_score"]].mean()
    summary.to_csv(out / "mean_scores_leads07_15.csv")
    compare = scores[scores.model.eq("finetuned")].set_index("lead_day")[["NSE", "KGE", "MAE_cumecs"]].subtract(
        scores[scores.model.eq("scratch")].set_index("lead_day")[["NSE", "KGE", "MAE_cumecs"]])
    compare = compare.rename(columns={"NSE": "finetuned_minus_scratch_NSE", "KGE": "finetuned_minus_scratch_KGE",
                                      "MAE_cumecs": "finetuned_minus_scratch_MAE_cumecs"})
    compare.to_csv(out / "transfer_comparison.csv")
    hashes = json.loads((root / "runs/source_hashes.json").read_text())
    assert all(sha(path) == h for path, h in hashes.items())
    # Reload a checkpoint and reproduce one complete horizon, independently of training.
    checkpoint = load_checkpoint(stages["finetuned"])
    item = dataset[0]
    model = HindcastForecastLSTM(cfg, *dataset.dimensions()).eval()
    model.load_state_dict(checkpoint["model_state"])
    with torch.no_grad():
        reloaded = inverse_flow(model(*(item[k][None] for k in ["history", "future", "static"])).numpy(), checkpoint["statistics"])
    np.testing.assert_allclose(reloaded[0], quantiles["finetuned"][0], rtol=1e-4, atol=.01)
    verification = {"passed": True, "output_shape_single_issue": list(reloaded.shape),
                    "no_quantile_crossing": True, "input_sources_unchanged": True,
                    "inherited_test_years_excluded": True, "test_samples": len(dataset),
                    "observed_target_pairs": int(table.observed_cumecs.notna().sum()),
                    "forecast_mode": cfg["data"]["forecast_mode"],
                    "training_years": checkpoint["training_years"], "selection_years": checkpoint["selection_years"]}
    save_json(out / "verification.json", verification)
    run_rows = []
    for stage, path in stages.items():
        checkpoint = checkpoints[stage]
        hist = json.loads(Path(path).with_name("history.json").read_text())
        run_rows.append({"stage": stage, "epochs_run": len(hist["epochs"]), "best_epoch": checkpoint["epoch"],
                         "validation_pinball": checkpoint["validation_pinball"],
                         "training_seconds": hist["elapsed_seconds"]})
    selected = json.loads((root / "runs/selected_model.json").read_text())
    report = ["# Actual 15-day seq2seq LSTM training", "", "Run date: 2026-10-30 (Asia/Karachi).", "",
              "A 365-day encoder hands hidden/cell states to a 15-day decoder. Each forward pass returns all "
              "15 leads and five ordered quantiles. Days 7-15 are summarized separately; no observed future discharge "
              "or teacher forcing is used.", "",
              "The local donor-only checkpoint was pretrained on eight observed CAMELS-US basins during 1985-1994, "
              "selected on 1995-1996. This is a workspace-trained checkpoint, not an official global foundation model. "
              "Its 10 lead embeddings were retained; five new rows copy day 10 and learn during fine-tuning. "
              "Observed-discharge/missingness input columns start with zero weights, preserving transferred weather/calendar weights.", "",
              "Public search also found Fine Flood Forecasts, but its released model predicts one day, not a "
              "15-day encoder-decoder sequence. The compatible local donor checkpoint was used instead. "
              "See pretrained_search.json for sources and the selection rationale.", "",
              "Marala train: 2016-2020; validation: 2021; test: 2022-2024. Whole-year chronological partitions "
              "contain every target date in each sample. No target filling is performed. Missing targets are masked. "
              "Normalization is recomputed on Marala training years; both alternatives use the same features, "
              "architecture, target dates, training period and early-stopping criterion. Learning rates differ for transfer and scratch.", "",
              markdown(pd.DataFrame(run_rows)), "",
              f"Selected by validation pinball only: **{selected['selected_stage']}**. Test scores do not select deployment weights.", "",
              "## Means of lead-specific scores, days 7-15", "", markdown(summary.reset_index()), "",
              "## Selected leads", "", markdown(scores[scores.lead_day.isin([1, 7, 10, 15])][["model", "lead_day", "n", "NSE", "KGE", "MAE_cumecs"]]), "",
              f"Fine-tuning has higher NSE than scratch at {int((compare.finetuned_minus_scratch_NSE > 0).sum())}/15 leads "
              f"and higher KGE at {int((compare.finetuned_minus_scratch_KGE > 0).sum())}/15. "
              "A single seed and these previously inspected test years do not establish a robust transfer advantage.", "",
              "## Limits", "",
              "Weather inputs are realized ERA5-Land plus reproducible artificial standardized noise, not archived "
              "issued forecasts or a genuine meteorological ensemble. These are stand-in-weather hindcasts and can "
              "overstate operational 7-15-day performance. Weather noise does not demonstrate authentic forecast uncertainty. "
              "Actual forecast-provider inputs need archived-forecast training and validation.", "",
              "Discharge reading times are largely unconfirmed in the historical WAPDA series. Issue-time observed flow "
              "availability and UTC-day alignment require validation. No 2025-2026 accuracy is claimed because complete "
              "weather inputs stop in 2024. Q95 is training-derived, not an official flood category. "
              "Uncertainty tails outside P05/P95 are not modeled, and no coverage guarantee is made.", "",
              "Donor forcings use NLDAS daily rainfall and the midpoint of Tmax/Tmin; Marala uses ERA5-Land rainfall "
              "and daily mean temperature. The source/target climates, basin scales and forcing definitions differ, "
              "so useful transfer must be measured rather than assumed.", "",
              "## Saved outputs", "",
              "- `pretrained/`: original/adapted checkpoint and exact transfer provenance.",
              "- `data/`: isolated, observed-only training table and preservation checks.",
              "- `runs/finetuned/seed_42/` and `runs/scratch/seed_42/`: best weights, optimizer, normalization, config, epochs and year history.",
              "- `runs/selected_model.json`: validation-selected checkpoint for inference.",
              "- `reports/initial/`: predictions, all 15 lead scores, monsoon scores, days 7-15 summary, quantile coverage, plots and verification.", ""]
    (root / "RUN_RESULTS.md").write_text("\n".join(report), encoding="utf-8")
    plot(scores, table, out)
    save_json(root / "runs/artifact_manifest.json", {str(p.relative_to(root)): {"sha256": sha(p), "bytes": p.stat().st_size}
              for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in str(p) and p.name not in ["artifact_manifest.json", "training.log"]})
    print(summary.to_string(), flush=True)
    print(f"Complete: {root / 'RUN_RESULTS.md'}", flush=True)


def plot(scores, table, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    for name, group in scores.groupby("model"):
        for ax, metric in zip(axes, ["NSE", "KGE", "MAE_cumecs"]):
            ax.plot(group.lead_day, group[metric], label=name)
            ax.axvspan(7, 15, alpha=.05)
            ax.set(xlabel="Lead day", ylabel=metric)
    axes[0].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out / "skill_by_lead.png", dpi=170)
    plt.close(fig)
    for year in [2022, 2023, 2024]:
        group = table[(table.year == year) & table.monsoon & (table.lead_day == 15)].sort_values("target_date")
        fig, ax = plt.subplots(figsize=(12, 4))
        ax.plot(group.target_date, group.observed_cumecs, color="black", label="Observed")
        ax.plot(group.target_date, group.finetuned, label="Fine-tuned seq2seq")
        ax.plot(group.target_date, group.scratch, label="Scratch", alpha=.7)
        ax.fill_between(group.target_date, group["finetuned_q0.05"], group["finetuned_q0.95"], alpha=.15)
        ax.set(title=f"{year} monsoon: day-15 hindcast, P05-P95", ylabel="Discharge m3/s")
        ax.legend()
        fig.tight_layout()
        fig.savefig(out / f"monsoon_{year}_lead15.png", dpi=150)
        plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(Path(__file__).with_name("config.yaml")))
    evaluate(load_config(parser.parse_args().config))
