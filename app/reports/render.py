"""Shared HTML rendering for FloodGuard reports.

A report page = shared styles (_base.html) + the report's JSON payload + shared
helpers (_helpers.js) + the report's own body script + tooltips (_tip.js).
The daily report and the flood event report differ only in their body script.
"""

from __future__ import annotations

import json
from pathlib import Path

TEMPLATES = Path(__file__).with_name("templates")


def render_page(body_script: str, data: dict, title: str) -> str:
    part = lambda name: (TEMPLATES / name).read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False, default=str).replace("</", "<\\/")
    page = (part("_base.html").replace("__REPORT_TITLE__", title)
            + '\n<div class="report" id="report"></div>\n<div id="tip" hidden></div>\n'
            + f'<script id="report-data" type="application/json">{payload}</script>\n<script>\n'
            + part("_helpers.js") + part(body_script) + "\n" + part("_tip.js") + "</script>\n")
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
            '<style>body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style></head><body>\n'
            + page + "\n</body></html>")


def write_atomic(path: Path, text: str) -> None:
    """Write via a temporary file so readers never see a half-written report."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def render_folder(folder: Path) -> Path:
    """Re-render a saved report from its report.json, adding reviewer decisions from review.json if present."""
    data = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    review_path = folder / "review.json"
    if review_path.exists():
        data["review"] = json.loads(review_path.read_text(encoding="utf-8"))
    script = "flood_event_report.js" if "event" in data else "daily_report.js"
    path = folder / f"{data['meta']['report_no']}.html"
    write_atomic(path, render_page(script, data, data["meta"]["report_no"]))
    return path
