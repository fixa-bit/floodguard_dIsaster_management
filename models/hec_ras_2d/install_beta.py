"""Install the official self-contained HEC-RAS 2025 Beta in the workspace."""
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
ARCHIVE = ROOT / "tools/hec_ras/downloads/HEC-RAS_2025_Beta.zip"
TARGET = ROOT / "tools/hec_ras/2025-beta"


def install():
    source = json.loads((HERE / "beta-source.json").read_text(encoding="utf-8"))
    with ARCHIVE.open("rb") as handle:
        if hashlib.file_digest(handle, "sha256").hexdigest() != source["sha256"]:
            raise ValueError("Downloaded HEC-RAS archive hash changed")
    target = TARGET.resolve()
    with zipfile.ZipFile(ARCHIVE) as package:
        for item in package.infolist():
            path = (target / item.filename).resolve()
            if not path.is_relative_to(target):
                raise ValueError("Unsafe archive path")
        package.extractall(target)
    engine = target / "HEC-RAS 2025 Beta/ras.exe"
    if not engine.is_file():
        raise ValueError("The portable HEC-RAS executable was not extracted")
    with engine.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    result = {"official_source": source, "engine_relative_path": str(engine.relative_to(ROOT)).replace("\\", "/"),
              "engine_sha256": digest, "installed_at_utc": datetime.now(timezone.utc).isoformat(),
              "version": "HEC-RAS 2025 Beta", "mode": "portable local extraction; no administrator rights or system install"}
    (HERE / "installation.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    install()
