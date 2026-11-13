"""Prepare an isolated dataset, adapt the donor checkpoint and train both controls."""
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
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import torch
from data import load_config, resolve, public_config
from lstm.train import load_checkpoint, run_training
from encoder_decoder_lstm_finetuned.model import adapt_checkpoint


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def prepare(cfg):
    source = resolve(cfg, cfg["experiment"]["source_daily_file"])
    output = resolve(cfg, cfg["data"]["daily_file"])
    original = pd.read_csv(source, parse_dates=["date"])
    # No weather is available past 2024; do not silently fill 2025-2026 forcings.
    selected = original[original.date.between("2015-01-01", "2024-12-31")]
    prepared = selected[["date", "basin_id", "rain_era5_mm", "temperature_c", "q_cumecs", "q_source"]].rename(
        columns={"rain_era5_mm": "precipitation_mm"})
    if not np.isfinite(prepared[["precipitation_mm", "temperature_c"]]).all().all():
        raise ValueError("Missing weather in selected training period")
    if output.exists():
        actual = pd.read_csv(output, parse_dates=["date"])
        pd.testing.assert_frame_equal(actual, prepared.reset_index(drop=True), check_exact=False)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        prepared.to_csv(output, index=False, na_rep="NaN")
    pd.testing.assert_series_equal(pd.read_csv(output).q_cumecs, prepared.q_cumecs.reset_index(drop=True),
                                   check_names=False, check_exact=False, rtol=1e-14, atol=1e-14)
    report = {"source": str(source), "sha256": sha(source), "prepared_sha256": sha(output),
              "rows": len(prepared), "observed_discharge_days": int(prepared.q_cumecs.notna().sum()),
              "target_values_and_missingness_preserved": True, "no_target_imputation": True,
              "period": [str(prepared.date.min().date()), str(prepared.date.max().date())],
              "rain_source": "ERA5-Land rain_era5_mm, matching donor variable meaning; precipitation is mm/day",
              "temperature_source": "ERA5-Land mean 2m temperature in Celsius"}
    save_json(output.with_name("preparation_report.json"), report)
    return source


def run(config_path, resume=False):
    cfg = load_config(config_path)
    root = Path(cfg["_root"])
    manifest_path = root / "runs/stages.json"
    if manifest_path.exists() and not resume:
        raise FileExistsError("Existing experiment; choose new output directories or --resume")
    source = prepare(cfg)
    original = resolve(cfg, cfg["experiment"]["source_pretrained_checkpoint"])
    if not original.exists():
        raise FileNotFoundError("Configured donor checkpoint missing; inspect pretrained_search.json and configure scratch-only explicitly")
    checkpoint = load_checkpoint(original)
    if checkpoint.get("training_stage") != "pretrain" or len(checkpoint.get("pretraining_basins", [])) < 2:
        raise ValueError("Expected verified multi-basin donor-only pretrained checkpoint")
    protected = {str(source): sha(source), str(original): sha(original)}
    adapted_path = resolve(cfg, cfg["experiment"]["adapted_checkpoint"])
    adapted = adapt_checkpoint(checkpoint, cfg)
    if not adapted_path.exists():
        adapted_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, adapted_path.with_name("camels_us_original_10day.pt"))
        torch.save(adapted, adapted_path)
    else:
        actual = load_checkpoint(adapted_path)
        assert all(torch.equal(actual["model_state"][k], v) for k, v in adapted["model_state"].items())
    save_json(adapted_path.with_name("transfer_manifest.json"), {
        "source_checkpoint": str(original), "source_sha256": sha(original), "adapted_sha256": sha(adapted_path),
        "pretraining_basins": checkpoint["pretraining_basins"], "training_years": checkpoint["training_years"],
        "selection_years": checkpoint["selection_years"], "adaptation": adapted["transfer_adaptation"],
        "normalization": "recomputed on 2016-2020 Marala only; transferred weights readapt during fine-tuning"})
    stages = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    for stage, initial in [("finetuned", adapted_path), ("scratch", None)]:
        if stage != cfg.get("variant_stage"):
            continue
        if stage != cfg.get("variant_stage"):
            continue
        target = resolve(cfg, cfg["finetuning" if initial else "training"]["output_dir"]) / "seed_42/best.pt"
        if resume and stage in stages and target.exists():
            print(f"Reusing complete stage {stage}", flush=True)
            continue
        if target.exists():
            raise FileExistsError(f"Incomplete/existing stage checkpoint: {target}; preserve it and choose a new output_dir")
        print(f"Training {stage}: 365-day encoder, whole 15-day decoder", flush=True)
        result = run_training(cfg, 42, initial_checkpoint=initial)
        trained = load_checkpoint(result)
        trained["training_stage"] = stage
        trained["forecast_output"] = "batch x 15 lead days x 5 ordered quantiles, one forward pass"
        if initial:
            trained["pretraining_basins"] = checkpoint["pretraining_basins"]
            trained["transfer_adaptation"] = adapted["transfer_adaptation"]
        torch.save(trained, result)
        stages[stage] = str(result)
        save_json(manifest_path, stages)
    selected = min(stages, key=lambda stage: load_checkpoint(stages[stage])["validation_pinball"])
    save_json(root / "runs/selected_model.json", {"selection_split": "2021 validation only", "selected_stage": selected,
              "checkpoint": stages[selected], "validation_pinball": load_checkpoint(stages[selected])["validation_pinball"]})
    if not all(sha(p) == h for p, h in protected.items()):
        raise RuntimeError("Original data/checkpoint changed")
    save_json(root / "runs/source_hashes.json", protected)
    (root / "requirements-lock.txt").write_text(subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True))
    from encoder_decoder_lstm_finetuned.evaluate import evaluate
    evaluate(cfg)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(Path(__file__).with_name("config.yaml")))
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    root = Path(args.config).resolve().parent
    with (root / "training.log").open("a", encoding="utf-8") as log:
        class Tee:
            def __init__(self, original): self.original = original
            def write(self, message):
                self.original.write(message)
                log.write(message)
                log.flush()
            def flush(self): self.original.flush(); log.flush()
        original_out, original_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = Tee(original_out), Tee(original_err)
        try:
            run(args.config, args.resume)
        finally:
            sys.stdout, sys.stderr = original_out, original_err


if __name__ == "__main__":
    main()
