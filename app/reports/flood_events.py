"""Flood event detection, dedupe and report triggering.

Flow (run after each river-monitoring or upstream-forecast refresh, or from the CLI):
  1. detect_signals(): qualifying flood signals from REAL data only
       - observed:  FFD category Low flood or higher (level 2-6), reading <= 48 h old
       - forecast:  GloFAS/GEOGloWS peak >= the station's low-flood threshold and the
                    other provider roughly agrees (>= 75% of the threshold)  (level 1)
       - model:     operational FloodGuard model at High or above, live data mode only;
                    placeholder ("dummy") model outputs never count             (level 1)
     Flash-flood / urban heuristics are not used: they read CRITICAL in dry weather.
  2. update_events(): one event per river system (a wave moving downstream stays one
     incident). Levels only escalate the event; dips and returns at or below the level
     already reported never produce another report. The event closes after
     `close_after_hours` with no signal (stale gauge readings hold it open).
  3. pending_reports(): reports are derived from stored state, so a failed report is
     retried next cycle and never duplicated:
       - New event       (no versions yet)
       - Escalated       (peak_level > reported_level)
       - Closed          (status CLOSED, closing version not issued)

Test mode: signals injected with is_test=True create separate test events (never mixed
with real ones), and their reports carry the TEST banner.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.gis.river_stations import STATIONS
from app.locations import LOCATIONS
from app.models.flood_event import FloodEvent

logger = logging.getLogger(__name__)

LEVELS = {"Low flood": 2, "Medium flood": 3, "High flood": 4, "Very high flood": 5, "Exceptionally high flood": 6}
LEVEL_NAMES = {0: "No signal", 1: "Flood watch (forecast)", **{v: k for k, v in LEVELS.items()}}
MAX_OBSERVATION_AGE_HOURS = 48
STATION_RIVER = {sid: river for sid, _name, river, *_ in STATIONS}
STATION_NAMES = {sid: name for sid, name, *_ in STATIONS}
UPSTREAM_RIVER = {"Gilgit": "Indus", "Upper Indus": "Indus"}
_lock = threading.Lock()


def _utc(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _station_for(name: str) -> str | None:
    lowered = name.lower()
    return next((sid for sid, station in STATION_NAMES.items() if station.lower() in lowered), None)


def forecast_threshold_hit(peaks: list[tuple[str, float]], threshold: float | None) -> tuple[str, float] | None:
    """Forecast flood watch rule: one provider's peak at or above the low-flood threshold, and every
    provider at least 75% of it. Shared by the event watcher and the report flags."""
    if not threshold:
        return None
    above = [(name, peak) for name, peak in peaks if peak >= threshold]
    if not above or not all(peak >= 0.75 * threshold for _name, peak in peaks):
        return None
    return max(above, key=lambda item: item[1])


def detect_signals(monitoring: dict | None, upstream: dict | None, risks: list[dict] | None = None,
                   model_points: list[dict] | None = None, system: dict | None = None, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    signals: list[dict] = []
    for s in (monitoring or {}).get("stations", []):
        level = LEVELS.get(s.get("flood_category"))
        observed = _utc(s.get("observed_at"))
        if not level or not observed:
            continue
        age = (now - observed).total_seconds() / 3600
        signals.append({"kind": "observed", "river": STATION_RIVER.get(s["id"], s.get("river")), "station_id": s["id"],
                        "station_name": STATION_NAMES.get(s["id"], s.get("name")), "level": level, "label": s["flood_category"],
                        "value_cumecs": s.get("current_discharge_cumecs"), "at": observed.isoformat(), "sources": ["obs"],
                        "stale": age > MAX_OBSERVATION_AGE_HOURS,
                        "detail": f"FFD reports {s['flood_category']} at {STATION_NAMES.get(s['id'], s['id'])} "
                                  f"({(s.get('current_discharge_cumecs') or 0):,.0f} cumecs, observed {age:.0f} h ago)."})
    for u in (upstream or {}).get("stations", []):
        threshold = (u.get("stats") or {}).get("low_flood_threshold_cumecs")
        if not threshold:
            continue
        peaks = [(p["provider"], p.get("peak_forecast_cumecs")) for p in u.get("providers", [])
                 if p.get("status") == "available" and p.get("peak_forecast_cumecs") is not None]
        hit = forecast_threshold_hit(peaks, threshold)
        if not hit:
            continue
        name, peak = hit
        kind = (u.get("stats") or {}).get("low_flood_threshold_kind", "reference")
        signals.append({"kind": "forecast", "river": UPSTREAM_RIVER.get(u.get("river"), u.get("river")),
                        "station_id": _station_for(u["name"]) or u["id"], "station_name": u["name"], "level": 1,
                        "label": LEVEL_NAMES[1], "value_cumecs": peak, "at": now.isoformat(), "sources": ["api"], "stale": False,
                        "detail": f"{name} forecasts a peak of {peak:,.0f} cumecs at {u['name']}, at or above the "
                                  f"{kind} low-flood threshold of {threshold:,.0f} cumecs; "
                                  + ", ".join(f"{n} {p:,.0f}" for n, p in peaks) + "."})
    live = (system or {}).get("data_mode") == "live" and not (system or {}).get("simulation_enabled")
    for r in (risks or []) if live else []:
        if str(r.get("severity", "")).upper() not in ("HIGH", "CRITICAL", "SEVERE", "EXTREME"):
            continue
        location = LOCATIONS.get(r.get("location_id"))
        if not location:
            continue
        signals.append({"kind": "model", "river": location.river_name, "station_id": r["location_id"], "station_name": location.name,
                        "level": 1, "label": LEVEL_NAMES[1], "value_cumecs": None, "at": now.isoformat(), "sources": ["ml"], "stale": False,
                        "detail": f"{r.get('model', 'Risk model')} rates {location.name} {r['severity']} "
                                  f"({round(100 * (r.get('flood_probability') or 0))}% flood probability)."})
    for p in model_points or []:
        meta = p.get("point_metadata") or {}
        if "dummy" in f"{meta.get('model_status', '')} {meta.get('simulation_source', '')}".lower():
            continue  # placeholder models never trigger a report
        issued = _utc(p.get("issued_at"))
        if str(p.get("risk_class", "")).lower() not in ("high", "very high", "extreme", "extremely high", "severe") or not issued \
                or now - issued > timedelta(hours=24):
            continue
        signals.append({"kind": "model", "river": p.get("river") or p.get("target_name"), "station_id": p.get("target_id"),
                        "station_name": p.get("target_name"), "level": 1, "label": LEVEL_NAMES[1], "value_cumecs": p.get("value"),
                        "at": issued.isoformat(), "sources": ["ml"], "stale": False,
                        "detail": f"{p.get('model_name')} forecasts {p.get('risk_class')} at {p.get('target_name')}."})
    return signals


def test_signal(station_id: str, category: str, discharge_cumecs: float | None = None, now: datetime | None = None) -> dict:
    """A simulated observed signal for testing the pipeline (creates a TEST event)."""
    now = now or datetime.now(timezone.utc)
    if category not in LEVELS:
        raise ValueError(f"category must be one of: {', '.join(LEVELS)}")
    return {"kind": "observed", "river": STATION_RIVER[station_id], "station_id": station_id, "station_name": STATION_NAMES[station_id],
            "level": LEVELS[category], "label": category, "value_cumecs": discharge_cumecs, "at": now.isoformat(),
            "sources": ["sim"], "stale": False, "simulated": True,
            "detail": f"SIMULATED: {category} at {STATION_NAMES[station_id]} (test signal, not real data)."}


def update_events(db, signals: list[dict], is_test: bool = False, now: datetime | None = None,
                  close_after_hours: int = 24) -> list[FloodEvent]:
    """Apply one detection cycle to the flood_events table. Returns the events touched."""
    now = now or datetime.now(timezone.utc)
    open_events = {e.river: e for e in db.scalars(select(FloodEvent).where(FloodEvent.status == "OPEN", FloodEvent.is_test == is_test))}
    # Panjnad is where Chenab and Sutlej water arrives: join that river's event, never a separate one.
    rivers_now = {s["river"] for s in signals}
    panjnad_river = "Sutlej" if ("Sutlej" in open_events or "Sutlej" in rivers_now) and not ("Chenab" in open_events or "Chenab" in rivers_now) else "Chenab"
    by_river: dict[str, list[dict]] = {}
    for signal in signals:
        river = panjnad_river if signal["river"] == "Panjnad" else signal["river"]
        by_river.setdefault(river, []).append({**signal, "river": river})
    touched = []
    for river, items in by_river.items():
        fresh = [s for s in items if not s.get("stale")]
        event = open_events.get(river)
        if event is None and not fresh:
            continue  # stale readings alone never open an event
        if event is None:
            day = now.strftime("%Y%m%d")
            prefix = f"FER-{'TEST-' if is_test else ''}{river.upper().replace(' ', '')}-{day}"
            count = len(db.scalars(select(FloodEvent.id).where(FloodEvent.event_no.like(f"{prefix}%"))).all())
            event = FloodEvent(event_no=f"{prefix}-{count + 1:02d}", river=river, is_test=is_test, opened_at=now,
                               current_level=0, peak_level=0, reported_level=0, stations=[], signals=[], versions=[])
            db.add(event)
        level = max(s["level"] for s in (fresh or items))
        event.current_level = level
        if fresh:  # only fresh data can raise the peak
            event.peak_level = max(event.peak_level or 0, max(s["level"] for s in fresh))
            values = [s["value_cumecs"] for s in fresh if s.get("value_cumecs") is not None and s["kind"] == "observed"]
            if values:
                event.peak_value_cumecs = max(event.peak_value_cumecs or 0, max(values))
        event.stations = sorted(set(event.stations or []) | {s["station_id"] for s in items})
        event.signals = items
        event.last_signal_at = now
        event.quiet_since = None
        touched.append(event)
    for river, event in open_events.items():
        if river in by_river:
            continue
        event.current_level = 0
        event.quiet_since = _utc(event.quiet_since) or now
        if now - event.quiet_since >= timedelta(hours=close_after_hours):
            event.status = "CLOSED"
            event.closed_at = now
        touched.append(event)
    db.commit()
    return touched


def pending_reports(db, is_test: bool | None = None) -> list[tuple[FloodEvent, str]]:
    query = select(FloodEvent)
    if is_test is not None:
        query = query.where(FloodEvent.is_test == is_test)
    pending = []
    for event in db.scalars(query):
        versions = event.versions or []
        if event.status == "CLOSED":
            if versions and versions[-1]["reason"] != "Closed":
                pending.append((event, "Closed"))
        elif not versions and event.peak_level > 0:
            pending.append((event, "New event"))
        elif versions and event.peak_level > event.reported_level:
            pending.append((event, "Escalated"))
    return pending


def record_version(db, event: FloodEvent, reason: str, path: str, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    versions = list(event.versions or [])
    versions.append({"version": len(versions) + 1, "reason": reason, "level": event.peak_level,
                     "level_name": LEVEL_NAMES.get(event.peak_level), "issued_at": now.isoformat(), "path": path})
    event.versions = versions
    if reason != "Closed":
        event.reported_level = event.peak_level
    db.commit()


def run_cycle(session_factory, signals: list[dict], is_test: bool = False, generate=None, close_after_hours: int = 24,
              dry_run: bool = False) -> list[dict]:
    """Update events from signals, then generate any pending reports. Serialised by a process lock."""
    with _lock, session_factory() as db:
        update_events(db, signals, is_test=is_test, close_after_hours=close_after_hours)
        results = []
        for event, reason in pending_reports(db, is_test=is_test):
            item = {"event_no": event.event_no, "river": event.river, "reason": reason,
                    "level": LEVEL_NAMES.get(event.peak_level), "path": None, "error": None}
            if not dry_run and generate is not None:
                try:
                    item["path"] = str(generate(event, reason))
                    record_version(db, event, reason, item["path"])
                except Exception as exc:  # retried next cycle because state is unchanged
                    logger.exception("Flood event report failed for %s", event.event_no)
                    item["error"] = f"{type(exc).__name__}: {exc}"
            results.append(item)
        return results
