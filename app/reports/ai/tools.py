"""Read-only tools for the bounded analysis agent (step 3).

Structured data comes from the report's own data (the same snapshot the report shows), the
database opened read-only (sqlite mode=ro) and GET requests to the local API. Documents come
from the knowledge base. Nothing here can write. Every data result carries a reference (T1, T2,
...) that the agent must cite; documents are referenced by their source.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import httpx
from shapely.geometry import Point, shape

from app.gis.river_stations import RIVER_CHAINS, upstream_ids
from app.locations import LOCATIONS
from app.reports.ai.explain import search_result_block
from app.reports.ai.knowledge import KnowledgeBase, query_words
from app.reports.collector import PKT, ROOT, STATION_COORDS, STATION_NAMES, TRAVEL_HOURS

# Rivers that join below a station's upstream chain (see the event report's downstream notes).
TRIBUTARIES = {"KALABAGH": ["NOWSHERA"], "TRIMMU": ["RASUL"], "PANJNAD": ["SIDHNAI", "ISLAM"], "GUDDU": ["PANJNAD"]}
MAX_POINTS = 48


def _strict(name: str, description: str, properties: dict) -> dict:
    return {"name": name, "description": description, "strict": True,
            "input_schema": {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}}


STATION = {"type": "string", "description": "FloodGuard station id, e.g. TRIMMU, KALABAGH, MARALA, PANJNAD, GANDA_SINGH_WALA."}
TOOL_DEFS = [
    _strict("get_station_readings", "Stored FFD discharge readings at a station (discharge, inflow, outflow) for the last N days, "
            "with the latest value, 24 h change and min/max. Use it to see the trend behind a flagged value.",
            {"station_id": STATION, "days": {"type": "integer", "description": "1 to 10."}}),
    _strict("get_upstream_context", "Current readings at the stations upstream of a station (including tributaries that join above it), "
            "dams and barrages releasing more or less than they receive, and indicative travel times.",
            {"station_id": STATION}),
    _strict("get_forecasts", "Forecasts for a station: GloFAS next-day and peak values, the FFD official forecast text, and the "
            "GloFAS/GEOGloWS forecast series of a matching upstream watch point with its low-flood threshold and agreement.",
            {"station_id": STATION}),
    _strict("get_rainfall", "Observed and forecast 24 h rainfall, temperature and screening risk for districts near a station or for a "
            "named district. Give a station_id, or a district name with station_id set to an empty string.",
            {"station_id": {"type": "string", "description": "Station id, or empty."},
             "district": {"type": "string", "description": "District name, or empty."}}),
    _strict("get_incidents_and_reports", "Alerts, incidents and citizen reports at or near a station or district in the last N days. "
            "Simulated items are marked.",
            {"station_id": {"type": "string", "description": "Station id, or empty."},
             "district": {"type": "string", "description": "District name, or empty."},
             "days": {"type": "integer", "description": "1 to 30."}}),
    _strict("get_satellite_check", "The Sentinel-1 radar check already made for this report at a station, if any: water outside "
            "the permanent-water reference, pass dates and the gauge category.",
            {"station_id": STATION}),
    _strict("search_documents", "Search FFD bulletins, Federal Flood Commission daily reports, NDMA/PDMA plans, flood classification "
            "limits, FloodGuard method notes and past FloodGuard reports. Returns passages you can cite by their source.",
            {"query": {"type": "string", "description": "Keywords: place names, river, and the topic (e.g. 'Kalabagh Tarbela release')."}}),
]
SUBMIT_TOOL = _strict(
    "submit_findings",
    "Submit your findings once, at the end. Every evidence item and explanation must cite references you received from tools: "
    "T-numbers from data tools, document sources, or web page URLs. You cannot set or change any measured value, category or status.",
    {"summary": {"type": "string", "description": "Two or three sentences for a supervisor."},
     "evidence": {"type": "array", "description": "What the data and documents show (most important first).", "items": {
         "type": "object", "additionalProperties": False, "required": ["finding", "relation", "refs"], "properties": {
             "finding": {"type": "string", "description": "One or two sentences."},
             "relation": {"type": "string", "enum": ["supports", "weakens", "context"],
                          "description": "supports: makes the flagged signal more credible or concerning; weakens: suggests it is less "
                                         "concerning (e.g. normal operation, data issue); context: background."},
             "refs": {"type": "array", "items": {"type": "string"}}}}},
     "possible_explanations": {"type": "array", "items": {
         "type": "object", "additionalProperties": False, "required": ["explanation", "likelihood", "refs"], "properties": {
             "explanation": {"type": "string"},
             "likelihood": {"type": "string", "enum": ["more likely", "possible", "less likely"]},
             "refs": {"type": "array", "items": {"type": "string"}}}}},
     "uncertainty": {"type": "object", "additionalProperties": False, "required": ["level", "reasons"], "properties": {
         "level": {"type": "string", "enum": ["low", "medium", "high"]},
         "reasons": {"type": "array", "items": {"type": "string"}}}},
     "reviewer_checks": {"type": "array", "description": "What a person should verify before relying on this.", "items": {"type": "string"}}},
)


def _pkt(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(PKT).strftime("%d %b %H:%M")


def _thin(points: list) -> list:
    if len(points) <= MAX_POINTS:
        return points
    step = len(points) / MAX_POINTS
    return [points[int(i * step)] for i in range(MAX_POINTS - 1)] + [points[-1]]


class AgentTools:
    def __init__(self, report: dict, kb: KnowledgeBase, api_base: str, exclude_doc_ids: set[str],
                 db_path=ROOT / "floodguard.db", max_calls: int = 12):
        self.report, self.kb, self.api_base = report, kb, api_base.rstrip("/")
        self.exclude_doc_ids, self.db_path, self.max_calls = exclude_doc_ids, db_path, max_calls
        self.calls = 0
        self.refs: dict[str, dict] = {}          # T-refs issued by data tools
        self.doc_refs: dict[str, dict] = {}      # document sources returned
        self.log: list[dict] = []
        self._cache: dict[str, object] = {}
        self.findings: dict | None = None
        self.stations = {s["id"]: s for s in report.get("all_stations") or report.get("stations") or []}

    # ------------------------------------------------------------------ plumbing
    def _db(self) -> sqlite3.Connection:
        con = sqlite3.connect(f"file:{self.db_path.as_posix()}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        return con

    def _get(self, path: str, **params):
        key = path + json.dumps(params, sort_keys=True)
        if key not in self._cache:
            response = httpx.get(f"{self.api_base}{path}", params=params or None, timeout=30)
            response.raise_for_status()
            self._cache[key] = response.json()
        return self._cache[key]

    def _issue(self, tool: str, args: dict, label: str, payload: dict) -> str:
        ref = f"T{len(self.refs) + 1}"
        self.refs[ref] = {"ref": ref, "kind": "data", "tool": tool, "args": args, "label": label}
        return json.dumps({"ref": ref, **payload}, ensure_ascii=False, default=str)

    @staticmethod
    def _station(station_id: str) -> str:
        sid = (station_id or "").strip().upper().replace(" ", "_").replace(".", "")
        by_name = {name.upper().replace(" ", "_"): key for key, name in STATION_NAMES.items()}
        sid = sid if sid in STATION_NAMES else by_name.get(sid, sid)
        if sid not in STATION_NAMES:
            raise ValueError(f"Unknown station id '{station_id}'. Valid ids: {', '.join(STATION_NAMES)}.")
        return sid

    # ------------------------------------------------------------------ dispatch
    def execute(self, name: str, args: dict):
        """Run one tool. Returns tool_result content (str or list of blocks) and whether it is an error."""
        if name == "submit_findings":
            self.findings = args
            self.log.append({"tool": name, "args": {}, "result": "Findings recorded"})
            return "Findings recorded. You are done.", False
        self.calls += 1
        if self.calls > self.max_calls:
            self.log.append({"tool": name, "args": args, "result": "Budget used"})
            return "Tool budget used up. Call submit_findings now with the evidence you already have.", True
        try:
            handler = getattr(self, f"_t_{name}")
        except AttributeError:
            return f"Unknown tool {name}.", True
        try:
            result = handler(**args)
        except ValueError as exc:
            self.log.append({"tool": name, "args": args, "result": f"Error: {exc}"})
            return f"Error: {exc}", True
        except (httpx.HTTPError, sqlite3.Error) as exc:
            self.log.append({"tool": name, "args": args, "result": f"Data source unavailable: {type(exc).__name__}"})
            return f"Data source unavailable ({type(exc).__name__}). Continue without it.", True
        summary = result if isinstance(result, str) else f"{len(result)} document passages"
        self.log.append({"tool": name, "args": args, "result": summary[:400]})
        return result, False

    # ------------------------------------------------------------------ tools
    def _t_get_station_readings(self, station_id: str, days: int):
        sid = self._station(station_id)
        days = max(1, min(int(days or 7), 10))
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        with self._db() as db:
            discharge = [(r["recorded_at"], r["discharge_cumecs"]) for r in db.execute(
                "select recorded_at, discharge_cumecs from river_gauge_observations where station_id = ? and recorded_at >= ? "
                "order by recorded_at", (sid, cutoff))]
            typed: dict[str, list] = {}
            for r in db.execute("select gauge, recorded_at, discharge_cumecs from typed_river_gauge_observations "
                                "where station_id = ? and recorded_at >= ? order by recorded_at", (sid, cutoff)):
                typed.setdefault(r["gauge"].lower(), []).append((r["recorded_at"], r["discharge_cumecs"]))
        values = [v for _t, v in discharge if v is not None]
        s = self.stations.get(sid, {})
        payload = {
            "station": STATION_NAMES[sid], "unit": "cumecs", "days": days,
            "source": "FFD readings stored by FloodGuard (database, read-only)",
            "report_values": {"discharge": s.get("discharge"), "inflow": s.get("inflow"), "outflow": s.get("outflow"),
                              "change_24h": s.get("change_24h"), "category": s.get("category"), "observed_at": s.get("observed_at"),
                              "simulated_in_this_report": bool(s.get("simulated"))},
            "discharge_series": [[_pkt(t), round(v, 1) if v is not None else None] for t, v in _thin(discharge)],
            "inflow_series": [[_pkt(t), round(v, 1) if v is not None else None] for t, v in _thin(typed.get("inflow", []))],
            "outflow_series": [[_pkt(t), round(v, 1) if v is not None else None] for t, v in _thin(typed.get("outflow", []))],
            "min": round(min(values), 1) if values else None, "max": round(max(values), 1) if values else None,
            "readings": len(discharge),
        }
        return self._issue("get_station_readings", {"station_id": sid, "days": days}, f"Station readings, {STATION_NAMES[sid]} ({days} days)", payload)

    def _t_get_upstream_context(self, station_id: str):
        sid = self._station(station_id)
        ids = list(dict.fromkeys(upstream_ids(sid) + TRIBUTARIES.get(sid, [])))
        inout = {r["name"]: r for r in self.report.get("inout") or []}
        rows = []
        for uid in ids:
            s = self.stations.get(uid, {})
            row = {"station": STATION_NAMES.get(uid, uid), "id": uid, "discharge": s.get("discharge"), "inflow": s.get("inflow"),
                   "outflow": s.get("outflow"), "change_24h": s.get("change_24h"), "category": s.get("category"),
                   "observed_at": s.get("observed_at"), "travel_hours_to_next": None}
            io = inout.get(STATION_NAMES.get(uid, uid))
            if io:
                row["operation"] = io.get("reading")
                row["net_inflow_minus_outflow"] = io.get("net")
            for chain in RIVER_CHAINS.values():
                if uid in chain and chain.index(uid) + 1 < len(chain):
                    row["travel_hours_to_next"] = TRAVEL_HOURS.get((uid, chain[chain.index(uid) + 1]))
            rows.append(row)
        payload = {"station": STATION_NAMES[sid], "upstream": rows, "unit": "cumecs",
                   "source": "FFD readings in this report (inflow/outflow per site) and FloodGuard indicative travel times"}
        return self._issue("get_upstream_context", {"station_id": sid}, f"Upstream stations and releases above {STATION_NAMES[sid]}", payload)

    def _t_get_forecasts(self, station_id: str):
        sid = self._station(station_id)
        name = STATION_NAMES[sid]
        station_fc = next((f for f in self.report.get("forecasts") or [] if f.get("name") == name), None)
        watch = []
        for u in (self.report.get("upstream") or {}).get("stations") or []:
            if name.lower() not in u.get("name", "").lower():
                continue
            watch.append({"point": u["name"], "low_flood_threshold": u.get("low_flood_threshold"),
                          "threshold_kind": u.get("low_flood_threshold_kind"), "agreement_pct": u.get("agreement_pct"),
                          "gap_cumecs": u.get("gap_cumecs"), "providers_agree": u.get("agree"),
                          "providers": [{"provider": p["provider"], "peak": p.get("peak"), "peak_at": p.get("peak_at"),
                                         "current": p.get("current"),
                                         "series": [[x["time"], x["value"]] for x in _thin(p.get("series") or [])]}
                                        for p in u.get("providers") or []],
                          "flood_type_signals": u.get("signals")})
        seasonal = self.report.get("seasonal") if sid == "MARALA" and (self.report.get("seasonal") or {}).get("available") else None
        payload = {"station": name, "unit": "cumecs", "station_forecast": station_fc, "upstream_watch": watch,
                   "seasonal_outlook": seasonal,
                   "source": "GloFAS and GEOGloWS modeled discharge (Flood API) and the FFD official forecast text, as in this report"}
        return self._issue("get_forecasts", {"station_id": sid}, f"Forecasts for {name}", payload)

    def _districts(self) -> list[dict]:
        national = self._get("/gis/national-risk")
        return [f for f in national.get("features", []) if f.get("properties")]

    def _t_get_rainfall(self, station_id: str, district: str):
        features = self._districts()
        rows = []
        if station_id:
            sid = self._station(station_id)
            point = Point(STATION_COORDS[sid])
            near = []
            for f in features:
                if not f.get("geometry"):
                    continue
                distance = shape(f["geometry"]).distance(point)
                if distance <= 0.45:
                    near.append((distance, f["properties"]))
            chosen = [p for _d, p in sorted(near, key=lambda x: x[0])[:8]]
            label = f"Rainfall near {STATION_NAMES[sid]}"
            args = {"station_id": sid}
        elif district:
            chosen = [f["properties"] for f in features if district.lower() in f["properties"].get("district_name", "").lower()][:5]
            label = f"Rainfall in {district}"
            args = {"district": district}
        else:
            raise ValueError("Give a station_id or a district.")
        for p in chosen:
            rows.append({"district": p.get("district_name"), "rain_last_24h_mm": p.get("rainfall_24h_mm"),
                         "rain_next_24h_mm": p.get("forecast_rainfall_24h_mm"), "temperature_c": p.get("temperature_c"),
                         "soil_moisture_percent": p.get("soil_moisture_percent"),
                         "screening_risk_pct": round((p.get("risk_probability") or 0) * 100)})
        payload = {"districts": rows, "source": "Open-Meteo weather through FloodGuard's district layer (Flood API); screening risk is an estimate"}
        return self._issue("get_rainfall", args, label, payload)

    def _t_get_incidents_and_reports(self, station_id: str, district: str, days: int):
        days = max(1, min(int(days or 7), 30))
        since = datetime.now(timezone.utc) - timedelta(days=days)
        sid = self._station(station_id) if station_id else None
        names = {n.lower() for n in ([STATION_NAMES[sid]] if sid else [])} | ({district.lower()} if district else set())
        point = Point(STATION_COORDS[sid]) if sid else None

        def near(location_id) -> bool:
            if sid and location_id == sid:
                return True
            loc = LOCATIONS.get(location_id)
            if not loc:
                return False
            if loc.name.lower() in names or any(n in loc.name.lower() for n in names):
                return True
            return bool(point and Point(loc.longitude, loc.latitude).distance(point) <= 0.5)

        def recent(ts) -> bool:
            try:
                moment = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            except ValueError:
                return True
            return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)) >= since

        alerts = [{"time": _pkt(a.get("timestamp")), "station": (a.get("event_metadata") or {}).get("station_name") or a.get("location_id"),
                   "message": a.get("message"),
                   "simulated": (a.get("event_metadata") or {}).get("value_type") == "simulated" or str((a.get("event_metadata") or {}).get("source", "")).startswith("SIMULATED")}
                  for a in self._get("/alerts") if recent(a.get("timestamp")) and
                  (near(a.get("location_id")) or any(n in str((a.get("event_metadata") or {}).get("station_name", "")).lower() for n in names))][:10]
        incidents = [{"id": i["id"], "type": i.get("type"), "status": i.get("status"), "severity": i.get("severity"),
                      "description": (i.get("description") or "")[:240], "created": _pkt(i.get("created_at")),
                      "simulated": str(i.get("source", "")).startswith("SIMULATED")}
                     for i in self._get("/incidents") if recent(i.get("created_at")) and near(i.get("location_id"))][:10]
        reports = [{"id": r["id"], "location": LOCATIONS[r["location_id"]].name if r.get("location_id") in LOCATIONS else r.get("location_id"),
                    "description": (r.get("description") or "")[:240], "verification": r.get("verification_status"),
                    "status": r.get("report_status"), "water_depth_cm": r.get("reported_water_depth_cm"), "time": _pkt(r.get("timestamp"))}
                   for r in self._get("/citizen-reports") if recent(r.get("timestamp")) and
                   (near(r.get("location_id")) or (point and r.get("longitude") is not None and Point(r["longitude"], r["latitude"]).distance(point) <= 0.5))][:10]
        payload = {"days": days, "alerts": alerts, "incidents": incidents, "citizen_reports": reports,
                   "source": "FloodGuard alerts, incidents and citizen reports (API, read-only); citizen reports are unverified unless marked"}
        label = f"Alerts, incidents and citizen reports near {STATION_NAMES[sid] if sid else district} ({days} days)"
        return self._issue("get_incidents_and_reports", {"station_id": sid or "", "district": district, "days": days}, label, payload)

    def _t_get_satellite_check(self, station_id: str):
        sid = self._station(station_id)
        checks = (self.report.get("satellite") or {}).get("checks") or []
        found = [c for c in checks if c.get("station_id") == sid]
        keep = ("location", "result", "potential_flood_area_km2", "pre_date", "during_date", "gauge_category", "category",
                "triggered_by_simulation", "why", "reason", "error")
        payload = {"station": STATION_NAMES[sid], "checks": [{k: c.get(k) for k in keep if c.get(k) is not None} for c in found],
                   "note": None if found else "No satellite check was made at this station for this report.",
                   "source": "Sentinel-1 radar (Microsoft Planetary Computer), compared with JRC permanent water"}
        return self._issue("get_satellite_check", {"station_id": sid}, f"Satellite check at {STATION_NAMES[sid]}", payload)

    def _t_search_documents(self, query: str):
        hits = self.kb.search(query_words(query), limit=5, per_doc=2, exclude_doc_ids=self.exclude_doc_ids)
        if not hits:
            return "No documents matched this query. Try other place names or topic words."
        for h in hits:
            self.doc_refs[h.source] = {"ref": h.source, "kind": "document", "label": h.title, "url": h.url,
                                       "doc_kind": h.kind, "published": h.published}
        return [search_result_block(h, citations=True) for h in hits]
