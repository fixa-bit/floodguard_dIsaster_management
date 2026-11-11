"""Generated-report archive and on-demand generation for the portal's Reports screen.

Reports live on disk under reports/ (daily: reports/daily/<folder>/, flood events:
reports/events/[test/]<event no>/v<n>/), each folder holding the HTML page and report.json.
Generation runs one job at a time in a background thread; the UI polls the job.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.gis.river_stations import RIVER_CHAINS
from app.models.flood_event import FloodEvent
from app.reports.collector import EXPOSURE_REGIONS, PKT, ROOT, STATION_NAMES
from app.reports.ai.review import ai_summary, load_review
from app.reports.flood_events import LEVEL_NAMES, LEVELS, STATION_RIVER, run_cycle, test_signal

logger = logging.getLogger(__name__)
REPORTS_ROOT = ROOT / "reports"

# Ready-made test cases for the flood event report. Each is a list of simulated station readings.
SCENARIOS = [
    {"id": "chenab_high", "name": "Chenab: High flood at Trimmu",
     "description": "One station in High flood. Population impact is available (Trimmu/Jhang).",
     "signals": [{"station_id": "TRIMMU", "category": "High flood", "discharge": 9500}]},
    {"id": "chenab_escalation", "name": "Chenab: Very high flood, wave reaching Panjnad",
     "description": "Very high at Trimmu and Medium at Panjnad. Run after the High-flood case with 'Continue open test event' to see an escalation report.",
     "signals": [{"station_id": "TRIMMU", "category": "Very high flood", "discharge": 14000},
                 {"station_id": "PANJNAD", "category": "Medium flood", "discharge": 6200}]},
    {"id": "ravi_medium", "name": "Ravi: Medium flood at Balloki",
     "description": "Population impact is available (Balloki region).",
     "signals": [{"station_id": "BALLOKI", "category": "Medium flood", "discharge": 3400}]},
    {"id": "ravi_upper", "name": "Ravi: Low flood at Shahdara and Balloki",
     "description": "Two stations in Low flood on the Lahore reach.",
     "signals": [{"station_id": "SHAHDARA", "category": "Low flood", "discharge": 1800},
                 {"station_id": "BALLOKI", "category": "Low flood", "discharge": 2100}]},
    {"id": "indus_taunsa", "name": "Indus: High flood at Taunsa",
     "description": "No population dataset here, so the report shows impact as unavailable.",
     "signals": [{"station_id": "TAUNSA", "category": "High flood", "discharge": 16000}]},
    {"id": "sutlej_islam", "name": "Sutlej: Medium flood at Islam",
     "description": "Sutlej event; Panjnad joins the Sutlej event when only the Sutlej floods.",
     "signals": [{"station_id": "ISLAM", "category": "Medium flood", "discharge": 3000}]},
    {"id": "jhelum_exceptional", "name": "Jhelum: Exceptionally high flood at Mangla and Rasul",
     "description": "Highest category on a short river chain.",
     "signals": [{"station_id": "MANGLA", "category": "Exceptionally high flood", "discharge": 25000},
                 {"station_id": "RASUL", "category": "Very high flood", "discharge": 19000}]},
]

_jobs: dict[str, dict] = {}
_job_lock = threading.Lock()
_running: str | None = None


# ------------------------------------------------------------------ archive
def _safe_folder(report_id: str) -> Path:
    folder = (REPORTS_ROOT / report_id).resolve()
    if not folder.is_relative_to(REPORTS_ROOT.resolve()) or folder == REPORTS_ROOT.resolve() or not folder.is_dir():
        raise FileNotFoundError(report_id)
    return folder


def _html_in(folder: Path) -> Path | None:
    return next(iter(sorted(folder.glob("*.html"))), None)


def _summary(folder: Path) -> dict | None:
    html = _html_in(folder)
    data_file = folder / "report.json"
    if not html:
        return None
    rel = folder.relative_to(REPORTS_ROOT).as_posix()
    item = {"id": rel, "kind": "daily" if rel.startswith("daily/") else "event", "file_name": html.name,
            "size_bytes": html.stat().st_size, "created_at": datetime.fromtimestamp(html.stat().st_mtime, timezone.utc).isoformat(),
            "is_test": "/test/" in f"/{rel}/", "title": html.stem, "has_simulated": None, "headline": None}
    try:
        data = json.loads(data_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return item
    meta, summary = data.get("meta", {}), data.get("summary", {})
    item.update(title=meta.get("report_no", html.stem), generated=meta.get("generated"), has_simulated=data.get("has_simulated"),
                headline=summary.get("headline"))
    if item["kind"] == "event":
        event = data.get("event", {})
        item.update(event_no=meta.get("event_no"), version=meta.get("version"), reason=meta.get("reason"),
                    river=event.get("river"), level=event.get("level_name"), is_test=bool(meta.get("is_test")))
    else:
        item.update(status=(data.get("summary") or {}).get("status"), period=meta.get("period"), trigger=meta.get("trigger", "manual"))
    try:
        review = load_review(folder)
    except (OSError, ValueError):
        review = {"flags": {}}
    item["ai"] = ai_summary(data, review)
    return item


_summary_cache: dict[str, tuple[float, dict]] = {}


def list_reports() -> list[dict]:
    folders = [f for f in REPORTS_ROOT.glob("daily/*") if f.is_dir()]
    folders += [f for f in REPORTS_ROOT.glob("events/*/v*") if f.is_dir()]
    folders += [f for f in REPORTS_ROOT.glob("events/test/*/v*") if f.is_dir()]
    items = []
    for folder in folders:
        html = _html_in(folder)
        if not html:
            continue
        key, stamp = str(folder), html.stat().st_mtime
        cached = _summary_cache.get(key)
        if not cached or cached[0] != stamp:
            cached = (stamp, _summary(folder))
            _summary_cache[key] = cached
        if cached[1]:
            items.append(cached[1])
    event_nos = {i["event_no"] for i in items if i.get("event_no")}
    if event_nos:
        with SessionLocal() as db:
            states = {e.event_no: e for e in db.query(FloodEvent).filter(FloodEvent.event_no.in_(event_nos))}
        for i in items:
            e = states.get(i.get("event_no"))
            if e is not None:
                i.update(event_status=e.status, event_peak=LEVEL_NAMES.get(e.peak_level), event_opened=e.opened_at.isoformat() if e.opened_at else None)
    return sorted(items, key=lambda r: r["created_at"], reverse=True)


def report_file(report_id: str, kind: str = "html") -> Path:
    folder = _safe_folder(report_id)
    path = folder / "report.json" if kind == "json" else _html_in(folder)
    if not path or not path.exists():
        raise FileNotFoundError(report_id)
    return path


def delete_report(report_id: str) -> None:
    """Delete one daily report, one event report version, or a whole event (all its versions)."""
    folder = _safe_folder(report_id)
    rel = folder.relative_to(REPORTS_ROOT.resolve()).parts
    is_daily = len(rel) == 2 and rel[0] == "daily"
    is_version = rel[0] == "events" and folder.name.startswith("v") and len(rel) in (3, 4)
    is_event = rel[0] == "events" and len(rel) in (2, 3) and folder.name.startswith("FER-")
    if not (is_daily or is_version or is_event):
        raise FileNotFoundError(report_id)
    shutil.rmtree(folder)
    for key in [k for k in _summary_cache if k.startswith(str(folder))]:
        _summary_cache.pop(key, None)
    parent = folder.parent
    if is_version and parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()
        is_event, folder = True, parent
    if is_event and "test" in rel:  # a deleted test event is forgotten completely
        with SessionLocal() as db:
            db.query(FloodEvent).filter(FloodEvent.event_no == folder.name, FloodEvent.is_test.is_(True)).delete()
            db.commit()


# ------------------------------------------------------------------ options
def options() -> dict:
    stations = [{"id": sid, "name": STATION_NAMES[sid], "river": STATION_RIVER[sid], "impact_available": sid in EXPOSURE_REGIONS}
                for chain in RIVER_CHAINS.values() for sid in chain]
    seen, unique = set(), []
    for s in stations:
        if s["id"] not in seen:
            seen.add(s["id"])
            unique.append(s)
    with SessionLocal() as db:
        open_tests = [{"event_no": e.event_no, "river": e.river, "level": LEVEL_NAMES.get(e.peak_level), "versions": len(e.versions or [])}
                      for e in db.query(FloodEvent).filter(FloodEvent.is_test.is_(True), FloodEvent.status == "OPEN")]
    settings = get_settings()
    return {"schedule": {"enabled": settings.daily_report_schedule_enabled, "time_pkt": settings.daily_report_time,
                         "next_run": daily_report_scheduler.next_run().isoformat() if settings.daily_report_schedule_enabled else None},
            "watcher_enabled": settings.flood_event_reports_enabled,
            "stations": unique, "categories": list(LEVELS), "scenarios": SCENARIOS, "open_test_events": open_tests,
            "test_flood_regions": [{"id": "trimmu_jhang", "name": "Trimmu / Jhang"}, {"id": "balloki", "name": "Balloki"}],
            "busy": _running is not None}


# ------------------------------------------------------------------ jobs
def get_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)


def list_jobs() -> list[dict]:
    return sorted(_jobs.values(), key=lambda j: j["started_at"], reverse=True)[:10]


def _start(kind: str, label: str, target, *args) -> dict:
    global _running
    with _job_lock:
        if _running and _jobs[_running]["status"] == "running":
            raise RuntimeError(f"Another report is being generated: {_jobs[_running]['label']}")
        job_id = uuid.uuid4().hex[:12]
        job = {"id": job_id, "kind": kind, "label": label, "status": "running", "message": "Started",
               "started_at": datetime.now(timezone.utc).isoformat(), "finished_at": None, "reports": [], "error": None}
        _jobs[job_id] = job
        _running = job_id

    def run():
        global _running
        try:
            target(job, *args)
            job["status"] = "done"
        except Exception as exc:  # reported to the UI
            logger.exception("Report job %s failed", job_id)
            job.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        finally:
            job["finished_at"] = datetime.now(timezone.utc).isoformat()
            with _job_lock:
                _running = None

    threading.Thread(target=run, name=f"report-job-{job_id}", daemon=True).start()
    return job


def _report_ref(path: Path) -> dict:
    return {"id": path.parent.relative_to(REPORTS_ROOT).as_posix(), "file_name": path.name}


def start_daily(run_satellite: bool, capture_snapshots: bool, test_flood_region: str | None, trigger: str = "manual",
                ai_analysis: bool | None = None, ai_review: str | None = None) -> dict:
    def work(job):
        from app.reports.daily_report import generate
        job["message"] = "Collecting portal data" + (", satellite checks" if run_satellite else "") + (" and portal visuals" if capture_snapshots else "")

        def progress(message: str) -> None:
            job["message"] = message

        path = generate(get_settings().report_api_base, run_satellite=run_satellite, capture_snapshots=capture_snapshots,
                        frontend_url=get_settings().report_frontend_url, test_flood_region=test_flood_region, trigger=trigger,
                        ai_analysis=ai_analysis, ai_review=ai_review, progress=progress)
        job["reports"] = [_report_ref(path)]
        ai = json.loads((path.parent / "report.json").read_text(encoding="utf-8")).get("ai_analysis") or {}
        job["message"] = "Daily report ready" + _ai_message(ai)
    return _start("daily", "Daily Flood Situation Report" + (" (scheduled)" if trigger == "scheduled" else ""), work)


def _close_open_test_events(note: str) -> list[str]:
    """Close open TEST events without issuing a closure report (used to start a fresh test)."""
    now = datetime.now(timezone.utc)
    closed = []
    with SessionLocal() as db:
        for event in db.query(FloodEvent).filter(FloodEvent.is_test.is_(True), FloodEvent.status == "OPEN"):
            event.status, event.closed_at, event.current_level = "CLOSED", now, 0
            event.versions = list(event.versions or []) + [{"version": None, "reason": "Closed", "level": event.peak_level,
                                                            "level_name": LEVEL_NAMES.get(event.peak_level), "issued_at": now.isoformat(),
                                                            "path": None, "note": note}]
            closed.append(event.event_no)
        db.commit()
    return closed


def _ai_message(ai: dict) -> str:
    status = ai.get("status")
    if status in ("complete", "partial"):
        return f". AI analysis {status}: {len(ai.get('flags') or {})} flagged signal(s) explained."
    if status in ("unavailable", "failed"):
        return f". AI analysis not run: {ai.get('reason')}"
    if status == "no_flags":
        return ". No flagged signals, so no AI analysis."
    return ""


def start_flood_event(signals: list[dict], mode: str, run_satellite: bool, capture_snapshots: bool, label: str,
                      ai_analysis: bool = False, ai_review: str | None = None) -> dict:
    """mode: 'new' (close open test events first), 'continue' (feed the open test event; dedupe applies),
    'close' (a cycle without signals: issues the closure report), 'real' (check real data now)."""
    if mode in ("new", "continue"):
        if not signals:
            raise ValueError("Add at least one station reading")
        built = [test_signal(s["station_id"], s["category"], s.get("discharge")) for s in signals]
    else:
        built = []

    def work(job):
        from app.reports.event_report import generate_event_report

        def progress(message: str) -> None:
            job["message"] = message

        def generate(event, reason):
            job["message"] = f"Generating {event.event_no} ({reason})"
            return generate_event_report(event, reason, api_base=get_settings().report_api_base, frontend_url=get_settings().report_frontend_url,
                                         run_satellite=run_satellite, capture_snapshots=capture_snapshots, trigger="test",
                                         ai_analysis=ai_analysis, ai_review=ai_review, progress=progress)

        if mode == "real":
            from app.services.flood_event_watcher import run_live_cycle
            job["message"] = "Checking real data for flood signals"
            results = run_live_cycle()
        else:
            if mode == "new":
                closed = _close_open_test_events("Closed from the Reports screen to start a new test event")
                if closed:
                    job["message"] = f"Closed open test event(s): {', '.join(closed)}"
            results = run_cycle(SessionLocal, built, is_test=True, generate=generate,
                                close_after_hours=0 if mode == "close" else get_settings().flood_event_close_after_hours)
        job["results"] = results
        job["reports"] = [_report_ref(Path(r["path"])) for r in results if r.get("path")]
        failed = [r for r in results if r.get("error")]
        if failed:
            raise RuntimeError("; ".join(f"{r['event_no']}: {r['error']}" for r in failed))
        if not results:
            job["message"] = ("No report due: no real flood signal right now." if mode == "real" else
                              "No report due: the open test event is already reported at this level (dedupe), "
                              "or there was no open test event to close.")
        else:
            job["message"] = "; ".join(f"{r['event_no']}: {r['reason']} ({r['level']})" for r in results)

    return _start("event", label, work)


class DailyReportScheduler:
    """Generates the Daily Flood Situation Report once a day at settings.daily_report_time (PKT)."""

    def __init__(self):
        self.task: asyncio.Task | None = None

    @staticmethod
    def next_run(now: datetime | None = None) -> datetime:
        local = (now or datetime.now(timezone.utc)).astimezone(PKT)
        hour, minute = (int(x) for x in get_settings().daily_report_time.split(":"))
        run = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if run <= local:
            run += timedelta(days=1)
        return run

    async def _worker(self):
        while True:
            wait = (self.next_run() - datetime.now(timezone.utc)).total_seconds()
            await asyncio.sleep(max(wait, 1))
            settings = get_settings()
            for attempt in range(12):  # if another report is generating, retry every 5 min for an hour
                try:
                    start_daily(settings.report_run_satellite, settings.report_capture_snapshots,
                                settings.daily_report_test_flood_region, trigger="scheduled",
                                ai_analysis=settings.ai_analysis_enabled)
                    break
                except RuntimeError:
                    await asyncio.sleep(300)
                except Exception:
                    logger.exception("Scheduled daily report could not start")
                    break
            await asyncio.sleep(61)  # never run twice for the same minute

    def start(self):
        if get_settings().daily_report_schedule_enabled and (self.task is None or self.task.done()):
            self.task = asyncio.create_task(self._worker())

    async def stop(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None


daily_report_scheduler = DailyReportScheduler()
