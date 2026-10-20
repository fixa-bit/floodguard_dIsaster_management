"""Verify a retained run and replay its independent held-out predictions offline."""
import argparse
import csv
import json
from pathlib import Path

import numpy as np

from .core import HERE, build_rows, load_model, load_observations, predict, sha256
from .train import split_rows


def verify_inventory(folder):
    folder = Path(folder).resolve()
    manifest = json.loads((folder / "RUN_MANIFEST.json").read_text(encoding="utf-8"))
    for name, record in manifest["files"].items():
        path = (folder / name).resolve()
        if not path.is_relative_to(folder) or not path.is_file():
            raise ValueError(f"Missing or invalid retained file: {name}")
        if path.stat().st_size != record["bytes"] or sha256(path) != record["sha256"]:
            raise ValueError(f"Retained file changed: {name}")
    return len(manifest["files"])


def validate(folder):
    folder = Path(folder)
    count = verify_inventory(folder)
    history, _ = load_observations([folder / "data/observations.csv"])
    cfg = json.loads((folder / "data/manifest.json").read_text(encoding="utf-8"))["config"]
    with (folder / "artifacts/holdout_predictions_2026.csv").open(encoding="utf-8", newline="") as handle:
        retained = list(csv.DictReader(handle))
    replayed = 0
    for horizon in cfg["horizons_days"]:
        rows, _ = build_rows(history, horizon)
        test = split_rows(rows, cfg)["test"]
        saved = [row for row in retained if int(row["horizon_days"]) == horizon]
        if len(test) != len(saved):
            raise ValueError("Held-out target count changed")
        for row, expected in zip(test, saved, strict=True):
            if row["target_at"] != expected["target_at"] or row["issued_at"] != expected["origin_observed_at"]:
                raise ValueError("Held-out timestamps changed")
            np.testing.assert_allclose(row["target_cumecs"], float(expected["actual_cumecs"]), rtol=1e-10)
        for role in ("champion", "best_learned", "persistence", "linear_trend"):
            model = load_model(folder / f"artifacts/evaluation_models/{horizon}d/{role}")
            if model["training_last_target"] >= test[0]["issued_at"]:
                raise ValueError("Evaluation fit includes future labels")
            np.testing.assert_allclose(predict(model, test), [float(row[role + "_cumecs"]) for row in saved], rtol=1e-7, atol=1e-7)
        replayed += len(test)
    return {"verified_files": count, "measured_days": len(history), "replayed_holdout_targets": replayed, "status": "passed"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    pointer = json.loads((HERE / "LATEST_RUN.json").read_text(encoding="utf-8"))
    parser.add_argument("--run", type=Path, default=HERE / pointer["path"])
    args = parser.parse_args()
    print(json.dumps(validate(args.run), indent=2))
