"""Flagged signals: values that a FloodGuard rule flagged in a report.

Flags are computed by code from the report's own data. They state the measured value, the
risk category and the rule, and nothing else. The optional AI step (app/reports/ai/) may
explain a flag; it never changes one. Rules are the same as the report's own logic:
collector.is_sharp_rise, flood_events.forecast_threshold_hit, the daily status rules.
Spec: docs/reports/daily_report_spec.md and flood_event_report_spec.md, section 02.
"""

from __future__ import annotations

from app.gis.river_stations import RIVER_CHAINS
from app.reports.collector import STATION_NAMES, is_sharp_rise
from app.reports.flood_events import LEVELS, forecast_threshold_hit

ORDER = ["Below low", "Low flood", "Medium flood", "High flood", "Very high flood", "Exceptionally high flood"]
KIND_LABELS = {
    "observed_flood": "Station in flood",
    "forecast_threshold": "Forecast above flood threshold",
    "satellite_water": "Possible flood water (satellite)",
    "forecast_disagreement": "Forecast sources disagree",
    "district_high": "High district screening risk",
    "sharp_rise": "Sharp rise",
}
# Other names used for stations in FFD bulletins, FFC reports and plans (for document search).
ALIASES = {
    "PANJNAD": ["Punjnad"], "GANDA_SINGH_WALA": ["G.S. Wala", "Ganda Singh"], "NOWSHERA": ["Nowshehra"],
    "KALABAGH": ["Jinnah Barrage", "Jinnah"], "SULEMANKI": ["Suleimanki"], "ISLAM": ["Islam Headworks"],
    "TAUNSA": ["Taunsa Barrage"], "GUDDU": ["Guddu Barrage"], "SUKKUR": ["Sukkur Barrage"], "KOTRI": ["Kotri Barrage"],
    "TRIMMU": ["Trimmu Headworks"], "MARALA": ["Marala Headworks"], "QADIRABAD": ["Qadirabad Headworks"],
    "KHANKI": ["Khanki Headworks"], "BALLOKI": ["Balloki Headworks"], "SIDHNAI": ["Sidhnai Headworks"],
    "TARBELA": ["Tarbela Dam"], "MANGLA": ["Mangla Dam", "Mangla Reservoir"], "CHASHMA": ["Chashma Barrage"],
    "RASUL": ["Rasul Barrage"], "JASSAR": [], "SHAHDARA": ["Ravi at Lahore"],
}


def _fmt(value: float | None, digits: int = 0) -> str:
    return "—" if value is None else f"{value:,.{digits}f}"


def _upstream_of(station_id: str) -> list[str]:
    for chain in RIVER_CHAINS.values():
        if station_id in chain and chain.index(station_id) > 0:
            return [chain[chain.index(station_id) - 1]]
    return []


def _terms(station_id: str | None, river: str | None, *extra: str) -> list[str]:
    terms = []
    if station_id:
        terms += [STATION_NAMES.get(station_id, station_id)] + ALIASES.get(station_id, [])
        terms += [STATION_NAMES.get(u, u) for u in _upstream_of(station_id)]
    if river:
        terms.append(river)
    terms += [t for t in extra if t]
    seen, out = set(), []
    for t in terms:
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def _flag(kind: str, title: str, *, station_id=None, location=None, river=None, district=None, measured, category,
          priority: float, simulated=False, query_terms=(), agent_eligible=True) -> dict:
    location = location or STATION_NAMES.get(station_id or "", station_id)
    # Anchor terms: a retrieved passage must name the flagged place (station, aliases or district).
    anchors = ([STATION_NAMES.get(station_id, station_id)] + ALIASES.get(station_id, [])) if station_id else [district or location]
    return {"kind": kind, "kind_label": KIND_LABELS[kind], "title": title, "station_id": station_id,
            "location": location, "river": river, "district": district,
            "measured": measured, "category": category, "priority": round(priority, 2), "simulated": simulated,
            "query_terms": list(query_terms), "anchor_terms": [a for a in anchors if a], "agent_eligible": agent_eligible}


def _number(flags: list[dict]) -> list[dict]:
    flags.sort(key=lambda f: -f["priority"])
    for i, f in enumerate(flags, 1):
        f["id"] = f"F{i}"
    return flags


def _observed_flood(s: dict, status_effect: str) -> dict:
    sim = bool(s.get("simulated"))
    return _flag(
        "observed_flood", f"{s['category']} at {s['name']}", station_id=s["id"], river=s.get("river"),
        measured={"label": "FFD discharge", "value": f"{_fmt(s.get('discharge'))} cumecs", "time": s.get("observed_at"),
                  "detail": "Simulated test reading" if sim else None, "sources": ["sim"] if sim else ["obs"]},
        category={"label": s["category"], "rule": "FFD flood category at or above Low flood",
                  "status_effect": status_effect},
        priority=100 + 10 * LEVELS.get(s["category"], 0), simulated=sim,
        query_terms=_terms(s["id"], s.get("river"), s["category"], "flood"))


def _sharp_rise(s: dict) -> dict:
    change, discharge = s["change_24h"], s["discharge"]
    pct = 100 * change / max(discharge - change, 1)
    return _flag(
        "sharp_rise", f"{s['name']} rose {_fmt(change)} cumecs in 24 h", station_id=s["id"], river=s.get("river"),
        measured={"label": "24 h change", "value": f"+{_fmt(change)} cumecs (+{pct:.0f}%)",
                  "detail": f"Now {_fmt(discharge)} cumecs", "time": s.get("observed_at"), "sources": ["obs"]},
        category={"label": "Sharp rise", "rule": "Rise of more than 50 cumecs and more than 10% in 24 h",
                  "status_effect": "No change to the status. Shown for awareness."},
        priority=30 + min(pct / 10, 19), query_terms=_terms(s["id"], s.get("river"), "rise", "discharge", "release"))


def _forecast_threshold(u: dict, hit: tuple[str, float], station_id: str | None) -> dict:
    provider, peak = hit
    threshold = u["low_flood_threshold"]
    peaks = " · ".join(f"{p['provider']} {_fmt(p['peak'])}" for p in u["providers"] if p.get("peak") is not None)
    return _flag(
        "forecast_threshold", f"Forecast peak above the low-flood threshold at {u['name']}", station_id=station_id,
        location=u["name"], river=u.get("river"),
        measured={"label": "Forecast peaks", "value": f"{peaks} cumecs",
                  "detail": f"{u.get('low_flood_threshold_kind') or 'Reference'} low-flood threshold {_fmt(threshold)} cumecs",
                  "time": None, "sources": ["api"]},
        category={"label": "Flood watch (forecast)",
                  "rule": "A provider peak at or above the low-flood threshold, and every provider at least 75% of it",
                  "status_effect": "Opens a flood watch event (Flood Event Report)."},
        priority=80, query_terms=_terms(station_id, u.get("river"), "forecast", "flood", "GloFAS"))


def _forecast_disagreement(u: dict, station_id: str | None) -> dict:
    peaks = " · ".join(f"{p['provider']} {_fmt(p['peak'])}" for p in u["providers"] if p.get("peak") is not None)
    return _flag(
        "forecast_disagreement", f"Forecast sources disagree on the {u['name']} peak", station_id=station_id,
        location=u["name"], river=u.get("river"),
        measured={"label": "Forecast peaks", "value": f"{peaks} cumecs",
                  "detail": f"Gap {_fmt(u.get('gap_cumecs'))} cumecs ({u['agreement_pct']}%)", "time": None, "sources": ["api"]},
        category={"label": "Forecast disagreement", "rule": "Providers differ by more than 25% and more than 100 cumecs",
                  "status_effect": "Raises the national status to Watch."},
        priority=60 + min((u["agreement_pct"] or 0) / 10, 9),
        query_terms=_terms(station_id, u.get("river"), "forecast", "GloFAS", "GEOGloWS"))


def _station_for_upstream(name: str) -> str | None:
    lowered = name.lower()
    return next((sid for sid, station in STATION_NAMES.items() if station.lower() in lowered), None)


def build_daily_flags(data: dict) -> list[dict]:
    flags: list[dict] = []
    for s in data.get("stations", []):
        if not s.get("available"):
            continue
        if s["category"] in LEVELS and not s.get("stale"):
            effect = "Raises the national status to Emergency." if ORDER.index(s["category"]) >= 3 else \
                "Raises the national status to Warning."
            flags.append(_observed_flood(s, effect))
        if is_sharp_rise(s.get("change_24h"), s.get("discharge")):
            flags.append(_sharp_rise(s))
    upstream = data.get("upstream") or {}
    for u in upstream.get("stations") or []:
        station_id = _station_for_upstream(u["name"])
        peaks = [(p["provider"], p["peak"]) for p in u["providers"] if p.get("peak") is not None and p.get("status", "available") == "available"]
        hit = forecast_threshold_hit(peaks, u.get("low_flood_threshold"))
        if hit:
            flags.append(_forecast_threshold(u, hit, station_id))
        if u.get("agreement_pct") is not None and not u.get("agree"):
            flags.append(_forecast_disagreement(u, station_id))
    for c in (data.get("satellite") or {}).get("checks", []):
        counts = c.get("result") == "potential_flooding_detected" and not c.get("triggered_by_simulation") \
            and (not c.get("station_id") or c.get("gauge_category") not in ("Below low",))
        if counts:
            flags.append(_flag(
                "satellite_water", f"Possible flood water near {c['location']}", station_id=c.get("station_id"),
                location=c["location"],
                measured={"label": "Water outside permanent water", "value": f"{c.get('potential_flood_area_km2') or 0:.1f} km²",
                          "detail": f"Sentinel-1 pass {str(c.get('during_date') or '')[:10]}", "time": None, "sources": ["sat"]},
                category={"label": "Possible flood water", "rule": "Radar water outside the permanent-water reference, "
                          "and the station's gauge (if any) above Below low",
                          "status_effect": "Raises the national status to Watch."},
                priority=70, query_terms=_terms(c.get("station_id"), None, "flood", "inundation", "satellite")))
    for d in (data.get("districts") or {}).get("top_risk", []):
        if d.get("risk", 0) >= 60:
            flags.append(_flag(
                "district_high", f"High screening risk in {d['district']}", district=d["district"], location=d["district"],
                measured={"label": "Screening risk", "value": f"{d['risk']}%", "detail": ", ".join(d.get("factors") or []) or None,
                          "time": None, "sources": ["api", "est"]},
                category={"label": "High screening risk", "rule": "District screening probability of 60% or more",
                          "status_effect": "Raises the national status to Watch."},
                priority=50 + d["risk"] / 10, query_terms=[d["district"], "rain", "flood", "district"]))
    return _number(flags)


def build_event_flags(data: dict) -> list[dict]:
    """Flags for a flood event report: the signals that opened or raised the event."""
    flags: list[dict] = []
    stations = {s["id"]: s for s in data.get("stations", [])}
    for sig in (data.get("event") or {}).get("signals", []):
        sim = bool(sig.get("simulated")) or "sim" in (sig.get("sources") or [])
        station_id = sig.get("station_id") if sig.get("station_id") in STATION_NAMES else None
        river = sig.get("river")
        if sig.get("kind") == "observed":
            s = stations.get(station_id) or {"id": station_id, "name": sig.get("station_name"), "river": river,
                                             "discharge": sig.get("value_cumecs"), "observed_at": sig.get("at")}
            s = {**s, "category": sig["label"], "discharge": sig.get("value_cumecs") if sig.get("value_cumecs") is not None else s.get("discharge"),
                 "simulated": sim, "id": station_id or sig.get("station_id"), "name": s.get("name") or sig.get("station_name")}
            flags.append(_observed_flood(s, f"Event level: {sig['label']}."))
        else:
            label = "Forecast above flood threshold" if sig.get("kind") == "forecast" else "Model rates flood risk high"
            flags.append(_flag(
                "forecast_threshold", f"{label}: {sig.get('station_name')}", station_id=station_id, location=sig.get("station_name"),
                river=river,
                measured={"label": "Forecast" if sig.get("kind") == "forecast" else "Model output",
                          "value": f"{_fmt(sig.get('value_cumecs'))} cumecs" if sig.get("value_cumecs") is not None else "—",
                          "detail": sig.get("detail"), "time": sig.get("at"), "sources": ["sim"] if sim else (sig.get("sources") or ["api"])},
                category={"label": sig.get("label", "Flood watch (forecast)"), "rule": "Forecast flood watch rule of the event trigger",
                          "status_effect": "Event level: Flood watch (forecast)."},
                priority=80, simulated=sim, query_terms=_terms(station_id, river, "forecast", "flood")))
    return _number(flags)
