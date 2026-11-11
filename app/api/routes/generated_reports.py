"""Reports screen: archive of generated reports, downloads, deletion and on-demand generation."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.reports.flood_events import LEVELS, STATION_RIVER
from app.reports.ai.review import ai_summary, clear_decision, load_review, save_decision
from app.services import report_jobs

router = APIRouter(prefix="/generated-reports", tags=["Reports"])


class DailyRequest(BaseModel):
    run_satellite: bool = True
    capture_snapshots: bool = True
    test_flood_region: str | None = "trimmu_jhang"
    ai_analysis: bool = True
    ai_review: Literal["portal", "label"] = "portal"


class StationReading(BaseModel):
    station_id: str
    category: str
    discharge: float | None = Field(default=None, ge=0)


class FloodEventRequest(BaseModel):
    mode: Literal["new", "continue", "close", "real"] = "new"
    scenario_id: str | None = None
    signals: list[StationReading] = []
    run_satellite: bool = True
    capture_snapshots: bool = True
    ai_analysis: bool = False
    ai_review: Literal["portal", "label"] = "portal"


class ReviewRequest(BaseModel):
    id: str
    flag_id: str = Field(pattern=r"^F\d{1,3}$")
    decision: Literal["accepted", "rejected"]
    note: str = Field(default="", max_length=1000)
    reviewer: str = Field(min_length=1, max_length=80)


@router.get("")
def list_reports():
    return report_jobs.list_reports()


@router.get("/options")
def report_options():
    return report_jobs.options()


@router.get("/jobs")
def list_jobs():
    return report_jobs.list_jobs()


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = report_jobs.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.post("/daily", status_code=202)
def generate_daily(request: DailyRequest):
    if request.test_flood_region not in (None, "trimmu_jhang", "balloki"):
        raise HTTPException(422, "Unknown test flood region")
    try:
        return report_jobs.start_daily(request.run_satellite, request.capture_snapshots, request.test_flood_region,
                                       ai_analysis=request.ai_analysis, ai_review=request.ai_review)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/flood-event", status_code=202)
def generate_flood_event(request: FloodEventRequest):
    signals = [s.model_dump() for s in request.signals]
    label = "Flood Event Report"
    if request.scenario_id:
        scenario = next((s for s in report_jobs.SCENARIOS if s["id"] == request.scenario_id), None)
        if not scenario:
            raise HTTPException(422, "Unknown scenario")
        signals, label = scenario["signals"], f"Flood Event Report: {scenario['name']}"
    for s in signals:
        if s["station_id"] not in STATION_RIVER:
            raise HTTPException(422, f"Unknown station {s['station_id']}")
        if s["category"] not in LEVELS:
            raise HTTPException(422, f"Category must be one of: {', '.join(LEVELS)}")
    if request.mode == "close":
        label = "Flood Event Report: close open test event"
    elif request.mode == "real":
        label = "Flood Event Report: check real data"
    try:
        return report_jobs.start_flood_event(signals, request.mode, request.run_satellite, request.capture_snapshots, label,
                                             ai_analysis=request.ai_analysis, ai_review=request.ai_review)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


def _file(report_id: str, kind: str):
    try:
        return report_jobs.report_file(report_id, kind)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Report not found") from exc


@router.get("/view")
def view_report(id: str):
    return FileResponse(_file(id, "html"), media_type="text/html")


@router.get("/download")
def download_report(id: str, format: Literal["html", "json"] = "html"):
    path = _file(id, format)
    name = path.name if format == "html" else f"{_file(id, 'html').stem}.json"
    return FileResponse(path, media_type="text/html" if format == "html" else "application/json", filename=name)


@router.delete("")
def delete_report(id: str):
    try:
        report_jobs.delete_report(id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Report not found") from exc
    return {"deleted": id}


def _folder(report_id: str):
    try:
        return report_jobs.report_file(report_id, "json").parent
    except FileNotFoundError as exc:
        raise HTTPException(404, "Report not found") from exc


@router.get("/ai")
def report_ai(id: str):
    """Flags (code), AI analysis and reviewer decisions of one report, for the review dialog."""
    import json
    folder = _folder(id)
    data = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    review = load_review(folder)
    return {"id": id, "title": data.get("meta", {}).get("report_no"), "flags": data.get("flags") or [],
            "ai_analysis": data.get("ai_analysis"), "review": review, "summary": ai_summary(data, review)}


@router.post("/review")
def review_ai_note(request: ReviewRequest):
    folder = _folder(request.id)
    try:
        review = save_decision(folder, request.flag_id, request.decision, request.note, request.reviewer)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"id": request.id, "review": review}


@router.delete("/review")
def clear_ai_review(id: str, flag_id: str):
    return {"id": id, "review": clear_decision(_folder(id), flag_id)}
