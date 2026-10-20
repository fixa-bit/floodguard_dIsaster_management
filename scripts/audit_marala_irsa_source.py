"""Probe monthly dated IRSA reports without changing gauge history or trained runs."""
import argparse
import csv
import hashlib
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from html import unescape
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
URL = "https://irsa.nespak.co/Home/DailyData"
CUSEC_TO_CUMECS = 0.028316846592


def clean(value):
    return " ".join(unescape(re.sub(r"<[^>]*>", " ", value)).split())


def parse_report(html, expected_date):
    actual = re.search(r'data-reading-date="(\d{4}-\d{2}-\d{2})"', html)
    if not actual or actual[1] != expected_date:
        raise ValueError("Response report date does not match request")
    card = re.search(r'<h3\b[^>]*>\s*MARALA\s*</h3>(.*?)(?=<h3\b|<footer\b|\Z)', html, re.S | re.I)
    if not card:
        return None
    values = {}
    for label, key in (("U/S DISCHARGE", "inflow_cusecs"), ("D/S DISCHARGE", "outflow_cusecs")):
        match = re.search(r'<span>\s*' + re.escape(label) + r'\s*</span>\s*<strong>(.*?)</strong>', card[1], re.S | re.I)
        if not match or not re.fullmatch(r"[\d,]+(?:\.\d+)? Cs", clean(match[1])):
            raise ValueError("Unrecognized reported Marala discharge value or units")
        values[key] = float(clean(match[1]).removesuffix(" Cs").replace(",", ""))
    return {"date": expected_date, **values,
            "inflow_cumecs": values["inflow_cusecs"] * CUSEC_TO_CUMECS,
            "outflow_cumecs": values["outflow_cusecs"] * CUSEC_TO_CUMECS,
            "measurement_kind": "IRSA_reported_discharge_time_basis_unconfirmed",
            "observed_at": None,
            "time_basis": "Report date verified; exact observation time and daily-mean definition not specified for the Marala card"}


def sample_dates(start, end):
    days = {start, end}
    for index in range(start.year * 12 + start.month - 1, end.year * 12 + end.month):
        year, month = divmod(index, 12)
        day = date(year, month + 1, 15)
        if start <= day <= end:
            days.add(day)
    return sorted(days)


def audit(start=date(2024, 10, 16), end=date(2026, 10, 15)):
    folder = ROOT / "models/source_audits" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_irsa_marala")
    (folder / "responses").mkdir(parents=True, exist_ok=False)
    (folder / "audit_script.py").write_bytes(Path(__file__).read_bytes())
    local = threading.local()
    clients = []

    def fetch(day):
        row = {"date": day.isoformat(), "status": "error", "inflow_cusecs": "", "outflow_cusecs": "", "response_file": "", "sha256": "", "error": ""}
        try:
            if not hasattr(local, "client"):
                local.client = httpx.Client(timeout=30, follow_redirects=True)
                clients.append(local.client)
                page = local.client.get(URL)
                page.raise_for_status()
                token = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', page.text)
                if not token:
                    raise ValueError("Report query form has no verification token")
                local.token = unescape(token[1])
            response = local.client.post(URL, data={"ReadingDateString": day.strftime("%Y%m%d"), "__RequestVerificationToken": local.token})
            response.raise_for_status()
            path = folder / "responses" / f"{day}.html"
            path.write_bytes(response.content)
            row.update(response_file=str(path.relative_to(folder)).replace("\\", "/"), sha256=hashlib.sha256(response.content).hexdigest())
            reading = parse_report(response.text, day.isoformat())
            row["status"] = "verified_reported_value" if reading else "no_marala_card"
            if reading:
                row.update(inflow_cusecs=reading["inflow_cusecs"], outflow_cusecs=reading["outflow_cusecs"])
            return row, reading
        except Exception as exc:
            row["error"] = str(exc)
            return row, None

    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(fetch, sample_dates(start, end)))
    finally:
        for client in clients:
            client.close()
    with (folder / "availability.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0][0]))
        writer.writeheader()
        writer.writerows(row for row, _ in results)
    readings = [reading for _, reading in results if reading]
    (folder / "reported_values.json").write_text(json.dumps(readings, indent=2) + "\n", encoding="utf-8")
    summary = {"source_url": URL, "retrieved_at": datetime.now(timezone.utc).isoformat(),
               "request_method": "POST date-selection form, ReadingDateString=YYYYMMDD; cookies and verification token are session-only",
               "sampling": "15th of each month plus window endpoints; not a complete daily coverage audit",
               "window_start": start.isoformat(), "window_end": end.isoformat(),
               "sampled_reports": len(results), "reports_with_values": len(readings),
               "no_marala_card": sum(row["status"] == "no_marala_card" for row, _ in results),
               "errors": sum(row["status"] == "error" for row, _ in results),
               "time_basis": "Unconfirmed: do not label these values 06:00 observations or daily means",
               "training_or_dashboard_changed": False,
               "cross_source_values_reconciled": False}
    (folder / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    files = {str(path.relative_to(folder)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(folder.rglob("*")) if path.is_file()}
    (folder / "FILE_HASHES.json").write_text(json.dumps(files, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"folder": str(folder), **summary}, indent=2))
    return folder


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2024, 10, 16))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 10, 15))
    args = parser.parse_args()
    audit(args.start, args.end)
