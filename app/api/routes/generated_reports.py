"""Reports screen: archive of generated reports, downloads, deletion and on-demand generation."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
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
def view_report(id: str, layout: Literal["standard", "notebook"] = "standard"):
    path = _file(id, "html")
    if layout == "notebook":
        html = path.read_text(encoding="utf-8")
        notebook_style = """
<script>document.documentElement.dataset.theme = 'light';</script>
<style id="floodguard-notebook-layout">
body{padding:0!important;background:#e8edef!important;overflow:hidden}
#report{display:none}
#floodguard-book{height:calc(100vh - 74px);min-height:460px;margin-top:48px;overflow:hidden}
#floodguard-book-track{display:flex;gap:20px;height:100%;transition:transform .25s ease}
.floodguard-spread{display:grid;grid-template-columns:1fr 1fr;flex:0 0 100%;height:100%;background:#fff;box-shadow:0 5px 22px rgba(15,30,36,.18);border:1px solid #cbd3d6}
.floodguard-page{height:100%;min-width:0;overflow:auto;padding:26px 28px;background:#fff}
.floodguard-page+.floodguard-page{border-left:1px solid #cbd3d6;box-shadow:inset 9px 0 14px -14px #52636a}
@media(max-width:760px){#floodguard-book{height:calc(100vh - 74px)}.floodguard-spread{grid-template-columns:1fr}.floodguard-page:nth-child(2){display:none}.floodguard-page{padding:18px}}
</style>
"""
        html = html.replace("</head>", notebook_style + "</head>", 1)
        notebook_script = """
<script>
document.addEventListener('DOMContentLoaded', () => {
  const report = document.getElementById('report');
  if (!report) return;
  const book = document.createElement('div'); book.id = 'floodguard-book';
  const track = document.createElement('div'); track.id = 'floodguard-book-track'; book.appendChild(track);
  document.body.appendChild(book);
  const pages = [];
  let spread, page;
  const newPage = () => {
    if (pages.length % 2 === 0) {
      spread = document.createElement('div'); spread.className = 'floodguard-spread'; track.appendChild(spread);
    }
    page = document.createElement('div'); page.className = 'floodguard-page'; spread.appendChild(page); pages.push(page);
  };
  newPage();
  [...report.children].forEach((block) => {
    page.appendChild(block);
    if (page.scrollHeight > page.clientHeight + 2 && page.children.length > 1) {
      page.removeChild(block); newPage(); page.appendChild(block);
    }
  });
  if (pages.length % 2) { const blank = document.createElement('div'); blank.className = 'floodguard-page'; spread.appendChild(blank); }
  report.remove();
  const spreads = [...track.children]; let current = 0;
  const update = () => {
    track.style.transform = `translateX(-${current * (book.clientWidth + 20)}px)`;
    window.parent.postMessage({ type: 'floodguard-notebook-state', current, total: spreads.length }, '*');
  };
  window.addEventListener('message', (event) => {
    if (event.source !== window.parent || !event.data) return;
    if (event.data.type === 'floodguard-notebook-state') update();
    if (event.data.type === 'floodguard-notebook-move') {
      current = Math.max(0, Math.min(spreads.length - 1, current + Number(event.data.direction || 0)));
      update();
    }
  });
  window.addEventListener('resize', update);
  update();
});
</script>
"""
        html = html.replace("</body>", notebook_script + "</body>", 1)
        return HTMLResponse(html)
    return FileResponse(path, media_type="text/html")


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
