"""Build monthly averages from FFD-reported 06:00 Marala inflow readings."""
import calendar
import hashlib
import io
import json
import math
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from html import unescape
from pathlib import Path

import httpx
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.ml.marala_pilot.collect import ARCHIVE, CUSEC_TO_CUMECS, parse_observation

ARTIFACTS = ROOT / "app/ml/marala_pilot/artifacts/seasonal"


def parse_current_bulletin(html, expected_date):
    """Read explicitly labelled measured cells, never the adjacent forecast."""
    text = " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())
    if "IN THOUSANDS OF CUSECS" not in text.upper() or "Actual Observations at 0600 PST" not in text:
        raise ValueError("Unrecognized observation units or time")
    dates = re.findall(r"Dated:\s*(\d{1,2})(?:st|nd|rd|th)?\s*([A-Za-z]+)[,\s-]+(\d{4})", text)
    parsed_dates = {datetime.strptime(f"{d} {m} {y}", "%d %B %Y").date() for d, m, y in dates}
    if parsed_dates != {expected_date}:
        raise ValueError("Bulletin date mismatch")
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", html, re.S | re.I):
        fields = dict(re.findall(r'<td\b[^>]*data-ffd="(station|inflow|outflow)"[^>]*>(.*?)</td>', row, re.S | re.I))
        clean = lambda value: unescape(re.sub(r"<[^>]+>", "", value)).strip()
        if clean(fields.get("station", "")) != "Marala":
            continue
        if not {"inflow", "outflow"}.issubset(fields):
            continue
        inflow, outflow = (float(clean(fields[key])) * 1000 for key in ("inflow", "outflow"))
        if not all(math.isfinite(value) and 0 <= value <= 2_000_000 for value in (inflow, outflow)):
            raise ValueError("Invalid measured flow")
        return {"station_id": "MARALA", "date": expected_date.isoformat(),
                "observed_at": f"{expected_date.isoformat()}T06:00:00+05:00",
                "inflow_cusecs": inflow, "outflow_cusecs": outflow,
                "inflow_cumecs": round(inflow * CUSEC_TO_CUMECS, 6),
                "outflow_cumecs": round(outflow * CUSEC_TO_CUMECS, 6),
                "measurement_kind": "FFD_reported_observation", "source_precision_cusecs": 100}
    # Early current-season pages embed the legacy table with a 1100 capacity
    # column before the actual inflow/outflow. Reuse its strict unit/date parser.
    return parse_observation(text, expected_date)


def monthly_gauge_averages(readings, start, end):
    by_day = {}
    for reading in readings:
        day = date.fromisoformat(reading["date"])
        if not start <= day <= end:
            continue
        if reading["station_id"] != "MARALA" or reading["measurement_kind"] != "FFD_reported_observation":
            raise ValueError("Only measured FFD Marala observations are accepted")
        value = float(reading["inflow_cumecs"])
        if not math.isfinite(value) or value < 0:
            raise ValueError("Invalid measured inflow")
        if day in by_day and float(by_day[day]["inflow_cumecs"]) != value:
            raise ValueError(f"Conflicting readings on {day}")
        by_day[day] = reading
    grouped = defaultdict(list)
    for day, reading in sorted(by_day.items()):
        grouped[day.strftime("%Y-%m")].append(reading)
    first = start.year * 12 + start.month - 1
    last = end.year * 12 + end.month - 1
    rows = []
    for index in range(first, last + 1):
        year, offset = divmod(index, 12)
        month = f"{year:04d}-{offset + 1:02d}"
        values = grouped[month]
        total_days = calendar.monthrange(year, offset + 1)[1]
        rows.append({
            "month": month, "days": len(values), "calendar_days": total_days,
            "flow_mean_cumecs": sum(float(row["inflow_cumecs"]) for row in values) / len(values) if values else None,
            "coverage": "complete" if len(values) == total_days else "partial" if values else "missing",
            "source_urls": [row["source_url"] for row in values],
        })
    return rows


def main():
    forecast = json.loads((ARTIFACTS / "current_provider_outlook.json").read_text(encoding="utf-8"))
    issue = date.fromisoformat(forecast["forecast_issue_start"])
    end = issue - timedelta(days=1)
    try:
        start = issue.replace(year=issue.year - 2)
    except ValueError:
        start = issue.replace(year=issue.year - 2, day=28)
    evidence = json.loads((ROOT / "app/ml/marala_pilot/data/ffd_observations.json").read_text(encoding="utf-8"))
    extra_path = ARTIFACTS / "gauge_history_observations.json"
    if extra_path.exists():
        evidence.extend(json.loads(extra_path.read_text(encoding="utf-8")))
    existing = {row["source_url"]: row for row in evidence}
    candidates, requests = {}, []
    with httpx.Client(timeout=45, follow_redirects=True) as client:
        for year in range(start.year, end.year + 1):
            page = 1
            while True:
                response = client.get(ARCHIVE, params={"year": year, "type": "bulletin", "page": page})
                response.raise_for_status()
                entries = re.findall(r'data-view-url="([^"]+)"[\s\S]{0,350}?data-title="Flood Bulletin ([^"]+)"', response.text)
                requests.append({"url": str(response.url), "entries": len(entries)})
                for url, title in entries:
                    day = datetime.strptime(title, "%d %b %Y").date()
                    if start <= day <= end:
                        candidates[url] = day
                pages = [int(number) for number in re.findall(r"[?&]page=(\d+)", unescape(response.text))]
                if not entries or not pages or page >= max(pages):
                    break
                page += 1
            print(f"Archive checked: {year}", flush=True)

        # Current-season bulletins are published separately from the old archive.
        page = 1
        while True:
            response = client.get("https://ffd.pmd.gov.pk/bulletin/bulletin", params={"page": page})
            response.raise_for_status()
            blocks = re.findall(r'<div class="hist-date">\s*<div class="day">(\d+)</div>\s*<div class="mon">([^<]+)</div>[\s\S]*?data-body-url="([^"]+)"', response.text)
            requests.append({"url": str(response.url), "entries": len(blocks)})
            if page == 1:
                # The latest bulletin is featured above the paginated history.
                featured = re.findall(r'href="(https://ffd\.pmd\.gov\.pk/b/[^"?#]+)"', response.text)
                for url in dict.fromkeys(featured):
                    official = client.get(url)
                    official.raise_for_status()
                    text = " ".join(unescape(re.sub(r"<[^>]+>", " ", official.text)).split())
                    match = re.search(r"Dated:\s*(\d{1,2})(?:st|nd|rd|th)?\s*([A-Za-z]+)[,\s-]+(\d{4})", text)
                    if match:
                        expected = datetime.strptime(" ".join(match.groups()), "%d %B %Y").date()
                        if start <= expected <= end:
                            candidates[url] = expected
            for day, month_year, url in blocks:
                expected = datetime.strptime(f"{day} {month_year}", "%d %b %Y").date()
                if start <= expected <= end:
                    candidates[url] = expected
            links = [int(number) for number in re.findall(r"[?&]page=(\d+)", unescape(response.text))]
            if not blocks or not links or page >= max(links):
                break
            page += 1
            if page > 50:
                raise ValueError("Current bulletin pagination exceeded expected limit")
        print(f"Current-season publication pages checked; {len(candidates)} dated sources", flush=True)

        def extract(item):
            url, day = item
            if url in existing:
                return existing[url]
            try:
                response = client.get(url)
                response.raise_for_status()
                if url.endswith("/body") or "/b/" in url:
                    row = parse_current_bulletin(response.text, day)
                else:
                    if not response.content.startswith(b"%PDF"):
                        raise ValueError("Source did not return a PDF")
                    text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(response.content)).pages)
                    row = parse_observation(text, day)
                row.update(source_url=url, source_sha256=hashlib.sha256(response.content).hexdigest())
                return row
            except Exception as exc:
                return {"source_url": url, "date": day.isoformat(), "error": str(exc)}

        results = list(ThreadPoolExecutor(max_workers=4).map(extract, sorted(candidates.items())))
    readings = [row for row in results if "error" not in row]
    rows = monthly_gauge_averages(readings, start, end)
    daily = sorted({row["date"]: row for row in readings}.values(), key=lambda row: row["date"])
    artifact = {
        "station_id": "MARALA", "river": "Chenab", "station_observation": True,
        "kind": "observed_gauge_inflow", "source": "Pakistan Meteorological Department / FFD flood bulletins",
        "documentation": ARCHIVE, "source_url": ARCHIVE,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "period_start": start.isoformat(), "period_end": end.isoformat(),
        "aggregation": "Arithmetic mean of available daily 06:00 PKT reported Marala inflow readings, converted from cusecs to m3/s; one reading per day",
        "limitations": "Partial-month means average available readings only, not a complete monthly mean or a continuous daily mean. Missing months are null; no model values or interpolation are used.",
        "monthly_records": sum(row["flow_mean_cumecs"] is not None for row in rows),
        "monthly_slots": len(rows), "monthly": rows,
        "daily_records": len(daily), "daily": daily,
        "archive_requests": requests,
        "rejected_documents": [row for row in results if "error" in row],
    }
    existing.update({row["source_url"]: row for row in readings})
    extra_path.write_text(json.dumps(sorted(existing.values(), key=lambda row: row["date"]), indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (ARTIFACTS / "observed_monthly_history.json").write_text(json.dumps(artifact, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Saved {len(readings)} FFD readings across {artifact['monthly_records']} measured monthly averages; remaining months missing", flush=True)
    print([(row["month"], row["days"], row["calendar_days"]) for row in rows if row["days"]])


if __name__ == "__main__":
    main()
