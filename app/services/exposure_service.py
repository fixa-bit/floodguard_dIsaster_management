"""Configured dataset access and durable GIS analysis artifacts; no frontend dependency."""
import json
import threading
from pathlib import Path
from uuid import UUID, uuid4

from shapely.geometry import Point, box, mapping

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.gis.exposure_engine import DatasetBundle, SLUG, audit_bundle, calculate, polygon_extent, write_json, timestamp
from app.schemas.exposure import ExposureRequest

LAYERS = {"flood_extent", "roads", "buildings", "hospitals", "schools", "settlements", "reference_buildings"}
_audit_cache = {}
_audit_lock = threading.Lock()
_analysis_lock = threading.Lock()


class ExposureService:
    def __init__(self, dataset_root=None, output_root=None):
        settings = get_settings()
        default = Path(__file__).resolve().parents[3] / "flood_model/exposure_infrastructure/datasets/exposure"
        self.root = Path(dataset_root or settings.exposure_dataset_root or default).resolve()
        self.outputs = Path(output_root or settings.exposure_output_root or self.root / "analysis").resolve()

    def regions(self):
        folder = self.root / "processed"
        result = []
        for path in sorted(folder.iterdir()) if folder.exists() else []:
            if path.is_dir() and SLUG.fullmatch(path.name):
                try:
                    bundle = DatasetBundle(self.root, path.name)
                    result.append({"region": path.name, "study_area": bundle.run["area"]["selection"],
                                   "prepared_at": bundle.run.get("processed_at"),
                                   "historical_reference_available": bundle.verification.get("flood_reference", {}).get("status") == "COMPATIBLE_REFERENCE_EXTENT"})
                except AppError:
                    result.append({"region": path.name, "status": "NOT_READY"})
        return {"regions": result}

    def audit(self, region, include_reference=True, refresh=False):
        bundle = DatasetBundle(self.root, region)
        provenance = json.dumps(bundle.verification, sort_keys=True)
        key = (str(self.root), region, include_reference, bundle.signatures(include_reference), hash(provenance))
        # Serialize audits; avoid simultaneous nationwide scans exhausting memory.
        with _audit_lock:
            if not refresh and key in _audit_cache:
                return _audit_cache[key]
            report = audit_bundle(bundle, include_reference)
            try:
                flood, provenance = bundle.historical_flood()
                overlap = flood.intersection(bundle.aoi)
                report["flood_alignment"] = {"status": "COMPATIBLE_REFERENCE" if overlap.area > 0 else "NO_OVERLAP",
                    "kind": provenance["kind"], "observation_period": provenance.get("observation_period"),
                    "note": "Historical satellite water reference; model output alignment is not implied."}
            except AppError as exc:
                report["flood_alignment"] = {"status": "NOT_AVAILABLE", "reason": exc.message}
            if len(_audit_cache) >= 8:
                _audit_cache.clear()
            _audit_cache[key] = report
        destination = self.outputs / region / "dataset_audit.json"
        write_json(destination, report)
        return report

    def analyze(self, request: ExposureRequest):
        if not _analysis_lock.acquire(blocking=False):
            raise AppError("EXPOSURE_ANALYSIS_BUSY", "A GIS analysis is already running in this worker; retry after it finishes", 409)
        destination = None
        try:
            bundle = DatasetBundle(self.root, request.region)
            if request.flood_source == "historical_reference":
                flood, provenance = bundle.historical_flood()
            elif request.flood_source == "provided":
                flood = polygon_extent(request.flood_extent, request.flood_crs)
                provenance = {"kind": "user_provided_unverified", "label": request.flood_label, "is_sample": False,
                              "declared_crs": request.flood_crs}
            else:
                station = bundle.configuration.get("area", {}).get("station", {})
                center = Point(station["coordinates"]) if station.get("coordinates") else bundle.aoi.representative_point()
                flood = box(center.x-0.04, center.y-0.03, center.x+0.04, center.y+0.03)
                provenance = {"kind": "synthetic_sample", "label": "SYNTHETIC TEST POLYGON — not an observed or forecast flood",
                              "is_sample": True, "source": "Deterministic rectangle centred on the configured station; GIS tests only"}
            audit = self.audit(request.region, request.include_reference_buildings)
            if audit["technical_status"] == "BLOCKED":
                failed = [name for name,d in audit["datasets"].items() if d["status"] == "BLOCKED"]
                raise AppError("EXPOSURE_DATASET_BLOCKED", "Correct dataset audit failures before calculating: " + ", ".join(failed), 503)
            if request.include_reference_buildings and bundle.verification.get("buildings_reference", {}).get("status") != "ASSESSED":
                # Reference inventory is optional; make omissions explicit instead of reading a file still being prepared.
                audit_warning = "Independent building reference is unavailable; mapped OSM counts only are returned."
            else:
                audit_warning = None
            analysis_id = str(uuid4())
            destination = self.outputs / request.region / analysis_id
            destination.mkdir(parents=True)
            summary = calculate(bundle, flood, provenance, destination, request.population_method, request.include_reference_buildings)
            summary.update(analysis_id=analysis_id, dataset_audit_status=audit["technical_status"])
            if audit_warning:
                summary["warnings"].append(audit_warning)
            summary["layers"] = {p.stem: f"/api/v1/exposure/analyses/{request.region}/{analysis_id}/layers/{p.stem}" for p in destination.glob("*.geojson")}
            summary["summary_url"] = f"/api/v1/exposure/analyses/{request.region}/{analysis_id}"
            write_json(destination / "summary.json", summary)
            write_json(destination / "audit.json", audit)
            write_json(destination / "status.json", {"status": "COMPLETED", "completed_at": timestamp()})
            return summary
        except AppError:
            if destination:
                write_json(destination / "status.json", {"status": "FAILED", "failed_at": timestamp()})
            raise
        except Exception as exc:
            if destination:
                write_json(destination / "status.json", {"status": "FAILED", "failed_at": timestamp()})
            raise AppError("EXPOSURE_ANALYSIS_FAILED", f"GIS calculation failed: {exc}", 503) from exc
        finally:
            _analysis_lock.release()

    def artifact(self, region, analysis_id, layer=None):
        if not SLUG.fullmatch(region):
            raise AppError("INVALID_REGION", "Invalid region name", 422)
        try:
            analysis_id = str(UUID(analysis_id))
        except ValueError as exc:
            raise AppError("INVALID_ANALYSIS_ID", "Analysis ID must be a UUID", 422) from exc
        if layer is not None and layer not in LAYERS:
            raise AppError("UNKNOWN_EXPOSURE_LAYER", "Unknown exposure layer", 404)
        folder = self.outputs / region / analysis_id
        status = folder / "status.json"
        if not status.exists() or json.loads(status.read_text(encoding="utf-8")).get("status") != "COMPLETED":
            raise AppError("EXPOSURE_ANALYSIS_NOT_FOUND", "Completed analysis not found", 404)
        path = folder / (f"{layer}.geojson" if layer else "summary.json")
        if not path.exists():
            raise AppError("EXPOSURE_LAYER_NOT_AVAILABLE", "Layer was not included in this analysis", 404)
        return path
