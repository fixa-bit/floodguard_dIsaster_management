"""Runs a flood-event detection cycle after each river-monitoring or upstream-forecast refresh.

The watcher checks the stored snapshots once a minute. When either snapshot has a new
`cached_at`, it collects real signals and lets app/reports/flood_events.py decide whether
a report is due (new event, escalation, closure). Report generation runs in a worker
thread, so the API keeps serving (the generator reads the API over HTTP).
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.upstream_forecast_snapshot import UpstreamForecastSnapshot
from app.reports.flood_events import detect_signals, run_cycle

logger = logging.getLogger(__name__)
SNAPSHOT_IDS = (1, 3)  # 1 = upstream forecasts, 3 = river monitoring (see their cache services)


def collect_live_signals(api_base: str) -> list[dict]:
    """Fetch the portal's current data over HTTP and return qualifying real signals."""
    from app.locations import LOCATIONS

    with httpx.Client(base_url=api_base.rstrip("/"), timeout=120) as client:
        def get(path, **params):
            try:
                response = client.get(path, params=params or None)
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                logger.warning("Flood event check could not read %s: %s", path, exc)
                return None
        system = get("/system/status")
        monitoring = get("/river/monitoring")
        upstream = get("/river/upstream-forecasts")
        model_points = get("/flood/model-forecasts")
        risks = [r | {"location_id": location_id} for location_id in LOCATIONS
                 if (r := get("/flood/risk", location_id=location_id))]
    if monitoring is None and upstream is None:
        raise RuntimeError("River monitoring and upstream forecasts are both unavailable")
    return detect_signals(monitoring, upstream, risks, model_points, system)


def run_live_cycle(dry_run: bool = False) -> list[dict]:
    from app.reports.event_report import generate_event_report

    settings = get_settings()
    signals = collect_live_signals(settings.report_api_base)

    def generate(event, reason):
        return generate_event_report(event, reason, api_base=settings.report_api_base, frontend_url=settings.report_frontend_url,
                                     run_satellite=settings.report_run_satellite, capture_snapshots=settings.report_capture_snapshots)

    results = run_cycle(SessionLocal, signals, is_test=False, generate=generate,
                        close_after_hours=settings.flood_event_close_after_hours, dry_run=dry_run)
    for item in results:
        logger.info("Flood event report %s %s (%s): %s", item["event_no"], item["reason"], item["level"], item["path"] or item["error"])
    return results


class FloodEventWatcher:
    def __init__(self, check_seconds: int = 60):
        self.check_seconds = check_seconds
        self.task: asyncio.Task | None = None
        self.last_stamps: tuple | None = None

    @staticmethod
    def _stamps() -> tuple:
        with SessionLocal() as db:
            return tuple((row.cached_at.isoformat() if row and row.cached_at else None)
                         for row in (db.get(UpstreamForecastSnapshot, i) for i in SNAPSHOT_IDS))

    async def _worker(self):
        await asyncio.sleep(30)  # let the caches fill after startup
        while True:
            try:
                stamps = await asyncio.to_thread(self._stamps)
                if any(stamps) and stamps != self.last_stamps:
                    self.last_stamps = stamps
                    await asyncio.to_thread(run_live_cycle)
            except Exception:
                logger.exception("Flood event check failed")
            await asyncio.sleep(self.check_seconds)

    def start(self):
        if get_settings().flood_event_reports_enabled and (self.task is None or self.task.done()):
            self.task = asyncio.create_task(self._worker())

    async def stop(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None


flood_event_watcher = FloodEventWatcher()
