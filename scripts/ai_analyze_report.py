"""Run (or re-run) the AI analysis of flagged values on an existing report folder.

The deterministic report (report.json) is not changed; only its "ai_analysis" block and the page
are rewritten. Useful after adding documents to knowledge/ or after setting the API key.

Usage:
    .venv/Scripts/python.exe scripts/ai_analyze_report.py reports/daily/2026-11-11_142134
        [--trigger manual|scheduled|watcher|test] [--review portal|label|none] [--include-simulated]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.reports.ai.runner import review_mode_for, run_ai_analysis  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--trigger", choices=["manual", "scheduled", "watcher", "test"], default=None)
    parser.add_argument("--review", choices=["portal", "label", "none"], default=None)
    parser.add_argument("--include-simulated", action="store_true", help="Also analyse simulated (test) flags")
    args = parser.parse_args()
    folder = args.folder.resolve()
    data = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    trigger = args.trigger or (data.get("ai_analysis") or {}).get("trigger") or data.get("meta", {}).get("trigger") or "manual"
    review = args.review or (data.get("ai_analysis") or {}).get("review_mode") or review_mode_for(trigger, None)
    include_simulated = args.include_simulated or bool(data.get("meta", {}).get("is_test"))
    ai = run_ai_analysis(folder, trigger=trigger, review_mode=review, include_simulated=include_simulated, progress=print)
    print(json.dumps({k: ai.get(k) for k in ("status", "reason", "note", "review_mode", "seconds", "integrity")}, indent=1))
    for flag_id, entry in (ai.get("flags") or {}).items():
        e, a = entry.get("explanation") or {}, entry.get("agent") or {}
        print(f"{flag_id}: explanation {e.get('status', '-')}, {len(e.get('sources') or [])} sources; "
              f"agent {a.get('status', '-')}, {len(a.get('evidence') or [])} evidence, {a.get('tool_calls', 0)} tool calls")


if __name__ == "__main__":
    main()
