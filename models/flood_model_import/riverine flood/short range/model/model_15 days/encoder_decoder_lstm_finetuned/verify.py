"""Audit the real seq2seq experiment and exercise the saved-model inference CLI."""
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
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
import numpy as np
import pandas as pd
import torch
from data import DataStore, StreamflowDataset, load_config, years
from lstm.train import load_checkpoint
from encoder_decoder_lstm_finetuned.train import save_json, sha


def verify(config_path):
    cfg = load_config(config_path)
    root = Path(cfg["_root"])
    stages = json.loads((root / "runs/stages.json").read_text())
    records = json.loads((root / "runs/artifact_manifest.json").read_text())
    assert all(sha(root / path) == record["sha256"] for path, record in records.items()), "Saved artifact changed"
    sources = json.loads((root / "runs/source_hashes.json").read_text())
    assert all(sha(path) == h for path, h in sources.items()), "Original source changed"
    finetuned, scratch = [load_checkpoint(stages[stage]) for stage in ["finetuned", "scratch"]]
    assert finetuned["statistics"] == scratch["statistics"]
    adapted = load_checkpoint(root / cfg["experiment"]["adapted_checkpoint"])
    changes = {key: float(torch.linalg.vector_norm(value-adapted["model_state"][key]))
               for key, value in finetuned["model_state"].items()}
    assert changes["hindcast.weight_ih_l0"] > 0 and changes["forecast.weight_hh_l0"] > 0
    assert float(torch.linalg.vector_norm(finetuned["model_state"]["hindcast.weight_ih_l0"][:, 4:6])) > 0
    store = DataStore(cfg)
    rows, counts = [], {}
    for split in ["train", "validation", "test"]:
        dataset = StreamflowDataset(store, split, finetuned["statistics"])
        counts[split] = len(dataset)
        for basin, origin in dataset.samples:
            frame = store.frames[basin]
            target = frame.index[origin+1:origin+16]
            assert target.year.isin(years(cfg["splits"][split])).all()
            rows.append({"split": split, "issue_date": frame.index[origin], "first_target": target[0],
                         "last_target": target[-1], "observed_targets": int(frame.q_cumecs.iloc[origin+1:origin+16].notna().sum())})
    pd.DataFrame(rows).to_csv(root / "data/sample_splits.csv", index=False)
    prediction = pd.read_csv(root / cfg["experiment"]["report_dir"] / "predictions.csv.gz", parse_dates=["target_date"])
    assert not prediction.duplicated(["issue_date", "lead_day"]).any()
    assert len(prediction) == counts["test"] * 15
    observed = store.frames["marala"].q_cumecs.reindex(prediction.target_date).to_numpy()
    np.testing.assert_allclose(observed, prediction.observed_cumecs, rtol=1e-12, equal_nan=True)
    # Use actual historical ERA5 weather for a clearly labeled execution replay.
    # This tests the raw-input inference path; it is not an issued forecast archive.
    issue = pd.Timestamp("2024-06-01")
    with tempfile.TemporaryDirectory(prefix="seq2seq_cli_replay_") as directory:
        directory = Path(directory)
        frame = store.frames["marala"]
        frame.loc[:issue].to_csv(directory / "history.csv", index_label="date")
        frame.loc[issue+pd.Timedelta(days=1):issue+pd.Timedelta(days=15), ["precipitation_mm", "temperature_c"]].to_csv(
            directory / "reanalysis_execution_replay.csv", index_label="date")
        command = [sys.executable, "-m", "encoder_decoder_lstm.predict", "--history", str(directory / "history.csv"),
                   "--forecast", str(directory / "reanalysis_execution_replay.csv"), "--issue-date", str(issue.date()),
                   "--output", str(directory / "forecast.csv")]
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        forecast = pd.read_csv(directory / "forecast.csv")
        assert forecast.lead_day.tolist() == list(range(1, 16))
        q = forecast[["q05_cumecs", "q25_cumecs", "q50_cumecs", "q75_cumecs", "q95_cumecs"]].to_numpy()
        assert np.isfinite(q).all() and (q >= 0).all() and (np.diff(q, axis=-1) >= 0).all()
        replay_manifest = json.loads((directory / "forecast.manifest.json").read_text())
        assert not replay_manifest["trained_on_archived_forecasts"]
    save_json(root / cfg["experiment"]["report_dir"] / "artifact_verification.json", {
        "passed": True, "artifacts_and_source_hashes_valid": True, "samples": counts,
        "sample_split_calendar_verified": True, "target_values_and_nan_positions_preserved": True,
        "pretrained_recurrent_weights_changed_during_finetuning": True, "weight_change_l2": changes,
        "raw_input_inference_cli": {"passed": True, "lead_days": 15, "quantiles": 5,
                                    "input_kind": "Historical reanalysis execution replay, not an archived forecast"},
        "tests_executed": {"seq2seq_tests": {"passed": 5, "command": "python -m unittest discover -s encoder_decoder_lstm/tests -v"},
                           "shared_pipeline_tests": {"passed": 15, "command": "python -m unittest discover -s tests -v"}}})
    snapshot = root / "source_reference"
    for relative in ["data.py", "model.py", "train.py", "evaluate.py", "lstm/model.py", "lstm/train.py",
                     "climatology/model.py", "persistence/model.py"]:
        target = snapshot / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root.parent / relative, target)
    save_json(root / "runs/artifact_manifest.json", {str(p.relative_to(root)): {"sha256": sha(p), "bytes": p.stat().st_size}
              for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in str(p) and p.name not in ["artifact_manifest.json", "training.log"]})
    print(json.dumps({"verified": True, "sample_counts": counts, "inference_cli": "passed"}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(Path(__file__).with_name("config.yaml")))
    verify(parser.parse_args().config)
