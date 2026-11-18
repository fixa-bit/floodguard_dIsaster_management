"""Reports screen: archive of generated reports, downloads, deletion and on-demand generation."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from app.reports.flood_events import LEVELS, STATION_RIVER
from app.reports.ai.review import ai_summary, clear_decision, load_review, save_decision
from app.services import report_jobs

# Two-column view of a report (?layout=columns), in the app's dark colours: the
# banner and header span the width, the numbered sections sit side by side, and the
# reader scrolls normally. Sections never split across the two columns.
COLUMNS_HEAD = """
<script>document.documentElement.dataset.theme = 'dark';</script>
<style id="floodguard-columns-layout">
body{margin:0!important;padding:18px!important;background:#071416!important}
#report{max-width:1600px!important;margin:0 auto!important;display:grid!important;grid-template-columns:minmax(0,1fr) minmax(0,1fr);
  column-gap:0;align-items:start;border-color:rgba(125,232,219,.16)!important;box-shadow:0 18px 40px rgba(0,0,0,.45)}
#report>*{grid-column:1/-1;min-width:0}
#report>section{grid-column:auto;align-self:stretch;border-top:1px solid var(--rule)}
#report>section:nth-of-type(odd){border-right:1px solid var(--rule)}
#report>section>.inner{padding:22px 26px}
#report table{display:block;max-width:100%;overflow-x:auto}
#report img,#report svg,#report canvas{max-width:100%}
@media (max-width:900px){#report{grid-template-columns:minmax(0,1fr)}#report>section:nth-of-type(odd){border-right:0}}
</style>
"""

# Notebook view of a report (?layout=notebook): the report flows onto fixed-size pages,
# shown two at a time like an open notebook (one at a time on narrow screens), and the
# reader turns pages with the buttons, the arrow keys or a swipe. Columns of a fixed
# height carry the pagination; the script only measures and scrolls.
NOTEBOOK_HEAD = """
<script>document.documentElement.dataset.theme = 'dark';</script>
<style id="floodguard-notebook-layout">
html,body{height:100%;overflow:hidden!important}
body{margin:0!important;padding:0!important;background:radial-gradient(ellipse at 50% 35%,#10292c 0,#071416 70%)!important}
.nb-view,.nb-flip{position:absolute;top:18px;bottom:64px;left:50%;transform:translateX(-50%) perspective(2600px) rotateX(6deg);transform-origin:50% 100%}
.nb-view{overflow:hidden;border-radius:3px;box-shadow:0 1px 0 #0b1113,0 2px 0 #2a3337,0 3px 0 #0b1113,0 4px 0 #2a3337,0 5px 0 #0b1113,0 0 0 1px rgba(80,245,208,.12),0 20px 40px rgba(0,0,0,.55)}
.nb-flip{pointer-events:none;z-index:5;transform-style:preserve-3d}
.nb-face{position:absolute;top:0;bottom:0;width:var(--nb-pw);overflow:hidden;background:var(--paper,#171d20);backface-visibility:hidden;-webkit-backface-visibility:hidden}
.nb-face>.nb-page{height:100%}
.nb-at-left{left:0}.nb-at-right{right:0}
.nb-leaf{position:absolute;top:0;bottom:0;width:var(--nb-pw);transform-style:preserve-3d;transition:transform .9s cubic-bezier(.45,.05,.3,1)}
.nb-leaf .nb-face{left:0}
.nb-leaf.fwd{transform-origin:0 50%}.nb-leaf.back{transform-origin:100% 50%}
.nb-leaf.fwd.turn{transform:rotateY(-180deg)}.nb-leaf.back.turn{transform:rotateY(180deg)}
.nb-face.nb-back{transform:rotateY(180deg)}
.nb-leaf .nb-face::after{content:"";position:absolute;inset:0;pointer-events:none;opacity:0;transition:opacity .45s ease-in;
  background:linear-gradient(to right,rgba(0,0,0,.5),rgba(0,0,0,0) 45%)}
.nb-leaf.turn .nb-face::after{opacity:1}
.nb-bar select{height:30px;padding:0 6px;color:#d8e9e8;background:#0f2326;border:1px solid rgba(125,232,219,.25);border-radius:6px;font:inherit}
.nb-bar .nb-auto{color:#d8e9e8;background:rgba(255,255,255,.08);border:1px solid rgba(125,232,219,.3)}
.nb-bar .nb-auto.on{color:#061113;background:#ffc247}
@media (prefers-reduced-motion:reduce){.nb-leaf{transition:none}.nb-view #report{transition:none}}
.nb-view #report{display:flex!important;width:max-content!important;max-width:none!important;height:100%;margin:0!important;padding:0!important;
  border:0!important;background:none!important;box-shadow:none!important;transition:transform .45s ease}
.nb-page{position:relative;flex:none;box-sizing:border-box;width:var(--nb-pw);height:100%;padding:24px 26px 34px;background:var(--paper,#171d20);color:var(--ink,#eef1f2)}
.nb-two .nb-page.nb-left{box-shadow:inset -20px 0 18px -14px rgba(0,0,0,.6)}
.nb-two .nb-page.nb-right{box-shadow:inset 20px 0 18px -14px rgba(0,0,0,.6)}
.nb-body{height:100%;overflow:hidden;display:flex;flex-direction:column;gap:14px}
.nb-body>*{flex:none;margin-top:0!important;margin-bottom:0!important}
.nb-page.nb-scroll .nb-body{overflow-y:auto}
.nb-num{position:absolute;bottom:10px;left:0;right:0;text-align:center;color:var(--ink-3,#8b9599);font:500 11px system-ui,-apple-system,Segoe UI,sans-serif}
.nb-body img,.nb-body svg,.nb-body canvas{max-width:100%}
.nb-body figure img,.nb-body img{max-height:calc(var(--nb-ph) - 150px);object-fit:contain}
.nb-body table{display:block;max-width:100%;overflow-x:auto}
.nb-body header.top{grid-template-columns:minmax(0,1fr)!important}
.nb-bar{position:fixed;left:0;right:0;bottom:0;height:52px;display:flex;align-items:center;justify-content:center;gap:14px;
  font:600 13px/1 system-ui,-apple-system,Segoe UI,sans-serif;color:#d8e9e8}
.nb-bar button{display:inline-flex;align-items:center;gap:6px;height:34px;padding:0 14px;color:#061113;background:#50f5d0;border:0;border-radius:17px;
  font:inherit;cursor:pointer;box-shadow:0 2px 6px rgba(0,0,0,.18)}
.nb-bar button:disabled{color:#6f8a8d;background:rgba(255,255,255,.08);cursor:default;box-shadow:none}
.nb-bar span{min-width:150px;text-align:center}
.nb-bar small{color:#8fb1b4;font-weight:500}
.nb-bar button,.nb-bar span{white-space:nowrap}
@media (max-width:720px){.nb-bar{gap:8px}.nb-bar small{display:none}.nb-bar span{min-width:0}.nb-bar button{padding:0 11px}}
</style>
"""

NOTEBOOK_BODY = """
<script id="floodguard-notebook-script">
(() => {
  const report = document.getElementById('report');
  if (!report) return;
  const view = document.createElement('div'); view.className = 'nb-view';
  report.parentNode.insertBefore(view, report); view.appendChild(report);
  const bar = document.createElement('div'); bar.className = 'nb-bar';
  bar.innerHTML = '<button type="button" data-go="-1" aria-label="Previous pages">&#8249; Previous</button>' +
    '<span aria-live="polite"></span><button type="button" data-go="1" aria-label="Next pages">Next &#8250;</button>' +
    '<button type="button" class="nb-auto" aria-pressed="false">&#9654; Auto-turn</button>' +
    '<select aria-label="Seconds per page"><option value="4">every 4 s</option><option value="7" selected>every 7 s</option><option value="12">every 12 s</option></select>' +
    '<small>Arrow keys turn pages</small>';
  document.body.appendChild(bar);
  const flipLayer = document.createElement('div'); flipLayer.className = 'nb-flip'; flipLayer.setAttribute('aria-hidden', 'true');
  document.body.appendChild(flipLayer);
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const label = bar.querySelector('span'), prev = bar.querySelector('[data-go="-1"]'), next = bar.querySelector('[data-go="1"]');
  const autoBtn = bar.querySelector('.nb-auto'), speed = bar.querySelector('select');
  let busy = false, autoTimer = 0;
  const KEEP_WHOLE = /^(FIGURE|IMG|CANVAS|PRE|svg|SVG)$/;
  let original = null, splits = [], pages = [], cur = null, perSpread = 2, pw = 600, spread = 0, size = '';

  // Put the report back the way it was drawn, so it can be laid out again at another size.
  function restore() {
    for (let i = splits.length - 1; i >= 0; i -= 1) { const s = splits[i]; s.kids.forEach((k) => s.node.appendChild(k)); }
    splits = [];
    if (original) report.replaceChildren(...original);
  }
  function newPage() {
    const page = document.createElement('div'); page.className = 'nb-page';
    page.innerHTML = '<div class="nb-body"></div><div class="nb-num"></div>';
    report.appendChild(page); pages.push(page); cur = { page, body: page.firstChild, items: 0 };
  }
  const fits = () => cur.body.scrollHeight <= cur.body.clientHeight + 1;
  // Place a block on the current page. A block too tall for a page is split into its children,
  // each piece wrapped in a copy of its container so it keeps its styling.
  function place(node, parentFor) {
    let parent = parentFor(); parent.appendChild(node);
    if (fits()) { cur.items += 1; return; }
    node.remove();
    if (cur.items) { newPage(); parent = parentFor(); parent.appendChild(node); if (fits()) { cur.items += 1; return; } node.remove(); }
    // A long table continues on the next page row by row, with its column headings repeated.
    const body = node.tagName === 'TABLE' ? node.tBodies[0] : null;
    if (body && body.rows.length > 1) {
      const rows = [...body.rows];
      splits.push({ node: body, kids: rows }); rows.forEach((r) => r.remove());
      let shellBody = null, shellPage = null;
      const bodyFor = () => {
        if (shellBody && shellPage === cur.page) return shellBody;
        const p = parentFor();
        if (!shellBody) { p.appendChild(node); shellBody = body; }
        else {
          const t = node.cloneNode(false); t.removeAttribute('id'); t.dataset.nbCopy = '1';
          if (node.tHead) t.appendChild(node.tHead.cloneNode(true));
          shellBody = body.cloneNode(false); t.appendChild(shellBody); p.appendChild(t);
        }
        shellPage = cur.page; return shellBody;
      };
      rows.forEach((r) => place(r, bodyFor));
      return;
    }
    const kids = [...node.children];
    if (kids.length && !KEEP_WHOLE.test(node.tagName)) {
      splits.push({ node, kids }); kids.forEach((k) => k.remove());
      let shell = null, shellPage = null;
      const shellFor = () => {
        if (shell && shellPage === cur.page) return shell;
        const p = parentFor();
        if (!shell) shell = node; else { shell = node.cloneNode(false); shell.removeAttribute('id'); shell.dataset.nbCopy = '1'; }
        p.appendChild(shell); shellPage = cur.page; return shell;
      };
      kids.forEach((k) => place(k, shellFor));
      return;
    }
    // One block taller than a page (a big table or chart): it gets a page to itself and scrolls inside it.
    parent = parentFor(); parent.appendChild(node); cur.page.classList.add('nb-scroll'); cur.items += 1; newPage();
  }
  const lastSpread = () => Math.max(0, Math.ceil(pages.length / perSpread) - 1);
  function paginate() {
    if (!original) { original = [...report.children]; if (!original.length) { original = null; return; } }
    const H = view.clientHeight, W = document.documentElement.clientWidth - 32;
    if (H < 240 || W < 240) return;  // hidden or not laid out yet: try again on the next resize
    perSpread = W >= 900 ? 2 : 1;
    pw = Math.floor(Math.min(H * 0.8, W / perSpread, 720));
    const key = perSpread + 'x' + pw + 'x' + H; if (key === size) return; size = key;
    const atPage = spread * perSpread;
    restore(); const blocks = [...report.children]; report.replaceChildren(); pages = [];
    for (const el of [view, flipLayer]) { el.style.width = (pw * perSpread) + 'px'; el.style.setProperty('--nb-pw', pw + 'px'); el.style.setProperty('--nb-ph', (H - 58) + 'px'); }
    view.classList.toggle('nb-two', perSpread === 2);
    newPage();
    blocks.forEach((b) => place(b, () => cur.body));
    pages = pages.filter((p) => { const empty = !p.firstChild.children.length; if (empty) p.remove(); return !empty; });
    report.querySelectorAll('[data-nb-copy]').forEach((c) => { if (!c.children.length || (c.tagName === 'TABLE' && !c.querySelector('tbody tr'))) c.remove(); });
    pages.forEach((p, i) => { p.lastChild.textContent = String(i + 1); p.classList.add(i % 2 ? 'nb-right' : 'nb-left'); });
    spread = Math.min(Math.floor(atPage / perSpread), lastSpread());
    show(false);
  }
  function show(animate) {
    report.style.transition = animate ? '' : 'none';
    report.style.transform = 'translateX(' + (-spread * perSpread * pw) + 'px)';
    const first = spread * perSpread + 1, last = Math.min(pages.length, first + perSpread - 1);
    label.textContent = (first === last ? 'Page ' + first : 'Pages ' + first + '\u2013' + last) + ' of ' + pages.length;
    prev.disabled = spread === 0; next.disabled = spread >= lastSpread();
  }
  // 3D page turn: the turning leaf shows the old page on its front and the new page on its back,
  // hinged at the spine; the half it has not reached yet keeps the old page until it lands.
  function face(page) {
    const f = document.createElement('div'); f.className = 'nb-face';
    if (page) { const c = page.cloneNode(true); c.removeAttribute('id'); f.appendChild(c); }
    return f;
  }
  function flip(dir, target) {
    if (perSpread !== 2 || reduced) { spread = target; show(true); return; }
    const at = (s, i) => pages[s * 2 + i];
    const stay = face(dir > 0 ? at(spread, 0) : at(spread, 1)); stay.classList.add(dir > 0 ? 'nb-at-left' : 'nb-at-right');
    const leaf = document.createElement('div'); leaf.className = 'nb-leaf ' + (dir > 0 ? 'nb-at-right fwd' : 'nb-at-left back');
    const front = face(dir > 0 ? at(spread, 1) : at(spread, 0)), back = face(dir > 0 ? at(target, 0) : at(target, 1));
    back.classList.add('nb-back'); leaf.append(front, back);
    flipLayer.replaceChildren(stay, leaf);
    spread = target; show(false); busy = true;
    requestAnimationFrame(() => requestAnimationFrame(() => leaf.classList.add('turn')));
    setTimeout(() => { flipLayer.replaceChildren(); busy = false; }, 950);
  }
  function go(d, manual = true) {
    if (manual) setAuto(false);
    if (busy) return;
    const t = Math.min(lastSpread(), Math.max(0, spread + d));
    if (t !== spread) flip(d > 0 ? 1 : -1, t);
  }
  // Auto-turn: a page spread every few seconds; stops at the last page or when the reader turns a page.
  function setAuto(on) {
    clearInterval(autoTimer); autoTimer = 0;
    if (on && spread >= lastSpread()) { spread = 0; show(true); }
    if (on) autoTimer = setInterval(() => { if (spread >= lastSpread()) setAuto(false); else go(1, false); }, +speed.value * 1000);
    autoBtn.classList.toggle('on', on); autoBtn.setAttribute('aria-pressed', String(on));
    autoBtn.innerHTML = on ? '&#10074;&#10074; Pause' : '&#9654; Auto-turn';
  }
  autoBtn.addEventListener('click', () => setAuto(!autoTimer));
  speed.addEventListener('change', () => { if (autoTimer) setAuto(true); });
  bar.addEventListener('click', (e) => { const b = e.target.closest('button[data-go]'); if (b) go(+b.dataset.go); });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowRight' || e.key === 'PageDown') { go(1); e.preventDefault(); }
    if (e.key === 'ArrowLeft' || e.key === 'PageUp') { go(-1); e.preventDefault(); }
    if (e.key === ' ') { setAuto(!autoTimer); e.preventDefault(); }
    if (e.key === 'Home') { setAuto(false); spread = 0; show(true); }
    if (e.key === 'End') { setAuto(false); spread = lastSpread(); show(true); }
  });
  let x0 = null, wheelAt = 0;
  view.addEventListener('touchstart', (e) => { x0 = e.touches[0].clientX; }, { passive: true });
  view.addEventListener('touchend', (e) => { if (x0 === null) return; const dx = e.changedTouches[0].clientX - x0; if (Math.abs(dx) > 50) go(dx < 0 ? 1 : -1); x0 = null; });
  view.addEventListener('wheel', (e) => {
    if (e.target.closest('.nb-scroll')) return;
    e.preventDefault();
    const d = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
    if (Math.abs(d) < 20 || Date.now() - wheelAt < 450) return;
    wheelAt = Date.now(); go(d > 0 ? 1 : -1);
  }, { passive: false });
  // The report draws itself after load: lay out once it has stopped changing, and again when the
  // window size or the fonts change.
  let timer = 0, ready = false;
  const later = (force) => { if (!ready) return; clearTimeout(timer); timer = setTimeout(() => { if (force) size = ''; paginate(); }, 150); };
  let settleTimer = 0;
  const watcher = new MutationObserver(() => settle());
  function settle() {
    clearTimeout(settleTimer);
    settleTimer = setTimeout(() => { if (!report.children.length) return; watcher.disconnect(); ready = true; later(true); }, 400);
  }
  watcher.observe(report, { childList: true, subtree: true });
  settle();
  window.addEventListener('resize', () => later());
  if (document.fonts) document.fonts.ready.then(() => later(true));
})();
</script>
"""

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
def view_report(id: str, layout: Literal["standard", "notebook", "columns"] = "standard"):
    path = _file(id, "html")
    if layout == "columns":
        html = path.read_text(encoding="utf-8")
        return HTMLResponse(html.replace("</head>", COLUMNS_HEAD + "</head>", 1))
    if layout == "notebook":
        html = path.read_text(encoding="utf-8")
        html = html.replace("</head>", NOTEBOOK_HEAD + "</head>", 1).replace("</body>", NOTEBOOK_BODY + "</body>", 1)
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
