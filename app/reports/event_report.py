"""Flood Event Report (FER): a report about one flood incident on one river system.

Triggered by app/reports/flood_events.py when an event opens, escalates or closes.
Uses the shared PortalCollector and the shared report renderer; the page body is
templates/flood_event_report.js. Spec: docs/reports/flood_event_report_spec.md.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from shapely.geometry import Point, shape

from app.reports.collector import (
    EXPOSURE_REGIONS, PKT, RIVER_CHAINS, ROOT, STATION_COORDS, STATION_NAMES, TRAVEL_HOURS, PortalCollector, _iso, _pkt,
    nearest_preview_area, shot_model_graphs, shot_population, shot_simulation_spread, shot_upstream,
)
from app.reports.flood_events import LEVEL_NAMES, LEVELS
from app.locations import LOCATIONS
from app.reports.flags import build_event_flags
from app.reports.render import render_page

# Districts within this distance (degrees, ~35 km) of a station on the river form its corridor.
CORRIDOR_DEG = 0.35

# FloodGuard checklist by level. Guidance for supervisors, not an official SOP.
CHECKLIST = {
    1: ["Confirm the forecast with FFD and the next GloFAS/GEOGloWS update.",
        "Pre-alert control rooms of downstream districts with the expected timing.",
        "Check that gauges on this river are reporting (stale readings hide a rise)."],
    2: ["Notify downstream districts with the arrival times in section 04.",
        "Warn riverine (katcha) settlements in the active floodplain.",
        "Verify pending citizen reports along this river."],
    3: ["Activate district emergency operation centres downstream.",
        "Prepare evacuation of floodplain settlements in arrival-time order.",
        "Position rescue boats and relief stocks near the exposed settlements in section 09."],
    4: ["Begin evacuation of floodplain settlements in arrival-time order.",
        "Patrol embankments and coordinate barrage operations with the Irrigation Department.",
        "Request fresh satellite passes for the reach below the highest station."],
}


def event_to_dict(event) -> dict:
    if isinstance(event, dict):
        return event
    fields = ("id", "event_no", "river", "status", "is_test", "current_level", "peak_level", "reported_level", "peak_value_cumecs",
              "stations", "signals", "versions", "opened_at", "last_signal_at", "quiet_since", "closed_at")
    data = {f: getattr(event, f) for f in fields}
    for key in ("opened_at", "last_signal_at", "quiet_since", "closed_at"):
        data[key] = data[key].isoformat() if data[key] else None
    return data


class FloodEventReportBuilder(PortalCollector):
    def __init__(self, api_base: str, event: dict, reason: str, version: int, work_dir: Path,
                 db_path: Path = ROOT / "floodguard.db", run_satellite: bool = True, capture_snapshots: bool = True,
                 frontend_url: str = "http://127.0.0.1:3000", generated_at: datetime | None = None):
        super().__init__(api_base, db_path, generated_at, run_satellite, capture_snapshots, frontend_url)
        self.event, self.reason, self.version, self.work_dir = event, reason, version, work_dir
        self.is_test = bool(event.get("is_test"))
        opened = _iso(event.get("opened_at")) or self.generated_at
        self.period_start, self.period_end = min(opened, self.generated_at - timedelta(days=1)), self.generated_at

    # ------------------------------------------------------------------ build
    def build(self) -> dict:
        system, _ = self._try("system status", self._get, "/system/status")
        monitoring, monitoring_error = self._try("river monitoring", self._get, "/river/monitoring")
        upstream, upstream_error = self._try("upstream forecasts", self._get, "/river/upstream-forecasts")
        national, national_error = self._try("national risk", self._get, "/gis/national-risk")
        alerts, _ = self._try("alerts", self._get, "/alerts")
        incidents, _ = self._try("incidents", self._get, "/incidents")
        reports, _ = self._try("citizen reports", self._get, "/citizen-reports")
        model_points, model_error = self._try("model forecasts", self._get, "/flood/model-forecasts")

        river = self.event["river"]
        chain = [sid for sid in (RIVER_CHAINS.get(river) or []) if not (river == "Sutlej" and sid == "PANJNAD")] \
            or [sid for sid in self.event.get("stations", []) if sid in STATION_NAMES]
        all_stations = self._stations(monitoring or {"stations": []})
        all_stations = self._apply_test_signals(all_stations)
        stations = [s for s in all_stations if s["id"] in chain]
        stations.sort(key=lambda s: chain.index(s["id"]))
        origin = self._origin(stations, chain)
        corridor = self._corridor(national, stations)
        if river == "Chenab":
            seasonal, seasonal_error = self._try("seasonal outlook", self._get, "/predictive/marala-monthly")
            seasonal_block = self._seasonal(seasonal, seasonal_error)
        else:
            seasonal_block = {"available": False, "reason": f"The portal has a seasonal outlook only for Marala (Chenab), not yet for the {river}."}
        data = {
            "meta": self._meta(system or {}),
            "event": self._event_block(),
            "stations": stations,
            "all_stations": all_stations,
            "arrival": self._arrival(stations, chain, origin),
            "inout": self._inout(stations),
            "forecasts": self._forecasts(stations),
            "seasonal": seasonal_block,
            "upstream": self._river_upstream(upstream, upstream_error, river),
            "models": self._river_models(model_points, model_error, river, chain),
        }
        data["satellite"] = self._event_satellite(stations)
        data["impact"] = self._event_impact(data["satellite"], stations, origin)
        data["districts"] = self._districts_at_risk(national, national_error, stations, data["arrival"])
        data["corridor"] = {"districts": sorted(corridor), "rule": f"Districts within about {round(CORRIDOR_DEG * 100)} km of a station on this river."}
        data["rainfall"] = self._river_rainfall(national, national_error, corridor)
        corridor_layer = {"features": [f for f in national["features"] if f["properties"]["district_name"] in corridor]} if national else None
        data["screening"] = self._districts(corridor_layer, all_stations, reports or [], incidents or []) if corridor else \
            {"available": False, "reason": national_error or "No districts found along this river"}
        data["operations"] = self._river_operations(alerts or [], incidents or [], reports or [], stations, corridor)
        names = {s["name"].lower() for s in stations}
        data["simulation_runs"] = [r for r in self._simulation_runs() if any(n in str(r["station"]).lower() for n in names)]
        data["checklist"] = self._checklist()
        # The signals that opened or raised the event, as flags (code). The AI step may explain them, never change them.
        data["flags"] = build_event_flags(data)
        data["snapshots"] = self._snapshots(self._snapshot_recipes(data, origin))
        data["data_quality"] = self._quality(monitoring_error, upstream, upstream_error, national_error, data)
        data["summary"] = self._summary(data, origin)
        data["provenance"] = dict(self.src.counts)
        data["has_simulated"] = self.is_test or self.src.counts.get("sim", 0) > 0
        return data

    # ------------------------------------------------------------------ parts
    def _meta(self, system: dict) -> dict:
        e = self.event
        return {"report_no": f"{e['event_no']}-v{self.version}", "event_no": e["event_no"], "version": self.version,
                "reason": self.reason, "generated": f"{self.generated_at.astimezone(PKT):%d %b %Y %H:%M} PKT",
                "data_mode": system.get("data_mode", "unknown"), "is_test": self.is_test,
                "simulation_enabled": system.get("simulation_enabled"), "ml_model_enabled": system.get("ml_model_enabled"),
                "units": "Discharge in cumecs (m³/s, as provided by the portal)"}

    def _event_block(self) -> dict:
        e = self.event
        signals = []
        for s in e.get("signals") or []:
            signals.append({**s, "at": _pkt(_iso(s.get("at"))), "sources": self.src(*s.get("sources", ["obs"]))})
        previous = [{**v, "issued_at": _pkt(_iso(v["issued_at"]))} for v in (e.get("versions") or [])]
        return {"river": e["river"], "status": e["status"], "level": e["peak_level"], "level_name": LEVEL_NAMES.get(e["peak_level"]),
                "current_level": e["current_level"], "current_level_name": LEVEL_NAMES.get(e["current_level"]),
                "previous_level_name": LEVEL_NAMES.get(e.get("reported_level") or 0),
                "opened": _pkt(_iso(e["opened_at"])), "closed": _pkt(_iso(e.get("closed_at"))),
                "quiet_since": _pkt(_iso(e.get("quiet_since"))), "peak_value": e.get("peak_value_cumecs"),
                "signals": signals, "versions": previous}

    def _apply_test_signals(self, stations: list[dict]) -> list[dict]:
        """In a test event, show the simulated reading on the station row, clearly marked."""
        if not self.is_test:
            return stations
        injected = {s["station_id"]: s for s in self.event.get("signals") or [] if s.get("simulated")}
        for row in stations:
            signal = injected.get(row["id"])
            if signal:
                row.update(category=signal["label"], simulated=True, sources=self.src("sim"),
                           real_category=row["category"], real_discharge=row["discharge"])
                if signal.get("value_cumecs") is not None:
                    row["discharge"] = signal["value_cumecs"]
        return stations

    @staticmethod
    def _origin(stations: list[dict], chain: list[str]) -> str | None:
        flooded = [s["id"] for s in stations if s["category"] in LEVELS]
        return flooded[0] if flooded else (chain[0] if chain else None)

    def _arrival(self, stations: list[dict], chain: list[str], origin: str | None) -> dict:
        if not origin or origin not in chain:
            return {"available": False, "reason": "The event is not on a monitored FFD river chain.", "rows": []}
        by_id = {s["id"]: s for s in stations}
        base = _iso(next((s["at"] for s in self.event.get("signals") or [] if s["station_id"] == origin and s.get("at")), None)) or self.generated_at
        rows, hours = [], 0
        for a, b in zip(chain[chain.index(origin):], chain[chain.index(origin) + 1:]):
            hours += TRAVEL_HOURS.get((a, b), 0)
            rows.append({"station": STATION_NAMES.get(b, b), "id": b, "hours": hours, "eta": _pkt(base + timedelta(hours=hours)),
                         "category_now": by_id.get(b, {}).get("category", "Unavailable"), "sources": self.src("est")})
        tail = {"Chenab": "Below Panjnad the water joins the Indus at Mithankot, upstream of Guddu.",
                "Sutlej": "Below Islam the water reaches Panjnad, then the Indus at Mithankot.",
                "Ravi": "Below Sidhnai the Ravi joins the Chenab upstream of Panjnad.",
                "Jhelum": "Below Rasul the Jhelum joins the Chenab at Trimmu."}.get(self.event["river"])
        return {"available": True, "origin": STATION_NAMES.get(origin, origin), "base_time": _pkt(base), "rows": rows, "tail": tail,
                "note": "Indicative FloodGuard travel times, to be calibrated against FFD peak timings."}

    def _river_upstream(self, payload: dict | None, error: str | None, river: str) -> dict:
        block = self._upstream(payload, error)
        if block.get("available"):
            block["stations"] = [u for u in block["stations"] if u["river"] == river or (river == "Indus" and u["river"] in ("Indus", "Gilgit"))]
        return block

    def _river_models(self, points, error, river: str, chain: list[str]) -> dict:
        block = self._models(points, error)
        names = [STATION_NAMES[c].lower() for c in chain] + [river.lower()]
        block["rows"] = [r for r in block["rows"] if any(n in f"{r['target']} {r['model']}".lower() for n in names)] or block["rows"][:4]
        return block

    def _event_satellite(self, stations: list[dict]) -> dict:
        flooded = sorted([s for s in stations if s["category"] in LEVELS], key=lambda s: -LEVELS[s["category"]])[:3]
        if not flooded:  # forecast-only watch: look at the most upstream signalled station on the chain
            ids = [sid for sid in self.event.get("stations", []) if sid in STATION_COORDS]
            flooded = [s for s in stations if s["id"] in ids[:1]]
        checks = []
        for s in flooded:
            row = {"location": f"{s['name']} station", "station_id": s["id"], "category": s["category"], "simulated_category": bool(s.get("simulated"))}
            if not self.run_satellite:
                row.update(result="not_run", reason="Satellite checks switched off for this run")
            else:
                lon, lat = STATION_COORDS[s["id"]]
                sar, error = self._try("Sentinel-1 check", self._sar, lat, lon)
                row.update(sar or {}, result=(sar or {}).get("status", "error"), error=error)
            row["sources"] = self.src("sat")
            checks.append(row)
        return {"checks": checks, "note": "Each check compares the latest Sentinel-1 radar pass with an earlier pass from the same orbit and removes permanent water. "
                                          "The image is always real, also in test events."}

    def _event_impact(self, satellite: dict, stations: list[dict], origin: str | None) -> dict:
        candidates = [s["id"] for s in stations if s["category"] in LEVELS and s["id"] in EXPOSURE_REGIONS]
        if not candidates:
            prepared = ", ".join(sorted({f"{STATION_NAMES[k]} ({v})" for k, v in EXPOSURE_REGIONS.items()}))
            return {"available": False, "reason": f"Exposure and population datasets are prepared only around {prepared}. "
                                                  "No flooded station on this river is inside one yet."}
        station = candidates[0]
        region = EXPOSURE_REGIONS[station]
        if self.is_test:
            impact = self._impact(region, "sample", sources=self.src("sim", "est"))
            impact["kind"] = "simulated"
            if impact.get("center") and self.run_satellite:
                lon, lat = impact["center"]
                impact["sar"], impact["sar_error"] = self._try("Sentinel-1 under simulated flood", self._sar, lat, lon)
        else:
            check = next((c for c in satellite["checks"] if c.get("station_id") == station and c.get("potential_flood_geojson")), None)
            if not check:
                return {"available": False, "station": STATION_NAMES[station], "region": region,
                        "reason": "No satellite water outline is available yet for this station (no recent pass, or no water outside the permanent-water reference). "
                                  "Impact is calculated once a pass shows water."}
            label = f"Sentinel-1 potential flood water, pass {str(check.get('during_date'))[:10]} (needs field confirmation)"
            impact = self._impact(region, "provided", check["potential_flood_geojson"], label, sources=self.src("sat", "est"))
            impact["kind"] = "satellite"
            impact["geojson"] = check["potential_flood_geojson"]
        impact.update(available=not impact.get("exposure_error"), station=STATION_NAMES[station], station_id=station,
                      reason=impact.get("exposure_error"))
        return impact

    def _districts_at_risk(self, national: dict | None, error: str | None, stations: list[dict], arrival: dict) -> dict:
        if not national:
            return {"available": False, "reason": error or "District layer unavailable", "rows": []}
        hours = {r["id"]: r for r in arrival.get("rows", [])}
        flooded = {s["id"] for s in stations if s["category"] in LEVELS}
        features = [(shape(f["geometry"]), f["properties"]) for f in national["features"] if f.get("geometry")]
        rows, seen = [], set()
        for s in stations:
            if s["id"] not in flooded and s["id"] not in hours:
                continue
            point = Point(STATION_COORDS[s["id"]])
            match = next((p for g, p in features if g.contains(point)), None)
            if not match or match["district_name"] in seen:
                continue
            seen.add(match["district_name"])
            eta = hours.get(s["id"])
            rows.append({"district": match["district_name"], "station": s["name"], "risk": round((match.get("risk_probability") or 0) * 100),
                         "why": "Flooded station in district" if s["id"] in flooded else f"Water expected in ~{eta['hours']} h",
                         "eta": eta["eta"] if eta else "Now", "sources": self.src("api", "est")})
        return {"available": True, "rows": rows, "geometries": None}

    @staticmethod
    def _corridor(national: dict | None, stations: list[dict]) -> set[str]:
        if not national:
            return set()
        points = [Point(STATION_COORDS[s["id"]]) for s in stations if s["id"] in STATION_COORDS]
        return {f["properties"]["district_name"] for f in national["features"]
                if f.get("geometry") and any(shape(f["geometry"]).distance(pt) <= CORRIDOR_DEG for pt in points)}

    def _river_rainfall(self, national: dict | None, error: str | None, corridor: set[str]) -> dict:
        if not national:
            return {"available": False, "reason": error or "No data"}
        props = [f["properties"] for f in national["features"] if f["properties"]["district_name"] in corridor]
        if not props:
            return {"available": False, "reason": "No districts found along this river"}
        props.sort(key=lambda p: max(p.get("rainfall_24h_mm") or 0, p.get("forecast_rainfall_24h_mm") or 0), reverse=True)
        self.src("api")
        rows = [{"district": p["district_name"], "observed": p.get("rainfall_24h_mm"), "forecast": p.get("forecast_rainfall_24h_mm"),
                 "temp": p.get("temperature_c"), "risk": round((p.get("risk_probability") or 0) * 100)} for p in props]
        wettest = max((max(r["observed"] or 0, r["forecast"] or 0) for r in rows), default=0)
        return {"available": True, "rows": rows,
                "verdict": "Little or no rain along the river: the flood water comes from upstream flow, not local rainfall." if wettest < 10
                           else f"Rain along the river (up to {wettest:.0f} mm in 24 h) can add local runoff to the river flow."}

    def _river_operations(self, alerts, incidents, reports, stations, corridor: set[str]) -> dict:
        ids = {s["id"] for s in stations}
        names = {s["name"].lower() for s in stations}
        districts = {d.lower() for d in corridor}

        def at_station(location_id, label=None):
            text = f"{location_id} {label or ''}".lower()
            return location_id in ids or any(n in text for n in names)

        def in_corridor(location_id):
            loc = LOCATIONS.get(location_id)
            return bool(loc and loc.name.lower() in districts)

        alerts = [a for a in alerts if at_station(a.get("location_id"), (a.get("event_metadata") or {}).get("station_name"))
                  or in_corridor(a.get("location_id"))]
        incidents = [i for i in incidents if at_station(i.get("location_id")) or in_corridor(i.get("location_id"))]
        reports = [r for r in reports if in_corridor(r.get("location_id"))]
        ops = self._operations(alerts, incidents, reports)
        ops["scope"] = "Items at stations on this river and in districts along it."
        return ops

    def _checklist(self) -> dict:
        level = self.event["peak_level"]
        items = CHECKLIST[min(max(level, 1), 4)] if self.reason != "Closed" else [
            "Confirm with FFD that all stations on this river are below low flood.",
            "Stand down pre-alerts issued for this event; keep damage and relief follow-up open.",
            "Close related incidents and resolve citizen reports along this river."]
        return {"level": LEVEL_NAMES.get(level), "items": items,
                "note": "FloodGuard checklist by flood level. It supports, and does not replace, NDMA/PDMA standard operating procedures."}

    def _snapshot_recipes(self, data: dict, origin: str | None) -> list[dict]:
        recipes = [shot_model_graphs("06", simulated=any("sim" in r["sources"] for r in data["models"]["rows"]))]
        recipes += [shot_upstream(u["name"], "06") for u in (data["upstream"].get("stations") or [])[:1]]
        impact = data["impact"]
        if impact.get("region") and impact.get("available"):
            if impact.get("kind") == "satellite":
                path = self.work_dir / "satellite_flood_extent.geojson"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"type": "Feature", "properties": {}, "geometry": impact["geojson"]}), encoding="utf-8")
                recipes.append(shot_population(impact["region"], "provided", "09", ["sat", "est"], str(path)))
            else:
                recipes.append(shot_population(impact["region"], "sample", "09", ["sim", "est"]))
        area = nearest_preview_area(origin) if origin in STATION_COORDS else None
        if area and self.reason != "Closed":
            recipes.append(shot_simulation_spread(area, "09", highest=self.event["peak_level"] >= 4))
        return recipes

    def _quality(self, monitoring_error, upstream, upstream_error, national_error, data) -> list[dict]:
        ages = [s["age_hours"] for s in data["stations"] if s["age_hours"] is not None]
        checks = data["satellite"]["checks"]
        shots = data["snapshots"]["shots"]
        return [
            {"feed": "FFD river state", "status": "Error" if monitoring_error else ("Stale" if not ages or min(ages) > 24 else "OK"),
             "note": monitoring_error or (f"Newest reading {min(ages):.0f} h old" if ages else "No readings")},
            {"feed": "Upstream forecasts (GloFAS, GEOGloWS)", "status": "Error" if upstream_error else "OK",
             "note": upstream_error or f"Stored {(data['upstream'].get('cached_at') or '—')} PKT"},
            {"feed": "District risk layer", "status": "Error" if national_error else "OK", "note": national_error or ""},
            {"feed": "Sentinel-1 radar", "status": "OK" if checks and all(c.get("result") not in ("error", "not_run") for c in checks) else ("None" if not checks else "Partial"),
             "note": "; ".join(c.get("error") or "" for c in checks if c.get("error"))},
            {"feed": "Portal snapshots", "status": "OK" if shots and all(s.get("image") for s in shots) else ("Unavailable" if not any(s.get("image") for s in shots) else "Partial"),
             "note": data["snapshots"].get("reason", "")},
        ]

    def _summary(self, data: dict, origin: str | None) -> dict:
        e, ev = self.event, data["event"]
        river, level_name = e["river"], ev["level_name"]
        flooded = [s for s in data["stations"] if s["category"] in LEVELS]
        where = ", ".join(f"{s['name']} ({s['category']})" for s in flooded) or ", ".join(s.get("station_name", "") for s in e.get("signals") or [])
        kinds = sorted({s["kind"] for s in e.get("signals") or []})
        first = (data["arrival"].get("rows") or [None])[0]
        people = data["impact"].get("people") if data["impact"].get("available") else None
        if self.reason == "Closed":
            headline = f"No flood signal on the {river} since {ev['quiet_since']} PKT. The event is closed. Highest level reached: {level_name}."
        else:
            lead = {"New event": f"{level_name} on the {river}", "Escalated": f"Escalated from {ev['previous_level_name']} to {level_name} on the {river}"}[self.reason]
            headline = (f"{lead}: {where}. Triggered by {' and '.join(kinds)} data. "
                        + (f"Water is expected at {first['station']} in about {first['hours']} h ({first['eta']} PKT). " if first else "")
                        + (f"About {people:,.0f} people are in the {'simulated' if self.is_test else 'satellite-detected'} flood extent (lower bound). " if people else ""))
        sat_km2 = sum(c.get("potential_flood_area_km2") or 0 for c in data["satellite"]["checks"])
        kpis = [
            {"value": level_name, "label": "Event level (highest)"},
            {"value": f"{e['peak_value_cumecs']:,.0f}" if e.get("peak_value_cumecs") else "—", "label": "Peak observed discharge (cumecs)"},
            {"value": f"{len(flooded)} / {len(data['stations'])}", "label": f"{river} stations in flood"},
            {"value": f"{first['station']} +{first['hours']} h" if first else "—", "label": "Next station downstream"},
            {"value": f"{people:,.0f}" if people else "—", "label": "People in flood extent (lower bound)"},
            {"value": f"{sat_km2:.1f} km²", "label": "Possible flood water (satellite)"},
        ]
        return {"headline": headline.strip(), "kpis": kpis}


def generate_event_report(event, reason: str, api_base: str = "http://127.0.0.1:8000/api/v1",
                          output_root: Path | None = None, trigger: str | None = None, ai_analysis: bool | None = None,
                          ai_review: str | None = None, progress=None, **options) -> Path:
    """Phase 1 writes the deterministic event report; phase 2 (optional) adds the AI analysis of its flags.
    Real events come from the watcher (automatic, AI per settings); test events get AI only when asked."""
    from app.core.config import get_settings
    from app.reports.ai.runner import placeholder, review_mode_for, run_ai_analysis

    ev = event_to_dict(event)
    trigger = trigger or ("test" if ev.get("is_test") else "watcher")
    version = len(ev.get("versions") or []) + 1
    output_root = output_root or ROOT / "reports" / "events"
    folder = output_root / ("test" if ev.get("is_test") else "") / ev["event_no"] / f"v{version}"
    folder.mkdir(parents=True, exist_ok=True)
    builder = FloodEventReportBuilder(api_base, ev, reason, version, work_dir=folder, **options)
    data = builder.build()
    run_ai = (get_settings().ai_analysis_enabled and not ev.get("is_test")) if ai_analysis is None else ai_analysis
    review_mode = review_mode_for(trigger, ai_review)
    data["meta"]["trigger"] = trigger
    data["ai_analysis"] = placeholder(run_ai, trigger, review_mode)
    (folder / "report.json").write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    path = folder / f"{data['meta']['report_no']}.html"
    path.write_text(render_page("flood_event_report.js", data, data["meta"]["report_no"]), encoding="utf-8")
    if run_ai:
        run_ai_analysis(folder, trigger=trigger, review_mode=review_mode, include_simulated=bool(ev.get("is_test")), progress=progress)
    return path
