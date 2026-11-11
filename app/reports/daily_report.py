"""Collect portal data for the Daily Flood Situation Report and render it to HTML.

The structure and rules follow docs/reports/daily_report_spec.md:
fixed coverage (every section and station, "Unavailable" with a reason when data
is missing), a data-source label on every item, and explicit marking of simulated
data. Rendering is done by app/reports/templates/daily_report.html, which reads the
JSON payload produced here.
"""


from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.reports.collector import (
    EXPOSURE_REGIONS, PKT, ROOT, STATION_COORDS, STATION_NAMES, PortalCollector, nearest_preview_area,
    shot_model_graphs, shot_population, shot_simulation_spread, shot_upstream,
)
from app.reports.flags import build_daily_flags
from app.reports.render import render_page


class DailyReportBuilder(PortalCollector):
    def __init__(self, api_base: str, db_path: Path, generated_at: datetime | None = None,
                 test_flood_region: str | None = "trimmu_jhang", run_satellite: bool = True,
                 capture_snapshots: bool = True, frontend_url: str = "http://127.0.0.1:3000",
                 output_dir: Path | None = None):
        super().__init__(api_base, db_path, generated_at, run_satellite, capture_snapshots, frontend_url)
        local = self.generated_at.astimezone(PKT)
        end = local.replace(hour=6, minute=0, second=0, microsecond=0)
        if local < end:
            end -= timedelta(days=1)
        self.period_end = end.astimezone(timezone.utc)
        self.period_start = self.period_end - timedelta(days=1)
        self.test_flood_region = test_flood_region
        self.output_dir = output_dir

    # ---------------------------------------------------------------- sections
    def build(self) -> dict:
        system, _ = self._try("system status", self._get, "/system/status")
        monitoring, monitoring_error = self._try("river monitoring", self._get, "/river/monitoring")
        upstream, upstream_error = self._try("upstream forecasts", self._get, "/river/upstream-forecasts")
        national, national_error = self._try("national risk", self._get, "/gis/national-risk")
        alerts, _ = self._try("alerts", self._get, "/alerts")
        incidents, _ = self._try("incidents", self._get, "/incidents")
        reports, _ = self._try("citizen reports", self._get, "/citizen-reports")
        model_points, model_error = self._try("model forecasts", self._get, "/flood/model-forecasts")
        seasonal, seasonal_error = self._try("seasonal outlook", self._get, "/predictive/marala-monthly")

        stations = self._stations(monitoring or {"stations": []})
        districts = self._districts(national, stations, reports or [], incidents or [])
        sim_runs = self._simulation_runs()
        ops = self._operations(alerts or [], incidents or [], reports or [])
        satellite = self._satellite(stations, districts, incidents or [])
        data = {
            "meta": self._meta(system or {}),
            "stations": stations,
            "wave": self._wave(stations),
            "inout": self._inout(stations),
            "forecasts": self._forecasts(stations),
            "upstream": self._upstream(upstream, upstream_error),
            "models": self._models(model_points, model_error),
            "seasonal": self._seasonal(seasonal, seasonal_error),
            "accuracy": {"available": False, "reason": "Needs forecasts stored on at least two report days. Starts once the report archive builds up."},
            "rainfall": self._rainfall(national, national_error),
            "districts": districts,
            "operations": ops,
            "satellite": satellite,
            "simulation_runs": sim_runs,
        }
        # Values a rule flagged (code). The optional AI step explains them; it never changes them.
        data["flags"] = build_daily_flags(data)
        data["snapshots"] = self._snapshots(self._snapshot_recipes(data))
        data["data_quality"] = self._data_quality(system or {}, monitoring, monitoring_error, upstream, upstream_error,
                                                  national, national_error, data)
        data["summary"] = self._summary(data)
        data["provenance"] = dict(self.src.counts)
        data["has_simulated"] = self.src.counts.get("sim", 0) > 0
        return data

    def _snapshot_recipes(self, data: dict) -> list[dict]:
        """Flood-relevant portal visuals only (spec: App snapshots)."""
        recipes = [shot_model_graphs("06", simulated=any("sim" in r["sources"] for r in data["models"]["rows"]))]
        upstream = data["upstream"].get("stations") or []
        # Selective cases: stations where the providers disagree, else the highest riverine signal.
        chosen = [u for u in upstream if u["agreement_pct"] is not None and not u["agree"]]
        if not chosen and upstream:
            chosen = [max(upstream, key=lambda u: max((s["probability"] for s in u["signals"] if s["type"] == "Riverine flood"), default=0))]
        recipes += [shot_upstream(u["name"], "06") for u in chosen[:2]]
        if self.test_flood_region:
            recipes.append(shot_population(self.test_flood_region, "sample", "11", ["sim", "est"]))
            station = next((sid for sid, region in EXPOSURE_REGIONS.items() if region == self.test_flood_region), None)
            area = nearest_preview_area(station) if station else None
            if area:
                recipes.append(shot_simulation_spread(area, "11"))
        return recipes

    def _meta(self, system: dict) -> dict:
        local_end = self.period_end.astimezone(PKT)
        return {
            "report_no": f"DFSR-{local_end:%Y}-{local_end.timetuple().tm_yday:03d}",
            "period": f"{self.period_start.astimezone(PKT):%d %b %Y %H:%M} → {local_end:%d %b %Y %H:%M} PKT",
            "generated": f"{self.generated_at.astimezone(PKT):%d %b %Y %H:%M} PKT",
            "data_mode": system.get("data_mode", "unknown"),
            "simulation_enabled": system.get("simulation_enabled"),
            "ml_model_enabled": system.get("ml_model_enabled"),
            "units": "Discharge in cumecs (m³/s, as provided by the portal); rainfall in mm",
        }

    def _satellite(self, stations: list[dict], districts: dict, incidents: list) -> dict:
        watch = []
        for s in stations:
            if s["category"] not in ("Below low", "Unavailable") or (s["change_24h"] and s["discharge"] and s["change_24h"] > 50):
                watch.append({"name": f"{s['name']} station", "why": f"{s['category']}, change {s['change_24h']}", "coords": STATION_COORDS[s["id"]], "simulated": False, "station_id": s["id"]})
        for d in (districts.get("multi_signal") or []):
            if d["signal_count"] >= 3:
                watch.append({"name": d["district"], "why": "3 or more warning signs", "coords": (d["lon"], d["lat"]), "simulated": False, "station_id": None})
        for i in incidents:
            if i.get("type") == "FLOOD" and i.get("status") not in ("RESOLVED", "CLOSED"):
                coords = STATION_COORDS.get(i["location_id"])
                if coords:
                    simulated = str(i.get("source", "")).startswith("SIMULATED")
                    watch.append({"name": STATION_NAMES.get(i["location_id"], i["location_id"]),
                                  "why": f"Open flood incident #{i['id']}" + (" (simulated)" if simulated else ""),
                                  "coords": coords, "simulated": simulated, "station_id": i["location_id"]})
        gauge = {s["id"]: s["category"] for s in stations}
        merged: dict = {}  # one check per location; keep every reason; simulated only if every trigger was simulated
        for w in watch:
            key = w["station_id"] or w["name"]
            if key in merged:
                merged[key]["why"] += "; " + w["why"]
                merged[key]["simulated"] = merged[key]["simulated"] and w["simulated"]
            else:
                merged[key] = dict(w)
        watch = list(merged.values())
        checks = []
        for w in watch[:4]:
            row = {"location": w["name"], "why": w["why"], "triggered_by_simulation": w["simulated"],
                   "station_id": w["station_id"], "gauge_category": gauge.get(w["station_id"]) if w["station_id"] else None}
            if not self.run_satellite:
                row.update(result="not_run", reason="Satellite checks switched off for this run")
            else:
                started = time.time()
                sar, error = self._try("Sentinel-1 check", self._sar, w["coords"][1], w["coords"][0])
                row.update(sar or {}, result=(sar or {}).get("status", "error"), error=error, seconds=round(time.time() - started))
            row["sources"] = self.src("sat", "sim") if w["simulated"] else self.src("sat")
            checks.append(row)
        test_flood = self._test_flood() if self.test_flood_region else None
        return {"checks": checks, "test_flood": test_flood,
                "rule": "Watch locations: stations in flood or rising more than 50 cumecs in 24 h, districts with 3 or more warning signs, and open flood incidents (up to 4 per report). "
                        "Radar water at a station (barrage, headworks or dam) raises the national status only if that station's gauge is above Below low, because river water there is normal."}

    def _test_flood(self) -> dict:
        """Simulated flood on real imagery: synthetic exposure extent + real Sentinel-1 at the same place."""
        result = self._impact(self.test_flood_region, "sample", sources=self.src("sim", "sat", "est"))
        if result.get("center") and self.run_satellite:
            lon, lat = result["center"]
            result["sar"], result["sar_error"] = self._try("Sentinel-1 under simulated flood", self._sar, lat, lon)
        return result

    # -------------------------------------------------------- quality + summary
    def _data_quality(self, system, monitoring, monitoring_error, upstream, upstream_error, national, national_error, data) -> list[dict]:
        rows = []
        stations = data["stations"]
        newest = max((s["age_hours"] for s in stations if s["age_hours"] is not None), default=None)
        oldest = min((s["age_hours"] for s in stations if s["age_hours"] is not None), default=None)
        available = sum(s["available"] for s in stations)
        rows.append({"feed": "FFD river state", "status": "Error" if monitoring_error else ("Stale" if oldest is None or oldest > 24 else "OK"),
                     "last": next((s["observed_at"] for s in stations if s["observed_at"]), "—"), "coverage": f"{available} / {len(stations)}",
                     "note": monitoring_error or (f"Latest reading is {oldest:.0f} h old" if oldest and oldest > 24 else "")})
        if upstream:
            for name in ("GloFAS", "GEOGloWS"):
                statuses = [p["status"] for s in data["upstream"]["stations"] for p in s["providers"] if p["provider"] == name]
                ok = statuses.count("available")
                rows.append({"feed": f"{name} (upstream watch)", "status": "OK" if ok == len(statuses) and statuses else "Partial",
                             "last": data["upstream"].get("cached_at") or "—", "coverage": f"{ok} / {len(statuses)}", "note": upstream.get("refresh_error") or ""})
        else:
            rows.append({"feed": "Upstream forecasts", "status": "Error", "last": "—", "coverage": "—", "note": upstream_error})
        rows.append({"feed": "Open-Meteo district weather", "status": "OK" if national else "Error", "last": data["meta"]["generated"],
                     "coverage": f"{data['districts'].get('total', 0)} districts", "note": national_error or ""})
        checks = data["satellite"]["checks"]
        sar_ok = sum(1 for c in checks if c.get("result") not in ("error", "not_run"))
        rows.append({"feed": "Sentinel-1 radar (Planetary Computer)", "status": "OK" if sar_ok == len(checks) else "Partial",
                     "last": max((c.get("during_date") or "")[:10] for c in checks) if checks else "—", "coverage": f"{sar_ok} / {len(checks)} checks",
                     "note": "; ".join(c["error"] for c in checks if c.get("error"))})
        model_sim = sum(1 for r in data["models"]["rows"] if "sim" in r["sources"])
        rows.append({"feed": "Model forecasts", "status": "Placeholder" if model_sim else "OK", "last": "—",
                     "coverage": f"{len(data['models']['rows'])} outputs", "note": f"{model_sim} outputs come from placeholder (dummy) models" if model_sim else ""})
        rows.append({"feed": "Simulation engine", "status": "On" if system.get("simulation_enabled") else "Off", "last": "—",
                     "coverage": f"{len(data['simulation_runs'])} stored runs",
                     "note": "Stored simulated alerts or incidents still appear in this report" if data["simulation_runs"] else ""})
        snaps = data["snapshots"]
        captured = sum(1 for s in snaps["shots"] if s.get("image"))
        rows.append({"feed": "Portal snapshots", "status": "OK" if captured == len(snaps["shots"]) else ("Unavailable" if not captured else "Partial"),
                     "last": "—", "coverage": f"{captured} / {len(snaps['shots'])}", "note": snaps.get("reason", "")})
        return rows

    def _summary(self, data: dict) -> dict:
        real = [s for s in data["stations"] if s["available"]]
        in_flood = [s for s in real if s["category"] not in ("Below low", "Unavailable")]
        order = ["Below low", "Low flood", "Medium flood", "High flood", "Very high flood", "Exceptionally high flood"]
        highest = max((s["category"] for s in real), key=lambda c: order.index(c) if c in order else -1, default="Unavailable")
        rising = [s for s in real if s["change_24h"] and s["change_24h"] > 0]
        stale = [s for s in data["stations"] if s["stale"]]
        ops = data["operations"]
        districts = data["districts"]
        top = (districts.get("top_risk") or [{}])[0]
        disagree = [u for u in (data["upstream"].get("stations") or []) if u["agreement_pct"] is not None and not u["agree"]]
        real_flood_checks = [c for c in data["satellite"]["checks"] if c.get("result") == "potential_flooding_detected" and not c["triggered_by_simulation"]]
        # Radar water at a station only counts when its own gauge confirms it (river water at barrages is normal).
        status_flood_checks = [c for c in real_flood_checks if not c.get("station_id") or c.get("gauge_category") not in ("Below low",)]
        sim_flood_checks = [c for c in data["satellite"]["checks"] if c.get("result") == "potential_flooding_detected" and c["triggered_by_simulation"]]
        # National status uses real data only; simulated items never raise it.
        if any(order.index(s["category"]) >= 3 for s in in_flood if s["category"] in order):
            status = "Emergency"
        elif in_flood:
            status = "Warning"
        elif disagree or status_flood_checks or any(r["risk"] >= 60 for r in districts.get("top_risk", [])):
            status = "Watch"
        else:
            status = "Normal"
        concerns = []
        stale_aged = [s for s in stale if s["age_hours"] is not None]
        missing = [s["name"] for s in data["stations"] if not s["available"]]
        if stale_aged:
            concerns.append({"text": f"River readings are {min(s['age_hours'] for s in stale_aged):.0f} hours old. FFD has not published a newer river-state reading since {stale_aged[0]['observed_at']} PKT.", "sources": ["obs"]})
        if missing:
            concerns.append({"text": "No reading for: " + ", ".join(missing) + ".", "sources": ["obs"]})
        for c in sim_flood_checks + real_flood_checks:
            reason = " The check ran because of a simulated incident, but the image is real." if c["triggered_by_simulation"] else ""
            if c.get("station_id") and c.get("gauge_category") == "Below low":
                gauges = " The gauge here is Below low, so this is most likely normal river water. It does not raise the national status."
            else:
                gauges = " All gauges are Below low, so this is most likely seasonal river water. It needs review, not action." if not in_flood else ""
            concerns.append({"text": f"The real Sentinel-1 pass of {c['during_date'][:10]} shows {c['potential_flood_area_km2']:.1f} km² of water outside the permanent-water "
                                     f"reference at {c['location']}.{reason}{gauges}",
                             "sources": ["sat"] + (["sim"] if c["triggered_by_simulation"] else [])})
        for u in disagree:
            peaks = ", ".join(f"{p['provider']} {p['peak']:,.0f}" for p in u["providers"] if p["peak"] is not None)
            concerns.append({"text": f"Forecast sources disagree by {u['agreement_pct']}% on the {u['name']} peak ({peaks} cumecs). Check the upstream watch before relying on either.", "sources": ["api"]})
        sim_alerts = [a for a in ops["alerts"] if "sim" in a["sources"] and a["approval"] == "pending"]
        if sim_alerts:
            concerns.append({"text": f"{len(sim_alerts)} simulated alert(s) from old test runs are still pending approval, and {sum(1 for i in ops['incidents'] if 'sim' in i['sources'] and i['status'] == 'OPEN')} simulated incident(s) are still open. Close them so they stop appearing in reports.", "sources": ["sim"]})
        mismatched = [f for f in data["forecasts"] if f["mismatch"]]
        if mismatched:
            concerns.append({"text": f"At {len(mismatched)} stations the GloFAS forecast differs from the observed flow by more than 10×. The forecast grid cell may not match the station: " + ", ".join(f["name"] for f in mismatched[:6]) + ".", "sources": ["api"]})
        headline = (f"{len(in_flood)} of {len(data['stations'])} stations are in flood. " if in_flood else f"All {len(real)} reporting stations are below low flood. ") + \
                   (f"{len(rising)} stations rose since the previous reading. " if rising else "No station rose since the previous reading. ") + \
                   (f"The highest district screening risk is {top.get('risk')}% ({top.get('district')}). " if top else "") + \
                   ("River readings are stale. " if stale else "")
        kpis = [
            {"value": f"{len(in_flood)} / {len(data['stations'])}", "label": "Stations in flood"},
            {"value": highest, "label": "Highest category"},
            {"value": str(len(rising)), "label": "Stations rising"},
            {"value": str(ops["counts"]["alerts"]["open"]), "label": "Alerts awaiting approval"},
            {"value": str(ops["counts"]["incidents"]["open"]), "label": "Open incidents"},
            {"value": str(sum(1 for r in ops["reports"] if r["verification"] == "PENDING")), "label": "Pending citizen reports"},
            {"value": f"{top.get('risk', '—')}%", "label": f"Highest district risk ({top.get('district', '—')})"},
            {"value": f"{sum(c.get('potential_flood_area_km2') or 0 for c in data['satellite']['checks']):.1f} km²", "label": "Possible flood water (satellite)"},
        ]
        previous = self._previous_summary()
        if previous:
            for k in kpis:
                old = next((p["value"] for p in previous.get("kpis", []) if p["label"] == k["label"]), None)
                k["delta"] = "= yesterday" if old == k["value"] else (f"was {old}" if old is not None else "new")
        else:
            for k in kpis:
                k["delta"] = "No previous report"
        categories = Counter(s["category"] for s in data["stations"])
        return {"status": status, "status_note": "Based on real data only. Simulated items never raise the national status.",
                "headline": headline.strip(), "kpis": kpis, "concerns": concerns[:5], "categories": dict(categories)}

    def _previous_summary(self) -> dict | None:
        if not self.output_dir:
            return None
        day = (self.period_end - timedelta(days=1)).astimezone(PKT).strftime("%Y-%m-%d")
        runs = sorted(f / "report.json" for f in self.output_dir.glob(f"{day}*") if (f / "report.json").exists())
        if runs:  # the last report generated on the previous day
            return json.loads(runs[-1].read_text(encoding="utf-8")).get("summary")
        return None


def render_html(data: dict) -> str:
    return render_page("daily_report.js", data, data["meta"]["report_no"])

def generate(api_base: str = "http://127.0.0.1:8000/api/v1", output_dir: Path | None = None, trigger: str = "manual",
             ai_analysis: bool | None = None, ai_review: str | None = None, progress=None, **options) -> Path:
    """Phase 1 writes the complete deterministic report. Phase 2 (optional) adds the AI analysis of flagged values."""
    from app.core.config import get_settings
    from app.reports.ai.runner import placeholder, review_mode_for, run_ai_analysis

    output_dir = output_dir or ROOT / "reports" / "daily"
    builder = DailyReportBuilder(api_base, ROOT / "floodguard.db", output_dir=output_dir, **options)
    data = builder.build()
    data["meta"]["trigger"] = trigger  # scheduled | manual
    run_ai = get_settings().ai_analysis_enabled if ai_analysis is None else ai_analysis
    review_mode = review_mode_for(trigger, ai_review)
    data["ai_analysis"] = placeholder(run_ai, trigger, review_mode)
    # One folder per run (date and time of generation, PKT), so every generated report is kept.
    folder = output_dir / builder.generated_at.astimezone(PKT).strftime("%Y-%m-%d_%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "report.json").write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    html_path = folder / f"{data['meta']['report_no']}.html"
    html_path.write_text(render_html(data), encoding="utf-8")
    if run_ai:
        run_ai_analysis(folder, trigger=trigger, review_mode=review_mode, progress=progress)
    return html_path
