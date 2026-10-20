"""Cache official HEC-RAS installer and example projects with provenance."""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DOWNLOADS = ROOT / "tools/hec_ras/downloads"
SOURCES = {
    "installer": "https://github.com/HydrologicEngineeringCenter/hec-downloads/releases/download/1.0.46/HEC-RAS_701_Setup.exe",
    "examples": "https://github.com/HydrologicEngineeringCenter/hec-downloads/releases/download/1.0.45/Example_Projects_7_0.zip",
    "beta": "https://github.com/HydrologicEngineeringCenter/hec-downloads/releases/download/1.0.44/HEC-RAS_2025_Beta.zip",
    "tutorial": "https://www.hec.usace.army.mil/confluence/rasdocs/hecras/files/latest/334760427/334763850/1/1768486562468/Simple_Plans.zip",
}


def fetch(kind):
    url = SOURCES[kind]
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    target = DOWNLOADS / url.rsplit("/", 1)[-1]
    if not target.exists():
        partial = target.with_suffix(target.suffix + ".partial")
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                expected = int(response.headers.get("content-length", "0"))
                written = 0
                with partial.open("wb") as handle:
                    for chunk in response.iter_bytes(1024 * 1024):
                        handle.write(chunk)
                        written += len(chunk)
                        if written // (25 * 1024 * 1024) != (written - len(chunk)) // (25 * 1024 * 1024):
                            print(f"{kind}: {written // 1048576} MiB", flush=True)
                if expected and written != expected:
                    raise ValueError(f"Incomplete {kind} download: {written} of {expected}")
        partial.replace(target)
    with target.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    record = {"kind": kind, "url": url, "path": str(target.relative_to(ROOT)).replace("\\", "/"),
              "bytes": target.stat().st_size, "sha256": digest, "recorded_at_utc": datetime.now(timezone.utc).isoformat()}
    (HERE / f"{kind}-source.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2), flush=True)


if __name__ == "__main__":
    fetch(sys.argv[1])
