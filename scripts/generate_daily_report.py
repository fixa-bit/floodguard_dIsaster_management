"""Generate the Daily Flood Situation Report from the running FloodGuard portal.

Usage:
    .venv/Scripts/python.exe scripts/generate_daily_report.py [--no-satellite] [--no-test-flood] [--no-snapshots]
        [--no-ai] [--ai-review portal|label] [--trigger manual|scheduled]

Writes reports/daily/<YYYY-MM-DD_HHMMSS>/DFSR-<year>-<day>.html plus report.json (the data snapshot).
The deterministic report is written first; the AI analysis of flagged values (if on) is added after it.
--trigger scheduled behaves like the automatic 06:30 run (AI notes published without human review).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.reports.daily_report import generate  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--frontend", default="http://127.0.0.1:3000")
    parser.add_argument("--no-satellite", action="store_true", help="Skip Sentinel-1 checks (they take about 1 minute each)")
    parser.add_argument("--no-test-flood", action="store_true", help="Skip the simulated flood on real imagery test")
    parser.add_argument("--test-flood-region", default="trimmu_jhang")
    parser.add_argument("--no-snapshots", action="store_true")
    parser.add_argument("--no-ai", action="store_true", help="Skip the AI analysis of flagged values")
    parser.add_argument("--ai-review", choices=["portal", "label"], default=None, help="Review mode for AI notes (manual runs)")
    parser.add_argument("--trigger", choices=["manual", "scheduled"], default="manual")
    args = parser.parse_args()
    path = generate(args.api, run_satellite=not args.no_satellite,
                    test_flood_region=None if args.no_test_flood else args.test_flood_region,
                    capture_snapshots=not args.no_snapshots, frontend_url=args.frontend, trigger=args.trigger,
                    ai_analysis=False if args.no_ai else None, ai_review=args.ai_review, progress=print)
    print(path)


if __name__ == "__main__":
    main()
