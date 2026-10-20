"""Install the official portable TUFLOW release locally, preserving provenance."""
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
VERSION = "2026.3.0"
ARCHIVE_URL = "https://downloads.tuflow.com/TUFLOW/Releases/2026/tuflow-2026.3-2026.3.0-1.zip"
EULA_URL = "https://downloads.tuflow.com/Licensing/TUFLOW%20Products%20Licence%20Agreement.pdf"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def install():
    target = ROOT / "tools/tuflow" / VERSION
    downloads = ROOT / "tools/tuflow/downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    archive = downloads / ARCHIVE_URL.rsplit("/", 1)[-1]
    eula = downloads / "TUFLOW_Products_Licence_Agreement.pdf"
    with httpx.Client(timeout=90, follow_redirects=True) as client:
        if not eula.exists():
            response = client.get(EULA_URL)
            response.raise_for_status()
            if not response.content.startswith(b"%PDF"):
                raise ValueError("Official EULA did not return a PDF")
            eula.write_bytes(response.content)
        if not archive.exists():
            partial = archive.with_suffix(".partial")
            with client.stream("GET", ARCHIVE_URL) as response:
                response.raise_for_status()
                downloaded, previous = 0, 0
                with partial.open("wb") as handle:
                    for chunk in response.iter_bytes(1024 * 1024):
                        handle.write(chunk)
                        downloaded += len(chunk)
                        if downloaded - previous >= 10 * 1024 * 1024:
                            print(f"Official TUFLOW download: {downloaded/1048576:.0f} MiB", flush=True)
                            previous = downloaded
            partial.replace(archive)
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as package:
        for item in package.infolist():
            output = (target / item.filename).resolve()
            if not output.is_relative_to(target.resolve()):
                raise ValueError("Archive contains an unsafe extraction path")
        package.extractall(target)
    binaries = sorted(target.rglob("*.exe"))
    engine = next((path for path in binaries if path.name.lower() == "tuflow_isp_w64.exe"), None)
    if engine is None:
        engine = next((path for path in binaries if path.name.lower() == "tuflow.exe"), None)
    if engine is None:
        engine = next((path for path in binaries if "tuflow" in path.name.lower() and ("isp" in path.name.lower() or "w64" in path.name.lower())), None)
    if engine is None:
        raise ValueError(f"Cannot identify the TUFLOW engine: {[p.name for p in binaries]}")
    manifest = {"version": VERSION, "installed_at": datetime.now(timezone.utc).isoformat(),
                "official_download_page": "https://tuflow.com/downloads/", "archive_url": ARCHIVE_URL,
                "archive_sha256": sha256(archive), "archive_bytes": archive.stat().st_size,
                "engine_relative_path": str(engine.relative_to(ROOT)).replace("\\", "/"), "engine_sha256": sha256(engine),
                "eula_url": EULA_URL, "eula_sha256": sha256(eula),
                "installation": "Official portable package; installed under the workspace, no global PATH or backend environment changes",
                "licence": "No licence purchased or activated by this installer; demo and licensed mode are separate engine capabilities"}
    (HERE / "installation.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)
    return engine


if __name__ == "__main__":
    install()
