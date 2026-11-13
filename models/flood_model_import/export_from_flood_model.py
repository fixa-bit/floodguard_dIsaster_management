"""Refresh this folder from the flood_model project.

Copies trained models (weights, fitted parameters, run configs, code, configs,
READMEs and licences) and mirrors the flood_model folder layout. Datasets,
predictions, evaluation reports, plots, logs and caches are not copied.

Only needed when models are retrained in flood_model; the disaster_management
app itself never reads from flood_model.

    python export_from_flood_model.py                 # dry run: list what would be copied
    python export_from_flood_model.py --apply         # replace the copy and rewrite MANIFEST.json
    python export_from_flood_model.py --source <path> # flood_model project root (default below)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
DEFAULT_SOURCE = Path(r"D:\projects\flood_model\flood_model")

ROOTS = [
    "riverine flood/short range/model",
    "riverine flood/short range/seasonal",
    "riverine flood/short range/evaluation comparison/common",  # shared code imported by short-range models
    "riverine flood/long range/model",
    "flash flood/short range/model",
]

# Directories never entered.
SKIP_DIRS = {"__pycache__", ".venv", ".pytest_cache", "node_modules", ".ipynb_checkpoints"}
# Directories holding datasets, predictions or evaluation output: only code and DATA_METADATA are kept.
DATA_DIRS = {"data", "dataset", "reports", "outputs", "forecasts", "sources"}
# Small metadata files inside data folders that model loaders and feature builders read.
DATA_METADATA = {"catchment_metadata.json", "band_metadata.json", "native_grid_band_weights.json"}
# Upstream reference copies: keep only licence and provenance notes.
REFERENCE_DIR = "source_reference"
REFERENCE_KEEP = {"license", "license.txt", "license.md", "readme.md", "provenance.json"}

WEIGHT_EXT = {".pt", ".pth", ".ckpt", ".safetensors", ".onnx", ".pkl", ".joblib", ".h5", ".keras", ".cbm", ".ubj"}
KEEP_EXT = WEIGHT_EXT | {".py", ".yaml", ".yml", ".json", ".md", ".txt", ".toml", ".cfg", ".ini"}
KEEP_NAMES = {"license", "notice"}

# Fitted parameters stored outside run folders, needed to reproduce a model.
EXTRA_FILES = {
    "riverine flood/long range/model/baselines/reports/climatology_2016_2023.csv",
    "riverine flood/long range/model/baselines/reports/damped_persistence_coefficients.csv",
    "riverine flood/long range/model/calibration/reports/conformal_offsets.csv",
    "riverine flood/long range/model/calibration/reports/conformal_offsets_deployment.csv",
    "riverine flood/long range/model/extremes/reports/peak_model.json",
    # Read by the HBV models' data loaders (their config paths point here).
    "riverine flood/short range/dataset/chenab_marala/raw/marala/temperature/google_earth_engine/catchment_metadata.json",
}

# Managed top-level folders in this directory (first path part of each root/extra file).
MANAGED = sorted({PurePosixPath(p).parts[0] for p in ROOTS + sorted(EXTRA_FILES)})


def keep(rel: PurePosixPath) -> bool:
    parts = [p.lower() for p in rel.parts[:-1]]
    name, suffix = rel.name.lower(), rel.suffix.lower()
    if str(rel) in EXTRA_FILES:
        return True
    if any(p in SKIP_DIRS for p in parts):
        return False
    if REFERENCE_DIR in parts:
        return parts[-1] == REFERENCE_DIR and name in REFERENCE_KEEP
    if any(p in DATA_DIRS for p in parts):
        return suffix == ".py" or name in DATA_METADATA
    return name in KEEP_NAMES or suffix in KEEP_EXT


def trained_artifact(rel: PurePosixPath) -> bool:
    """Saved model state: weights, LightGBM boosters, HBV calibrations, fitted parameter tables."""
    p, suffix = rel.as_posix(), rel.suffix.lower()
    if suffix in WEIGHT_EXT or p in EXTRA_FILES and "catchment_metadata" not in p:
        return True
    if "/runs/" in p and suffix == ".txt" and rel.name.startswith(("lead_", "lightgbm_")):
        return True  # LightGBM boosters saved as text
    return "/runs/" in p and rel.name == "calibration.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def select(source: Path) -> list[PurePosixPath]:
    chosen = []
    for root in ROOTS:
        for path in sorted((source / root).rglob("*")):
            rel = PurePosixPath(path.relative_to(source).as_posix())
            if path.is_file() and keep(rel):
                chosen.append(rel)
    chosen += [PurePosixPath(p) for p in sorted(EXTRA_FILES)
               if not any(p.startswith(r + "/") for r in ROOTS)]
    return chosen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    source = args.source.resolve()

    chosen = select(source)
    total = sum((source / r).stat().st_size for r in chosen)
    print(f"{len(chosen)} files, {total / 1e6:.1f} MB from {source}")
    if not args.apply:
        for rel in chosen:
            print(f"{(source / rel).stat().st_size:>10}  {rel}")
        return

    for name in MANAGED:
        shutil.rmtree(HERE / name, ignore_errors=True)
    files = []
    for rel in chosen:
        src, dst = source / rel, HERE / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        digest = sha256(dst)
        if digest != sha256(src):
            raise SystemExit(f"checksum mismatch: {rel}")
        files.append({"path": str(rel), "bytes": src.stat().st_size, "sha256": digest,
                      "trained_artifact": trained_artifact(rel)})

    commit = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(source), "status", "--porcelain", "--", *ROOTS],
                           capture_output=True, text=True).stdout.strip()
    manifest = {
        "about": "Local copy of the trained flood_model models. Each 'path' is relative to this folder "
                 "and to the flood_model project root, which this folder mirrors.",
        "source_project": str(source),
        "source_git_commit": commit or None,
        "source_had_uncommitted_model_changes": bool(dirty),
        "exported_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "roots": ROOTS,
        "extra_files": sorted(EXTRA_FILES),
        "file_count": len(files),
        "trained_artifact_count": sum(f["trained_artifact"] for f in files),
        "total_bytes": total,
        "files": files,
    }
    (HERE / "MANIFEST.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"copied {len(files)} files ({manifest['trained_artifact_count']} trained artifacts) to {HERE}")


if __name__ == "__main__":
    main()
