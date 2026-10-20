"""Create reproducible, hypothetical HEC-RAS confluence sensitivity cases.

The downloaded USACE sample remains untouched under tools/hec_ras/samples.
Only the copied boundary HDF is changed. Run ``ras plan prepare`` and
``ras plan solve`` afterward; this script does not create hydraulic results.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import h5py

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "tools/hec_ras/samples/escondida"
RUNS = ROOT / "tools/hec_ras/runs"
RECORD = Path(__file__).with_name("escondida-inputs.json")
CASES = {
    "mainstem": {"branch_cfs": 0.0, "rain_in_per_hr": 0.0},
    "tributary": {"branch_cfs": 50.0, "rain_in_per_hr": 0.0},
    "tributary_rain": {"branch_cfs": 50.0, "rain_in_per_hr": 0.02},
}


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def create(name: str) -> dict:
    target = RUNS / f"escondida_{name}"
    if target.exists():
        raise FileExistsError(f"Case exists; preserving {target}")
    shutil.copytree(SAMPLE, target)
    project_path = target / "Escondida Example Project.ras"
    project = project_path.read_text("utf8")
    original = '<GeometryAssociation Geometry="Base Cell Size" Terrain="Terrain" />'
    if project.count(original) != 1:
        raise ValueError("Expected the sample's base geometry terrain association")
    project_path.write_text(project.replace(original, '<GeometryAssociation Geometry="Base Cell Size" Terrain="Terrain" N_Values="N Values" />'), encoding="utf8")
    boundary_path = target / "Boundary Conditions/Boundary Condition.h5"
    values = CASES[name]
    with h5py.File(boundary_path, "r+") as file:
        attributes = file["Boundary Conditions/BC Lines/Attributes"]
        rows = attributes[:]
        flow_rows = [index for index, row in enumerate(rows) if row["Hydr Type"] == b"Flow"]
        if len(flow_rows) != 2 or rows[flow_rows[0]]["Local Data Type"] != b"Table":
            raise ValueError("Unexpected native main/branch flow boundary layout")
        if rows[flow_rows[1]]["Local Data Type"] != b"Constant":
            raise ValueError("Expected the second inflow to be constant")
        rows[flow_rows[1]]["Constant"] = values["branch_cfs"]
        # The native compound HDF type must be retained: h5py's high-level
        # assignment truncates some of this older file's fixed-width strings.
        attributes.id.write(h5py.h5s.ALL, h5py.h5s.ALL, rows, mtype=attributes.id.get_type())
        precipitation = file["Boundary Conditions/Meteorology/Precipitation"]
        if precipitation.attrs["Spatial Data Type"] != b"Constant":
            raise ValueError("Expected a constant precipitation boundary")
        precipitation.attrs.modify("Enabled", 1)
        precipitation.attrs.modify("Constant", values["rain_in_per_hr"])
    with h5py.File(boundary_path) as file:
        actual = file["Boundary Conditions/BC Lines/Attributes"][:]
        assert float(actual[flow_rows[1]]["Constant"]) == values["branch_cfs"]
        assert abs(float(file["Boundary Conditions/Meteorology/Precipitation"].attrs["Constant"]) - values["rain_in_per_hr"]) < 1e-6
    return {
        "id": name,
        "parameters": values,
        "main_flow_table_cfs": "unchanged from official sample (300–2800 cfs)",
        "run_dir": str(target.relative_to(ROOT)).replace("\\", "/"),
        "boundary_condition_sha256": sha256(boundary_path),
        "project_association_sha256": sha256(project_path),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if name not in CASES:
        raise ValueError(f"Choose one of {tuple(CASES)}")
    source = {str(path.relative_to(SAMPLE)).replace("\\", "/"): sha256(path)
              for path in SAMPLE.rglob("*") if path.is_file() and "Export" not in path.parts}
    record = json.loads(RECORD.read_text("utf8")) if RECORD.exists() else {
        "source": "USACE HEC-RAS 2025 sample: Escondida Example Project",
        "sample_command": "ras sample pull 'Escondida Example Project' tools/hec_ras/samples/escondida",
        "source_files_sha256": source,
        "cases": [],
        "warning": "Hypothetical, uncalibrated demonstration inputs; not a forecast",
    }
    entry = create(name)
    record["cases"].append(entry)
    RECORD.write_text(json.dumps(record, indent=2) + "\n", encoding="utf8")
    print(json.dumps(entry, indent=2))


if __name__ == "__main__":
    main()
