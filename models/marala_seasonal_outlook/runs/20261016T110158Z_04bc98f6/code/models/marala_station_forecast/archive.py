"""Immutable run snapshots and retained official-source evidence."""
import hashlib
import json
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

from .core import HERE, PROJECT, load_observations, sha256, write_csv, write_json


def begin_run(sources, output):
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    folder = Path(output).parent / "runs" / run_id
    folder.mkdir(parents=True, exist_ok=False)
    frozen = []
    for index, source in enumerate(map(Path, sources), 1):
        target = folder / "data/sources" / f"{index:02d}_{source.name}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        frozen.append(target)
    code = folder / "code/models/marala_station_forecast"
    code.mkdir(parents=True, exist_ok=True)
    for source in list(HERE.glob("*.py")) + [HERE / "config.json", HERE / "README.md"]:
        shutil.copy2(source, code / source.name)
    (folder / "code/requirements.txt").write_text("numpy==2.1.3\nxgboost==2.1.3\nhttpx==0.28.1\npypdf>=6,<7\n", encoding="utf-8")
    return folder, frozen


def retain_bulletins(history, folder, workers=4):
    """Retain the bytes retrieved now; never disguise an old hash mismatch."""
    import io
    import httpx
    from pypdf import PdfReader
    from app.ml.marala_pilot.collect import parse_observation
    from scripts.collect_marala_gauge_history import parse_current_bulletin

    evidence = Path(folder) / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    cache = HERE / "evidence_cache"
    cache.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=45, follow_redirects=True) as client:
        def fetch(row):
            result = {"date": row["date"], "source_url": row["source_url"],
                      "expected_source_sha256": row["source_sha256"], "retrieved_sha256": "",
                      "local_file": "", "original_bytes_match": False, "values_match": False, "error": ""}
            try:
                cached = next((cache / (row["source_sha256"] + suffix) for suffix in (".pdf", ".html") if (cache / (row["source_sha256"] + suffix)).exists()), None)
                if cached:
                    content = cached.read_bytes()
                else:
                    response = client.get(row["source_url"])
                    response.raise_for_status()
                    content = response.content
                digest = hashlib.sha256(content).hexdigest()
                suffix = ".pdf" if content.startswith(b"%PDF") else ".html"
                stored = cache / (digest + suffix)
                if not stored.exists():
                    stored.write_bytes(content)
                retained = evidence / stored.name
                shutil.copy2(stored, retained)
                result.update(retrieved_sha256=digest, local_file=str(retained.relative_to(folder)).replace("\\", "/"), original_bytes_match=digest == row["source_sha256"])
                day = date.fromisoformat(row["date"])
                if suffix == ".pdf":
                    text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)
                    parsed = parse_observation(text, day)
                else:
                    parsed = parse_current_bulletin(content.decode("utf-8"), day)
                result["values_match"] = all(abs(float(parsed[key]) - float(row[key])) < 1e-5 for key in ("inflow_cumecs", "outflow_cumecs"))
                if not result["values_match"]:
                    result["error"] = "Retrieved source disagrees with retained training measurement"
            except Exception as exc:
                result["error"] = str(exc)
            return result
        rows = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(fetch, row) for row in history.values()]
            for future in as_completed(futures):
                rows.append(future.result())
                if len(rows) % 40 == 0:
                    print(f"Retained bulletin audit: {len(rows)}/{len(history)}", flush=True)
    rows.sort(key=lambda row: row["date"])
    write_csv(evidence / "index.csv", rows)
    summary = {"observations": len(rows), "documents_retained": sum(bool(row["local_file"]) for row in rows),
               "original_byte_hash_matches": sum(row["original_bytes_match"] for row in rows),
               "extracted_values_match": sum(row["values_match"] for row in rows),
               "errors": sum(bool(row["error"]) for row in rows),
               "note": "The training snapshot is preserved unchanged. HTML bytes may change; hash mismatches are disclosed rather than replacing the original evidence hash."}
    write_json(evidence / "summary.json", summary)
    return summary


def seal_run(folder, data, artifacts):
    folder, data, artifacts = map(Path, (folder, data, artifacts))
    if (folder / "RUN_MANIFEST.json").exists():
        raise ValueError("A sealed run cannot be overwritten")
    if data.resolve() != (folder / "data").resolve():
        shutil.copytree(data, folder / "data", dirs_exist_ok=True)
    if artifacts.resolve() != (folder / "artifacts").resolve():
        shutil.copytree(artifacts, folder / "artifacts", dirs_exist_ok=True)
    inventory = {str(path.relative_to(folder)).replace("\\", "/"): {"sha256": sha256(path), "bytes": path.stat().st_size}
                 for path in sorted(folder.rglob("*")) if path.is_file() and path.name != "RUN_MANIFEST.json"}
    write_json(folder / "RUN_MANIFEST.json", {"run_id": folder.name, "sealed_at": datetime.now(timezone.utc).isoformat(),
               "policy": "Do not edit this run. New data or experiments create a new run directory.", "files": inventory})
    write_json(folder.parent.parent / "LATEST_RUN.json", {"run_id": folder.name, "path": str(folder.relative_to(folder.parent.parent)).replace("\\", "/"),
               "manifest_sha256": sha256(folder / "RUN_MANIFEST.json")})


def archive_existing(download_evidence=True):
    manifest = json.loads((HERE / "data/manifest.json").read_text(encoding="utf-8"))
    sources = [Path(row["path"]) for row in manifest["sources"]]
    if any(sha256(source) != row["sha256"] for source, row in zip(sources, manifest["sources"], strict=True)):
        raise ValueError("Original source inputs changed; cannot claim exact-source archive")
    folder, _ = begin_run(sources, HERE / "artifacts")
    history, _ = load_observations([HERE / "data/observations.csv"])
    if download_evidence:
        print(retain_bulletins(history, folder), flush=True)
    seal_run(folder, HERE / "data", HERE / "artifacts")
    print(f"Sealed immutable run: {folder}", flush=True)
    return folder


if __name__ == "__main__":
    archive_existing()
