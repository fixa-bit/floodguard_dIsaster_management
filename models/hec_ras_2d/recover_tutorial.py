"""Recover complete CRC-checked members from the interrupted official tutorial ZIP.

The Confluence server may close a chunked transfer before the central directory.
Only fully decompressed members are retained; this is an input recovery utility,
not evidence that the entire source archive was downloaded.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from stream_unzip import stream_unzip

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tools/hec_ras/downloads/Simple_Plans.zip.partial"
TARGET = ROOT / "tools/hec_ras/tutorial_recovered"
WANTED = (
    "Simple_Plans/Boundary Conditions/January 1997 Event.h5",
    "Simple_Plans/GISData/projection.prj",
    "Simple_Plans/Geometries/1c. 400ft nCh wCh.h5",
    "Simple_Plans/Geometries/2a. 200ft wCh1.h5",
    "Simple_Plans/Plans/1c. 400ft nCh wCh.h5",
    "Simple_Plans/Plans/2a. 200ft wCh1.h5",
    "Simple_Plans/Results/1c. 400ft nCh wCh.h5",
    "Simple_Plans/Results/2a. 200ft wCh1.h5",
)


def chunks():
    with SOURCE.open("rb") as handle:
        while part := handle.read(1 << 20):
            yield part


def main():
    TARGET.mkdir(parents=True, exist_ok=True)
    records = []
    try:
        for raw_name, declared_size, content in stream_unzip(chunks()):
            name = raw_name.decode("utf-8")
            if name not in WANTED:
                for _ in content:
                    pass
                continue
            target = TARGET / name
            target.parent.mkdir(parents=True, exist_ok=True)
            incomplete = target.with_suffix(target.suffix + ".incomplete")
            digest = hashlib.sha256()
            size = 0
            try:
                with incomplete.open("wb") as output:
                    for part in content:
                        output.write(part)
                        digest.update(part)
                        size += len(part)
                if declared_size is not None and size != declared_size:
                    raise ValueError(f"Size mismatch: {name}: {size} != {declared_size}")
                incomplete.replace(target)
                records.append({"member": name, "bytes": size, "sha256": digest.hexdigest(), "crc_checked": True})
                print("Recovered", name, size, flush=True)
            except Exception:
                incomplete.unlink(missing_ok=True)
                raise
    except Exception as exc:
        print(f"Archive ended before ZIP directory: {type(exc).__name__}: {exc}", flush=True)
    manifest = {"source_url": "https://www.hec.usace.army.mil/confluence/rasdocs/hecras/files/latest/334760427/334763850/1/1768486562468/Simple_Plans.zip",
                "archive_complete": False, "partial_bytes": SOURCE.stat().st_size,
                "partial_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(), "members": records}
    (ROOT / "models/hec_ras_2d/recovered-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf8")


if __name__ == "__main__":
    main()
