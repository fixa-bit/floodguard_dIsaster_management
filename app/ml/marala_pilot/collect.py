"""Download FFD measurements and ERA5-Land context; never synthesize missing values."""
import argparse
import csv
import hashlib
import io
import json
import re
from html import unescape
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
ARCHIVE = "https://ffd.pmd.gov.pk/bulletins/archive"
WEATHER = "https://archive-api.open-meteo.com/v1/archive"
CUSEC_TO_CUMECS = 0.028316846592


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"No rows for {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def parse_observation(text, expected_date):
    """Restrict extraction to the explicitly labelled observation table and row."""
    compact = " ".join(text.split())
    if not re.search(r"IN THOUSANDS OF CUSECS", compact, re.I):
        raise ValueError("Unrecognized discharge units")
    if not re.search(r"Actual Observations at 0600 PST", compact, re.I):
        raise ValueError("Unrecognized observation time")
    dates = re.findall(r"Dated:\s*(\d{1,2})(?:st|nd|rd|th)?\s*([A-Za-z]+)[,\s-]+(\d{4})", compact)
    parsed_dates = {datetime.strptime(f"{d} {m} {y}", "%d %B %Y").date() for d, m, y in dates}
    if parsed_dates != {expected_date}:
        raise ValueError(f"Bulletin date mismatch: {parsed_dates} != {expected_date}")
    table = compact.split("QUANTITATIVE FLOOD FORECAST", 1)[-1]
    match = re.search(r"\bMarala\s+1100(?:\.0)?\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\b", table, re.I)
    if not match:
        raise ValueError("Missing/unrecognized Marala observation row")
    inflow, outflow = (float(value) * 1000 for value in match.groups())
    if not 0 <= inflow <= 2_000_000 or not 0 <= outflow <= 2_000_000:
        raise ValueError("Implausible discharge or unit error")
    return {
        "station_id": "MARALA", "date": expected_date.isoformat(),
        "observed_at": f"{expected_date.isoformat()}T06:00:00+05:00",
        "inflow_cusecs": inflow, "outflow_cusecs": outflow,
        "inflow_cumecs": round(inflow * CUSEC_TO_CUMECS, 6),
        "outflow_cumecs": round(outflow * CUSEC_TO_CUMECS, 6),
        "measurement_kind": "FFD_reported_observation",
        "source_precision_cusecs": 100,
    }


def collect(output=ROOT / "data", workers=4):
    from pypdf import PdfReader

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    config = json.loads((ROOT / "config.json").read_text())
    evidence_path = output / "ffd_observations.json"
    # Cache successfully extracted measurements, not entire copyrighted publications.
    evidence = json.loads(evidence_path.read_text()) if evidence_path.exists() else []
    existing = {row["source_url"]: row for row in evidence}
    failures, requests, candidates = [], [], {}
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        def get(url, **kwargs):
            last = None
            for _ in range(3):
                try:
                    response = client.get(url, **kwargs)
                    response.raise_for_status()
                    return response
                except httpx.HTTPError as exc:
                    last = exc
            raise RuntimeError(f"Download failed: {url}") from last

        for year in config["seasons"]:
            page = 1
            while True:
                response = get(ARCHIVE, params={"year": year, "type": "bulletin", "page": page})
                entries = re.findall(r'data-view-url="([^"]+)"[\s\S]{0,350}?data-title="Flood Bulletin ([^"]+)"', response.text)
                if not entries:
                    break
                for url, title_date in entries:
                    day = datetime.strptime(title_date, "%d %b %Y").date()
                    if day.year == year and config["start_month_day"] <= day.strftime("%m-%d") <= config["end_month_day"]:
                        candidates[url] = day
                pages = [int(number) for number in re.findall(r"[?&]page=(\d+)", unescape(response.text))]
                if not pages or page >= max(pages):
                    break
                page += 1

        def extract(item):
            url, day = item
            if url in existing:
                return existing[url]
            try:
                response = get(url)
                if not response.content.startswith(b"%PDF"):
                    raise ValueError("Archive did not return a PDF")
                text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(response.content)).pages)
                row = parse_observation(text, day)
                row.update(source_url=url, source_sha256=hashlib.sha256(response.content).hexdigest())
                return row
            except Exception as exc:
                return {"source_url": url, "date": day.isoformat(), "error": str(exc)}

        results = list(ThreadPoolExecutor(max_workers=workers).map(extract, sorted(candidates.items())))
        observations = []
        for row in results:
            if "error" in row:
                failures.append(row)
            else:
                observations.append(row)
        observations.sort(key=lambda row: row["date"])
        by_date = {}
        for row in observations:
            if row["date"] in by_date and row["inflow_cusecs"] != by_date[row["date"]]["inflow_cusecs"]:
                raise ValueError(f"Conflicting FFD readings: {row['date']}")
            by_date[row["date"]] = row
        observations = list(by_date.values())
        evidence_path.write_text(json.dumps(observations, indent=2) + "\n", encoding="utf-8")
        write_csv(output / "observations.csv", observations)
        print(f"FFD: {len(observations)} measured daily readings; {len(failures)} rejected documents", flush=True)

        weather_rows = []
        for year in config["seasons"]:
            for point in config["weather_points"]:
                params = {
                    "latitude": point["latitude"], "longitude": point["longitude"],
                    "start_date": f"{year}-{config['start_month_day']}",
                    "end_date": f"{year}-{config['end_month_day']}",
                    "hourly": "precipitation,temperature_2m,soil_moisture_0_to_7cm,snow_depth",
                    "models": config["weather_model"], "timezone": "UTC",
                }
                response = get(WEATHER, params=params)
                payload = response.json()
                requests.append({"url": str(response.url), "sha256": hashlib.sha256(response.content).hexdigest(),
                                 "grid_latitude": payload["latitude"], "grid_longitude": payload["longitude"]})
                hourly = payload["hourly"]
                for offset in range(0, len(hourly["time"]), 24):
                    def aggregate(field, operation):
                        values = hourly[field][offset:offset + 24]
                        return operation(values) if len(values) == 24 and all(value is not None for value in values) else ""
                    weather_rows.append({
                        "date": hourly["time"][offset][:10], "point": point["name"],
                        "rainfall_mm": aggregate("precipitation", sum),
                        "temperature_c": aggregate("temperature_2m", lambda values: sum(values) / 24),
                        "soil_moisture_m3_m3": aggregate("soil_moisture_0_to_7cm", lambda values: sum(values) / 24),
                        "snow_depth_m": aggregate("snow_depth", lambda values: sum(values) / 24),
                        "source_kind": "ERA5_Land_reanalysis",
                    })
                print(f"Weather: {year} / {point['name']}", flush=True)
        write_csv(output / "weather_daily.csv", weather_rows)
        manifest = {
            "retrieved_at": datetime.now(timezone.utc).isoformat(), "station_id": config["station_id"],
            "archive": ARCHIVE, "weather_documentation": "https://open-meteo.com/en/docs/historical-weather-api",
            "observations": len(observations), "weather_rows": len(weather_rows),
            "weather_requests": requests, "rejected_documents": failures,
            "data_policy": "Measured FFD inflow/outflow; weather is modeled reanalysis; no simulated rows or filled gauge gaps.",
            "weather_license": "Open-Meteo data CC BY 4.0; ERA5-Land / Copernicus attribution required.",
        }
        (output / "sources.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data")
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=4)
    args = parser.parse_args()
    print(json.dumps(collect(args.output, args.workers), indent=2))
