"""Check for flood events and issue Flood Event Reports (the backend also does this automatically).

Real data (same as the automatic watcher):
    .venv/Scripts/python.exe scripts/flood_event_check.py              # detect + issue due reports
    .venv/Scripts/python.exe scripts/flood_event_check.py --dry-run    # only show signals and events

Test events (separate from real events, reports carry the TEST banner):
    ... --test TRIMMU="High flood"                  # simulated signal; repeat --test for several stations
    ... --test TRIMMU="Very high flood:15000"      # optional discharge in cumecs
    ... --test-quiet --close-after-hours 0         # a cycle with no test signal (closes open test events)
    ... --list                                     # show stored events
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.init_db import init_db  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.flood_event import FloodEvent  # noqa: E402
from app.reports.event_report import generate_event_report  # noqa: E402
from app.reports.flood_events import LEVEL_NAMES, run_cycle, test_signal  # noqa: E402
from app.services.flood_event_watcher import collect_live_signals  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--frontend", default="http://127.0.0.1:3000")
    parser.add_argument("--dry-run", action="store_true", help="Show signals and due reports without changing anything")
    parser.add_argument("--test", action="append", default=[], metavar='STATION="Category[:cumecs]"')
    parser.add_argument("--test-quiet", action="store_true", help="Run a test cycle with no signals")
    parser.add_argument("--close-after-hours", type=int, default=24)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--no-satellite", action="store_true")
    parser.add_argument("--no-snapshots", action="store_true")
    parser.add_argument("--ai", action="store_true", help="Add AI analysis to test event reports (real events follow the settings)")
    parser.add_argument("--ai-review", choices=["portal", "label"], default=None)
    args = parser.parse_args()
    init_db()

    if args.list:
        with SessionLocal() as db:
            for e in db.query(FloodEvent).order_by(FloodEvent.id):
                print(f"{e.event_no:34} {e.status:6} {'TEST' if e.is_test else 'REAL':4} peak={LEVEL_NAMES[e.peak_level]:24} "
                      f"reported={LEVEL_NAMES[e.reported_level]:24} versions={len(e.versions or [])}")
        return

    is_test = bool(args.test or args.test_quiet)
    if is_test:
        signals = []
        for item in args.test:
            station, _, spec = item.partition("=")
            category, _, value = spec.partition(":")
            signals.append(test_signal(station.strip().upper(), category.strip(), float(value) if value else None))
    else:
        signals = collect_live_signals(args.api)
    print(f"{len(signals)} {'test' if is_test else 'real'} signal(s)")
    for s in signals:
        print(f"  [{s['kind']}] {s['river']}: {s['label']} at {s['station_name']}{' (stale)' if s.get('stale') else ''} - {s['detail']}")
    if args.dry_run:
        return

    def generate(event, reason):
        return generate_event_report(event, reason, api_base=args.api, frontend_url=args.frontend,
                                     ai_analysis=True if args.ai else None, ai_review=args.ai_review, progress=print,
                                     run_satellite=not args.no_satellite, capture_snapshots=not args.no_snapshots)

    results = run_cycle(SessionLocal, signals, is_test=is_test, generate=generate, close_after_hours=args.close_after_hours)
    if not results:
        print("No report due (no new event, no escalation above the reported level, no closure).")
    for r in results:
        print(f"{r['event_no']} {r['reason']} ({r['level']}): {r['path'] or 'FAILED ' + str(r['error'])}")


if __name__ == "__main__":
    main()
