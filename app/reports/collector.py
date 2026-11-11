"""Shared data collection for FloodGuard reports (daily report and flood event reports).

PortalCollector reads the running portal (API + database) and returns plain dicts
for each topic: stations, forecasts, districts, operations, satellite checks,
exposure/population impact and portal snapshots. Every item gets data-source
labels through self.src (see docs/reports/daily_report_spec.md, rule 2).
Report builders subclass it and decide which topics to collect and how to summarize.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from shapely.geometry import Point, shape

from app.gis.river_stations import RIVER_CHAINS, STATIONS
from app.locations import LOCATIONS

PKT = timezone(timedelta(hours=5))
ROOT = Path(__file__).resolve().parents[2]
STATION_COORDS = {sid: (lon, lat) for sid, _name, _river, lat, lon, _label in STATIONS}
STATION_NAMES = {sid: name for sid, name, *_ in STATIONS}
DAMS = {"TARBELA", "MANGLA"}

# Indicative travel times (hours) between consecutive stations. FloodGuard estimates,
# to be calibrated against FFD peak timings.
TRAVEL_HOURS = {
    ("TARBELA", "KALABAGH"): 12, ("KALABAGH", "CHASHMA"): 6, ("CHASHMA", "TAUNSA"): 36,
    ("TAUNSA", "GUDDU"): 48, ("GUDDU", "SUKKUR"): 18, ("SUKKUR", "KOTRI"): 72,
    ("MANGLA", "RASUL"): 12, ("JASSAR", "SHAHDARA"): 24, ("SHAHDARA", "BALLOKI"): 18,
    ("BALLOKI", "SIDHNAI"): 72, ("MARALA", "KHANKI"): 7, ("KHANKI", "QADIRABAD"): 7,
    ("QADIRABAD", "TRIMMU"): 28, ("TRIMMU", "PANJNAD"): 36, ("GANDA_SINGH_WALA", "SULEMANKI"): 36,
    ("SULEMANKI", "ISLAM"): 48, ("ISLAM", "PANJNAD"): 72,
}
# Preview districts available in the portal's Simulation > Flood spread & population view
# (frontend/src/components/tenYearPreviewData.ts): id -> (lon, lat).
PREVIEW_AREAS = {
    "jhang": (72.3187, 31.2681), "multan": (71.5249, 30.1575), "lahore": (74.3587, 31.5204),
    "rawalpindi": (73.0169, 33.5651), "charsadda": (71.731, 34.148), "sukkur": (68.8574, 27.7244),
    "dadu": (67.7769, 26.7303), "badin": (68.8384, 24.6559),
}
# Stations inside a prepared exposure/population region (exposure pilots in data/).
EXPOSURE_REGIONS = {"TRIMMU": "trimmu_jhang", "BALLOKI": "balloki", "SHAHDARA": "balloki"}


def is_sharp_rise(change: float | None, discharge: float | None) -> bool:
    """Sharp rise rule: more than 50 cumecs and more than 10% in 24 h (flood wave and report flags)."""
    return bool(change and discharge and change > 50 and change / max(discharge - change, 1) > 0.10)


def nearest_preview_area(station_id: str, max_km: float = 150) -> str | None:
    lon, lat = STATION_COORDS[station_id]
    best = min(PREVIEW_AREAS.items(), key=lambda kv: (kv[1][0] - lon) ** 2 + (kv[1][1] - lat) ** 2)
    km = (((best[1][0] - lon) * 95) ** 2 + ((best[1][1] - lat) * 111) ** 2) ** 0.5
    return best[0] if km <= max_km else None


# ---------------------------------------------------------------- snapshot recipes
# A recipe opens one portal screen, sets it up for a specific case and captures
# one or more elements (not whole pages). Only flood-relevant visuals are captured:
# model prediction graphs, upstream API graphs for selected stations, flood extent +
# population results, and the simulated flood spread (2D and 3D population view).
def shot_model_graphs(section: str, simulated: bool) -> dict:
    return {"name": "Model prediction graphs", "steps": [
        ("nav", "Predictive Risk Views"), ("pause", 2500),
        ("capture", {"key": "model-riverine", "view": "Model prediction: riverine short-term", "section": section,
                     "target": ".multiview-card >> nth=0", "sources": ["sim"] if simulated else ["ml"],
                     "caption": "Placeholder model output (illustrative values)" if simulated else "FloodGuard model output"})]}


def shot_upstream(station_name: str, section: str) -> dict:
    return {"name": f"Upstream forecast graph: {station_name}", "steps": [
        ("nav", "Upstream Source Flood Watch"), ("click", ".source-station-selector button", station_name), ("pause", 2000),
        ("capture", {"key": f"upstream-{station_name}", "view": f"GloFAS vs GEOGloWS forecast: {station_name}", "section": section,
                     "target": ".source-tab-body", "max_height": 620, "sources": ["api"],
                     "caption": "Modeled discharge from both providers against the low-flood threshold"})]}


def shot_population(region: str, flood_source: str, section: str, sources: list[str], geojson_path: str | None = None) -> dict:
    """flood_source "provided" uploads geojson_path (e.g. a real satellite water outline) into the portal."""
    label = {"sample": "synthetic test extent", "historical_reference": "historical satellite water reference",
             "provided": "satellite-detected water"}.get(flood_source, flood_source)
    upload = [("upload", "Flood polygon GeoJSON", geojson_path), ("pause", 1000)] if flood_source == "provided" else []
    return {"name": f"Population impact: {region}", "steps": [
        ("nav", "GIS Operations"), ("select", "Population study region", region), ("select", "Population flood source", flood_source),
        *upload, ("role_click", "button", "Calculate population"), ("wait", ".population-cards", 240000), ("pause", 6000),
        ("capture", {"key": f"population-{region}", "view": f"Flood-affected population ({label})", "section": section,
                     "target": ".population-analysis", "max_height": 640, "sources": sources,
                     "caption": "WorldPop estimate on the flood extent; partial coverage is a lower bound"}),
        ("capture", {"key": f"extent-{region}", "view": f"Flood extent over population density ({label})", "section": section,
                     "target": ".national-map-panel", "sources": sources,
                     "caption": "Blue: flood extent. Yellow to red: population density. Pink: affected settlements"})]}


def shot_simulation_spread(area: str, section: str, highest: bool = False) -> dict:
    """highest=True shows the widest example spread (level 5), used for High flood and above."""
    level = [("click", ".outlook-flood-presets button", "Highest flood scenario"), ("pause", 3000)] if highest else []
    return {"name": f"Simulated flood spread: {area}", "steps": [
        ("nav", "Simulation"), ("role_click", "tab", "Flood spread & population"), ("pause", 3000),
        ("select", "Simulation preview district", area), ("pause", 5000),
        ("role_click", "button", "2D comparison"), ("pause", 4000), *level,
        ("capture", {"key": f"spread2d-{area}", "view": f"Simulated flood spread vs baseline population: {area.title()}", "section": section,
                     "target": ".outlook-map-pair", "sources": ["sim", "est"],
                     "caption": f"Hypothetical river spread (level {5 if highest else 2} of 5) beside the WorldPop 2025 baseline"}),
        ("role_click", "button", "Cinematic 3D"), ("pause", 5000), ("role_click", "button", "Population focus"), ("pause", 6000),
        ("capture", {"key": f"spread3d-{area}", "view": f"3D population exposure (simulated spread): {area.title()}", "section": section,
                     "target": "[aria-label='Cinematic region map']", "sources": ["sim", "est"],
                     "caption": "Column height = population density; blue columns intersect the simulated footprint"})]}



def _iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _pkt(value: datetime | None) -> str | None:
    return value.astimezone(PKT).strftime("%d %b %H:%M") if value else None


class Provenance:
    """Counts data-source labels as items are added, for section 00."""

    def __init__(self):
        self.counts: Counter[str] = Counter()

    def __call__(self, *keys: str) -> list[str]:
        for key in keys:
            self.counts[key] += 1
        return list(keys)


class PortalCollector:
    def __init__(self, api_base: str, db_path: Path = ROOT / "floodguard.db", generated_at: datetime | None = None,
                 run_satellite: bool = True, capture_snapshots: bool = True, frontend_url: str = "http://127.0.0.1:3000"):
        self.api = httpx.Client(base_url=api_base.rstrip("/"), timeout=180)
        self.db_path = db_path
        self.generated_at = generated_at or datetime.now(timezone.utc)
        # Default period: the 24 h before generation. Report builders may override.
        self.period_end = self.generated_at
        self.period_start = self.period_end - timedelta(days=1)
        self.run_satellite = run_satellite
        self.capture_snapshots = capture_snapshots
        self.frontend_url = frontend_url
        self.src = Provenance()

    # ------------------------------------------------------------------ helpers
    def _get(self, path: str, **params) -> Any:
        response = self.api.get(path, params=params or None)
        response.raise_for_status()
        return response.json()

    def _try(self, label: str, func, *args, **kwargs):
        try:
            return func(*args, **kwargs), None
        except Exception as exc:  # report every failure instead of hiding it
            return None, f"{label}: {type(exc).__name__}: {str(exc)[:160]}"

    def _db(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _in_period(self, value: str | None) -> bool:
        moment = _iso(value)
        return bool(moment and self.period_start <= moment < self.period_end)

    # ---------------------------------------------------------------- topics
    def _history(self) -> dict[str, list[tuple[datetime, float]]]:
        cutoff = (self.period_end - timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S")
        rows: dict[str, list] = {}
        with self._db() as db:
            for row in db.execute("select station_id, recorded_at, discharge_cumecs from river_gauge_observations "
                                  "where recorded_at >= ? order by recorded_at", (cutoff,)):
                rows.setdefault(row["station_id"], []).append((_iso(row["recorded_at"]), row["discharge_cumecs"]))
        return rows

    def _stations(self, monitoring: dict) -> list[dict]:
        history = self._history()
        by_id = {s["id"]: s for s in monitoring.get("stations", [])}
        result = []
        for river, chain in RIVER_CHAINS.items():
            for sid in chain:
                if river == "Sutlej" and sid == "PANJNAD":
                    continue  # Panjnad is listed once, under its own river
                s = by_id.get(sid)
                gauges = {g["gauge"]: g["value"] for g in (s or {}).get("gauge_readings", [])}
                observed = _iso((s or {}).get("observed_at"))
                age = (self.generated_at - observed).total_seconds() / 3600 if observed else None
                series = history.get(sid, [])
                previous = [v for t, v in series if observed and timedelta(hours=18) <= observed - t <= timedelta(hours=30)]
                current = (s or {}).get("current_discharge_cumecs")
                change = round(current - previous[-1], 2) if previous and current is not None else None
                values = [v for _, v in series][-7:]
                rising = sum(1 for a, b in zip(values, values[1:]) if b > a) if len(values) >= 3 else None
                forecast = (s or {}).get("forecast_discharge_cumecs")
                mismatch = bool(current and current > 10 and forecast is not None and
                                (forecast < 0.1 * current or forecast > 10 * current))
                result.append({
                    "id": sid, "name": STATION_NAMES.get(sid, sid), "river": "Panjnad" if sid == "PANJNAD" else river,
                    "available": s is not None and current is not None,
                    "discharge": current, "inflow": gauges.get("INFLOW"), "outflow": gauges.get("OUTFLOW"),
                    "change_24h": change, "change_source": "FFD observed, previous stored reading" if change is not None else None,
                    "history": [{"time": t.isoformat(), "value": v} for t, v in series][-7:], "rising_days": rising,
                    "category": (s or {}).get("flood_category", "Unavailable"),
                    "observed_at": _pkt(observed), "age_hours": round(age, 1) if age is not None else None,
                    "stale": age is None or age > 24,
                    "level": (s or {}).get("observed_level_value"), "level_unit": (s or {}).get("observed_level_unit"),
                    "forecast": forecast, "forecast_valid": (s or {}).get("forecast_valid_at"),
                    "peak": (s or {}).get("expected_peak_cumecs"), "peak_at": (s or {}).get("expected_peak_at"),
                    "official_text": (s or {}).get("official_forecast_text"), "forecast_mismatch": mismatch,
                    "pct_normal": None, "sources": self.src("obs") if s else [],
                })
        return result

    def _wave(self, stations: list[dict]) -> dict:
        by_id = {s["id"]: s for s in stations}
        rising = [s for s in stations if is_sharp_rise(s["change_24h"], s["discharge"])]
        waves = []
        for s in rising:
            for river, chain in RIVER_CHAINS.items():
                if s["id"] not in chain:
                    continue
                hours, path = 0, [{"id": s["id"], "name": s["name"], "hours": 0}]
                for a, b in zip(chain[chain.index(s["id"]):], chain[chain.index(s["id"]) + 1:]):
                    hours += TRAVEL_HOURS.get((a, b), 0)
                    path.append({"id": b, "name": by_id.get(b, {}).get("name", b), "hours": hours})
                if len(path) > 1:
                    waves.append({"origin": s["name"], "river": river, "path": path, "sources": self.src("est")})
        return {"waves": waves, "rule": "A station counts as rising when it gains more than 10% and more than 50 cumecs in 24 h."}

    def _inout(self, stations: list[dict]) -> list[dict]:
        rows = []
        for s in stations:
            if s["inflow"] is None or s["outflow"] is None:
                continue
            net = s["inflow"] - s["outflow"]
            scale = max(s["inflow"], s["outflow"], 1)
            if abs(net) < 0.05 * scale:
                reading = "Balanced"
            elif net > 0:
                reading = "Storing" if s["id"] in DAMS else "Inflow above outflow (canal withdrawals or pond storage)"
            else:
                reading = "Releasing more than inflow"
            rows.append({"name": s["name"], "inflow": s["inflow"], "outflow": s["outflow"], "net": round(net, 2),
                         "reading": reading, "sources": self.src("obs")})
        return rows

    def _forecasts(self, stations: list[dict]) -> list[dict]:
        rows = []
        for s in stations:
            sources = []
            if s["forecast"] is not None:
                sources += self.src("api")
            if s["official_text"]:
                sources += self.src("off")
            rows.append({"name": s["name"], "forecast": s["forecast"], "valid": s["forecast_valid"], "peak": s["peak"],
                         "peak_at": s["peak_at"], "official_text": s["official_text"], "mismatch": s["forecast_mismatch"],
                         "current": s["discharge"], "sources": sources})
        return rows

    def _upstream(self, payload: dict | None, error: str | None) -> dict:
        if not payload:
            return {"available": False, "reason": error or "No data"}
        rows = []
        for s in payload["stations"]:
            providers = [{"provider": p["provider"], "status": p["status"], "peak": p["peak_forecast_cumecs"],
                          "peak_at": p["peak_forecast_time"], "current": p["current_cumecs"],
                          "series": [{"time": x["time"][:10], "value": x["value"], "phase": x["phase"]} for x in p["series"]]}
                         for p in s["providers"]]
            peaks = [p["peak"] for p in providers if p["peak"] not in (None, 0)]
            diff = round(100 * (max(peaks) - min(peaks)) / max(peaks)) if len(peaks) >= 2 else None
            gap = max(peaks) - min(peaks) if len(peaks) >= 2 else 0
            # Disagreement needs both a relative (>25%) and an absolute (>100 cumecs) gap,
            # so tiny low-season flows do not raise false flags.
            stats = s.get("stats") or {}
            rows.append({"id": s.get("id"), "name": s["name"], "river": s["river"], "providers": providers,
                         "low_flood_threshold": stats.get("low_flood_threshold_cumecs"),
                         "low_flood_threshold_kind": stats.get("low_flood_threshold_kind"),
                         "agreement_pct": diff, "gap_cumecs": round(gap, 1), "agree": diff is not None and (diff <= 25 or gap <= 100),
                         "signals": [{"type": f["type"], "severity": f["severity"], "probability": f["probability"],
                                      "basis": f["basis"]} for f in s["flood_types"]],
                         "rain_max_mm": s["stats"].get("max_forecast_rain_mm"), "sources": self.src("api", "est")})
        return {"available": True, "stations": rows, "refresh_error": payload.get("refresh_error"),
                "cached_at": _pkt(_iso(payload.get("cached_at")))}

    def _models(self, points: list | None, error: str | None) -> dict:
        rows = []
        for location_id, location in LOCATIONS.items():
            risk, risk_error = self._try("flood risk", self._get, "/flood/risk", location_id=location_id)
            if risk:
                rows.append({"model": risk["model"], "target": location.name, "value": f"{round(risk['flood_probability'] * 100)}%",
                             "risk_class": risk["severity"], "status": "Operational (rule-based)" if risk["model_type"] == "rule_based" else risk["model_type"],
                             "sources": self.src("ml")})
        latest: dict[tuple, dict] = {}
        for p in points or []:
            key = (p["model_case"], p["target_id"])
            if key not in latest or p["issued_at"] > latest[key]["issued_at"]:
                latest[key] = p
        for p in latest.values():
            meta = p.get("point_metadata") or {}
            dummy = "dummy" in str(meta.get("model_status", "")) or "dummy" in str(meta.get("simulation_source", ""))
            rows.append({"model": p["model_name"], "target": p["target_name"], "value": f"{p['value']:g} {p['value_unit'].replace('_', ' ')}",
                         "risk_class": p["risk_class"], "status": meta.get("model_status", "unknown").replace("_", " "),
                         "sources": self.src("sim" if dummy else "ml")})
        return {"rows": rows, "error": error}

    def _seasonal(self, payload: dict | None, error: str | None) -> dict:
        if not payload:
            return {"available": False, "reason": error or "No data"}
        outlook = payload.get("current_provider_outlook") or {}
        observed = {m["month"]: m["flow_mean_cumecs"] for m in (payload.get("recent_history") or {}).get("monthly", [])
                    if m.get("flow_mean_cumecs") is not None}
        month = self.period_end.astimezone(PKT).strftime("%Y-%m")
        rows = []
        for f in outlook.get("forecast", []):
            if f["target_month"] < month or len(rows) >= 4:
                continue
            stats = f["monthly_mean_discharge_cumecs"]
            same = [v for k, v in observed.items() if k[5:] == f["target_month"][5:]]
            rows.append({"month": f["target_month"], "mean": stats["mean"], "p25": stats["p25"], "p75": stats["p75"],
                         "observed_normal": sum(same) / len(same) if same else None})
        self.src("api")
        return {"available": bool(rows), "station": "Marala (Chenab)", "rows": rows, "source": outlook.get("forecast_source"),
                "issued": outlook.get("forecast_issue_start"), "reason": None if rows else "No outlook months cover this period",
                "note": "Modeled monthly mean from the provider. The p25–p75 band is not a calibrated interval."}

    def _rainfall(self, national: dict | None, error: str | None) -> dict:
        if not national:
            return {"available": False, "reason": error or "No data"}
        props = [f["properties"] for f in national["features"]]
        top = sorted(props, key=lambda p: max(p.get("rainfall_24h_mm") or 0, p.get("forecast_rainfall_24h_mm") or 0), reverse=True)[:8]
        north = [p for p in props if p.get("latitude", 0) >= 35]
        self.src("api")
        return {"available": True,
                "top": [{"district": p["district_name"], "observed": p.get("rainfall_24h_mm"), "forecast": p.get("forecast_rainfall_24h_mm")} for p in top],
                "melt": [{"district": p["district_name"], "temp": p.get("temperature_c")} for p in sorted(north, key=lambda p: -(p.get("temperature_c") or -99))[:5]],
                "melt_note": "The portal has no temperature normals yet, so the heat and snowmelt flag (temperature 4 °C or more above normal while flow rises) cannot be calculated. Current temperatures in northern districts are shown."}

    def _districts(self, national: dict | None, stations: list[dict], reports: list, incidents: list) -> dict:
        if not national:
            return {"available": False, "reason": "District risk layer unavailable"}
        features = national["features"]
        rising_points = [Point(STATION_COORDS[s["id"]]) for s in stations if s["change_24h"] and s["change_24h"] > 0 and s["id"] in STATION_COORDS]
        open_reports = [(Point(r["longitude"], r["latitude"]), r) for r in reports if r.get("report_status") != "CLOSED"]
        open_incidents = []
        for i in incidents:
            if i.get("status") in ("RESOLVED", "CLOSED"):
                continue
            coords = STATION_COORDS.get(i["location_id"]) or ((LOCATIONS[i["location_id"]].longitude, LOCATIONS[i["location_id"]].latitude)
                                                              if i["location_id"] in LOCATIONS else None)
            if coords:
                open_incidents.append((Point(coords), i))
        rows, bands = [], Counter()
        for f in features:
            p = f["properties"]
            prob = p.get("risk_probability") or 0
            band = "High" if prob >= 0.6 else "Medium" if prob >= 0.3 else "Low"
            bands[band] += 1
            geom = shape(f["geometry"]) if f.get("geometry") else None
            signals = {
                "high_risk": prob >= 0.6,
                "station_rising": bool(geom and any(geom.contains(pt) for pt in rising_points)),
                "citizen_reports": sum(1 for pt, _ in open_reports if geom and geom.contains(pt)),
                "open_incident": [i["id"] for pt, i in open_incidents if geom and geom.contains(pt)],
                "simulated_incident": any(i.get("source", "").startswith("SIMULATED") for pt, i in open_incidents if geom and geom.contains(pt)),
            }
            count = sum(bool(v) for k, v in signals.items() if k != "simulated_incident")
            rows.append({"district": p["district_name"], "risk": round(prob * 100), "severity": p.get("severity"),
                         "factors": p.get("top_risk_factors", []), "signals": signals, "signal_count": count,
                         "lat": p.get("latitude"), "lon": p.get("longitude")})
        rows.sort(key=lambda r: (r["signal_count"], r["risk"]), reverse=True)
        self.src("api", "est")
        return {"available": True, "total": len(features), "bands": dict(bands),
                "top_risk": sorted(rows, key=lambda r: -r["risk"])[:10],
                "multi_signal": [r for r in rows if r["signal_count"] >= 1][:10]}

    def _operations(self, alerts: list, incidents: list, reports: list) -> dict:
        now = self.generated_at

        def age(ts):
            moment = _iso(ts)
            return round((now - moment).total_seconds() / 3600, 1) if moment else None

        alert_rows = []
        for a in alerts:
            meta = a.get("event_metadata") or {}
            simulated = meta.get("value_type") == "simulated" or str(meta.get("source", "")).startswith("SIMULATED")
            alert_rows.append({"id": a["id"], "time": _pkt(_iso(a["timestamp"])), "location": meta.get("station_name") or a.get("location_id"),
                               "message": a["message"], "severity": meta.get("severity", "—"),
                               "approval": meta.get("approval_status", "—"), "age_hours": age(a["timestamp"]),
                               "new": self._in_period(a["timestamp"]), "sources": self.src("sim" if simulated else "obs")})
        incident_rows = []
        for i in incidents:
            simulated = str(i.get("source", "")).startswith("SIMULATED")
            incident_rows.append({"id": i["id"], "type": i["type"], "location": STATION_NAMES.get(i["location_id"], i["location_id"]),
                                  "severity": i["severity"], "status": i["status"], "description": i["description"],
                                  "age_hours": age(i["created_at"]), "new": self._in_period(i["created_at"]),
                                  "sources": self.src("sim" if simulated else "obs")})
        report_rows = []
        for r in reports:
            report_rows.append({"id": r["id"], "location": LOCATIONS[r["location_id"]].name if r["location_id"] in LOCATIONS else r["location_id"],
                                "description": r["description"], "verification": r["verification_status"], "status": r["report_status"],
                                "important": r["is_important"], "depth_cm": r.get("reported_water_depth_cm"),
                                "age_hours": age(r["timestamp"]), "new": self._in_period(r["timestamp"]), "sources": self.src("obs")})

        def counts(rows, open_test):
            return {"new": sum(r["new"] for r in rows), "open": sum(open_test(r) for r in rows), "total": len(rows)}

        pending_alerts = [r["age_hours"] for r in alert_rows if r["approval"] == "pending" and r["age_hours"] is not None]
        pending_reports = [r["age_hours"] for r in report_rows if r["verification"] == "PENDING" and r["age_hours"] is not None]
        open_incidents = [r["age_hours"] for r in incident_rows if r["status"] not in ("RESOLVED", "CLOSED") and r["age_hours"] is not None]
        return {
            "alerts": alert_rows, "incidents": incident_rows, "reports": report_rows,
            "counts": {"alerts": counts(alert_rows, lambda r: r["approval"] == "pending"),
                       "incidents": counts(incident_rows, lambda r: r["status"] not in ("RESOLVED", "CLOSED")),
                       "reports": counts(report_rows, lambda r: r["status"] != "CLOSED")},
            "waiting": [
                {"item": "Oldest alert awaiting approval", "hours": max(pending_alerts) if pending_alerts else None, "target": 0.5},
                {"item": "Oldest citizen report awaiting verification", "hours": max(pending_reports) if pending_reports else None, "target": 4},
                {"item": "Oldest open incident", "hours": max(open_incidents) if open_incidents else None, "target": 24},
            ],
            "waiting_note": "Approval and verification timestamps are not stored yet, so the report shows how long the oldest item has been waiting instead of median response times.",
        }

    def _simulation_runs(self) -> list[dict]:
        rows = []
        with self._db() as db:
            for row in db.execute("select id, result, created_at from monitoring_simulation_runs order by created_at desc limit 10"):
                result = json.loads(row["result"])
                readings = result.get("readings", [])
                rows.append({"run_id": row["id"][:8].upper(), "name": result.get("name"), "station": result.get("station_name"),
                             "created": _pkt(_iso(row["created_at"])), "active_in_period": self._in_period(row["created_at"]),
                             "readings": len(readings), "max_value": max((r["value"] for r in readings), default=None),
                             "alerts": len(result.get("alerts", [])), "incidents": len(result.get("incidents", [])),
                             "sources": self.src("sim")})
        return rows

    # ----------------------------------------------------------- satellite + impact
    def _sar(self, lat: float, lon: float) -> dict:
        from app.services.sar_catalog_service import infer_at_location
        for attempt in range(4):  # Planetary Computer rate-limits signing requests (HTTP 429); back off and retry.
            try:
                result = infer_at_location(lat, lon)
                break
            except Exception as exc:
                if "429" not in str(exc) or attempt == 3:
                    raise
                time.sleep(30 * (attempt + 1))
        keep =("status", "potential_flood_area_km2", "water_area_km2", "excluded_permanent_water_area_km2", "analysis_area_km2",
                "during_date", "pre_date", "coordinates", "image_data_url", "permanent_water_image_data_url",
                "during_radar_image_data_url", "pre_radar_image_data_url", "limitation", "source", "model",
                "potential_flood_geojson")
        return {k: result.get(k) for k in keep}

    @staticmethod
    def _flood_request(region: str, flood_source: str, flood_extent: dict | None, flood_label: str | None) -> dict:
        request = {"region": region, "flood_source": flood_source}
        if flood_source == "provided":
            request["flood_extent"] = flood_extent
            request["flood_label"] = (flood_label or "Flood extent supplied by FloodGuard report")[:250]
        return request

    def _impact(self, region: str, flood_source: str, flood_extent: dict | None = None,
                flood_label: str | None = None, sources: list[str] | None = None) -> dict:
        """Exposure + population for a flood extent in a prepared exposure region.

        flood_source: "sample" (synthetic test polygon), "historical_reference", or
        "provided" (flood_extent GeoJSON, e.g. a real satellite water outline).
        """
        request = self._flood_request(region, flood_source, flood_extent, flood_label)
        exposure, exposure_error = self._try("exposure analysis", lambda: self.api.post(
            "/exposure/analyses", json=request).raise_for_status().json())
        result = {"region": region, "flood_source": flood_source, "exposure_error": exposure_error, "sources": sources or []}
        if not exposure:
            return result
        population = exposure["population"]
        infra = exposure["infrastructure"]
        result.update({
            "label": exposure["flood"]["label"], "area_km2": exposure["flood"].get("analyzed_extent_area_km2"),
            "people": population.get("estimated_exposed_population"),
            "counts": {name: {"count": infra.get(name, {}).get("affected_count"), "length_km": infra.get(name, {}).get("affected_length_km")}
                       for name in ("settlements", "buildings", "roads", "schools", "hospitals")},
            "warnings": exposure.get("warnings", []),
        })
        facilities = []
        for layer in ("hospitals", "schools", "settlements"):
            layer_data, _ = self._try(layer, self._get, f"/exposure/analyses/{region}/{exposure['analysis_id']}/layers/{layer}")
            for f in (layer_data or {}).get("features", [])[:8]:
                p = f.get("properties", {})
                facilities.append({"name": p.get("name") or p.get("name:en") or "Unnamed", "type": layer[:-1].title(),
                                   "detail": p.get("amenity") or p.get("place") or ""})
        result["facilities"] = facilities[:15]
        extent, _ = self._try("flood extent", self._get, f"/exposure/analyses/{region}/{exposure['analysis_id']}/layers/flood_extent")
        if extent and extent.get("features"):
            geom = shape(extent["features"][0]["geometry"])
            polygon = geom if geom.geom_type == "Polygon" else max(geom.geoms, key=lambda g: g.area)
            result["extent"] = [list(c) for c in polygon.exterior.coords]
            result["center"] = [geom.centroid.x, geom.centroid.y]
        population_job, population_error = self._try("population analysis", self._population, region, flood_source, flood_extent, flood_label)
        result["population"], result["population_error"] = population_job, population_error
        return result

    def _population(self, region: str, flood_source: str = "sample", flood_extent: dict | None = None,
                    flood_label: str | None = None) -> dict:
        started = self.api.post("/population/analyses", json=self._flood_request(region, flood_source, flood_extent, flood_label)).raise_for_status().json()
        ident = started.get("analysis_id") or started.get("id") or started.get("ident")
        for _ in range(60):
            status = self._get(f"/population/analyses/{region}/{ident}/status")
            if status.get("status") == "COMPLETED":
                break
            if status.get("status") == "FAILED":
                raise RuntimeError(status.get("error") or "population analysis failed")
            time.sleep(3)
        summary = self._get(f"/population/analyses/{region}/{ident}")
        rows = []
        admin = summary.get("administrative") or {}
        for level in ("ADM3", "ADM2"):
            for unit in (admin.get(level) or [])[:8]:
                rows.append({"name": unit.get("name") or unit.get("shapeName"), "level": level,
                             "people": unit.get("estimated_exposed_population") or unit.get("exposed_population")})
            if rows:
                break
        population = summary.get("population") or {}
        return {"rows": rows, "status": population.get("status"),
                "known_area_fraction": population.get("flood_area_with_known_population_fraction"),
                "adm3_available": (summary.get("administrative_availability") or {}).get("ADM3") == "AVAILABLE",
                "density": summary.get("density_distribution") or []}

    # ------------------------------------------------------------- snapshots
    def _snapshots(self, recipes: list[dict]) -> dict:
        def plan(recipe):
            return [{k: v for k, v in step[1].items() if k not in ("target", "max_height")}
                    for step in recipe["steps"] if step[0] == "capture"]
        if not self.capture_snapshots:
            return {"captured": False, "reason": "Snapshot capture switched off for this run", "shots": [s for r in recipes for s in plan(r)]}
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {"captured": False, "reason": "Playwright is not installed (pip install playwright, then: playwright install chromium)",
                    "shots": [s for r in recipes for s in plan(r)]}
        import base64
        shots = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            for recipe in recipes:
                done = plan(recipe)
                by_key = {s["key"]: s for s in done}
                try:
                    page.goto(self.frontend_url, wait_until="networkidle", timeout=90000)
                    for kind, *args in recipe["steps"]:
                        if kind == "nav":
                            page.get_by_role("navigation", name="Main navigation").get_by_role("button", name=args[0], exact=True).click()
                        elif kind == "click":
                            page.locator(args[0], has_text=args[1]).first.click()
                        elif kind == "role_click":
                            page.get_by_role(args[0], name=args[1], exact=True).first.click()
                        elif kind == "select":
                            page.get_by_label(args[0], exact=True).select_option(args[1])
                        elif kind == "wait":
                            page.locator(args[0]).first.wait_for(timeout=args[1])
                        elif kind == "upload":
                            page.get_by_label(args[0], exact=True).set_input_files(args[1])
                        elif kind == "pause":
                            page.wait_for_timeout(args[0])
                        elif kind == "capture":
                            spec = args[0]
                            element = page.locator(spec["target"]).first
                            element.scroll_into_view_if_needed()
                            box = element.bounding_box()
                            limit = spec.get("max_height")
                            if limit and box and box["height"] > limit:
                                scroll = page.evaluate("[scrollX, scrollY]")
                                image = page.screenshot(type="jpeg", quality=72, full_page=True, clip={
                                    "x": box["x"] + scroll[0], "y": box["y"] + scroll[1], "width": box["width"], "height": limit})
                            else:
                                image = element.screenshot(type="jpeg", quality=72)
                            shot = by_key[spec["key"]]
                            shot["image"] = "data:image/jpeg;base64," + base64.b64encode(image).decode()
                            shot["captured_at"] = _pkt(datetime.now(timezone.utc))
                except Exception as exc:
                    for shot in done:
                        if "image" not in shot:
                            shot["error"] = f"{recipe['name']}: {type(exc).__name__}: {str(exc).splitlines()[0][:140]}"
                shots += done
            browser.close()
        return {"captured": True, "shots": shots}
