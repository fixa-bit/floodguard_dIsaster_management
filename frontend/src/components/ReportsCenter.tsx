import { AlertTriangle, CalendarClock, CheckCircle2, Download, ExternalLink, FileText, FlaskConical, Loader2, Plus, Radar, RefreshCw, Settings2, Sparkles, Trash2, Undo2, Waves, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { API_BASE_URL } from "../config";
import { apiFetch } from "../services/api";
import "../reports-center.css";

interface GeneratedReport {
  id: string;
  kind: "daily" | "event";
  title: string;
  file_name: string;
  size_bytes: number;
  created_at: string;
  generated?: string;
  is_test: boolean;
  has_simulated: boolean | null;
  headline: string | null;
  trigger?: "scheduled" | "manual";
  event_no?: string;
  version?: number;
  reason?: string;
  river?: string;
  level?: string;
  event_status?: "OPEN" | "CLOSED";
  event_peak?: string;
  ai?: AiSummary | null;
}
interface AiSummary { status: string; reason: string | null; review_mode: "none" | "label" | "portal"; trigger: string | null; notes: number; reviewed: number; to_review: number }
interface Flag {
  id: string; title: string; kind_label: string; simulated: boolean;
  measured: { label: string; value: string; detail?: string | null; time?: string | null };
  category: { label: string; rule: string; status_effect: string };
}
interface Explanation { status: string; note?: string; segments?: { text: string; cites: number[] }[]; sources?: { n: number; title: string; url?: string | null }[] }
interface AgentResult { status: string; note?: string | null; summary?: string; uncertainty?: { level: string } }
interface ReviewEntry { decision: "accepted" | "rejected"; note: string; reviewer: string; at: string }
interface AiDetail {
  id: string; title: string; flags: Flag[]; summary: AiSummary | null;
  ai_analysis: { status: string; reason?: string | null; review_mode: string; flags: Record<string, { explanation?: Explanation; agent?: AgentResult }> } | null;
  review: { flags: Record<string, ReviewEntry> };
}
interface ReportRef { id: string; file_name: string }
interface ReportJob {
  id: string;
  kind: "daily" | "event";
  label: string;
  status: "running" | "done" | "failed";
  message: string;
  reports: ReportRef[];
  error: string | null;
}
interface StationOption { id: string; name: string; river: string; impact_available: boolean }
interface Reading { station_id: string; category: string; discharge: number | null }
interface Scenario { id: string; name: string; description: string; signals: Reading[] }
interface ReportOptions {
  schedule: { enabled: boolean; time_pkt: string; next_run: string | null };
  watcher_enabled: boolean;
  stations: StationOption[];
  categories: string[];
  scenarios: Scenario[];
  open_test_events: { event_no: string; river: string; level: string; versions: number }[];
  test_flood_regions: { id: string; name: string }[];
}
interface EventGroup { eventNo: string; dir: string; river: string; peak: string; status: string; isTest: boolean; versions: GeneratedReport[] }

const fileUrl = (id: string, path: "view" | "download") => `${API_BASE_URL}/generated-reports/${path}?id=${encodeURIComponent(id)}`;
const when = (iso: string) => new Date(iso).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const day = (iso: string) => new Date(iso).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short", year: "numeric" });
const levelTone = (level = "") => /Very high|Exceptionally|High/.test(level) ? "crit" : /Medium/.test(level) ? "serious" : /Low/.test(level) ? "warn" : "watch";

export function ReportsCenter() {
  const [tab, setTab] = useState<"daily" | "events">("daily");
  const [reports, setReports] = useState<GeneratedReport[]>([]);
  const [options, setOptions] = useState<ReportOptions | null>(null);
  const [job, setJob] = useState<ReportJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showDailyOptions, setShowDailyOptions] = useState(false);
  const [daily, setDaily] = useState({ run_satellite: true, capture_snapshots: true, test_flood_region: "trimmu_jhang", ai_analysis: true, ai_review: "portal" as "portal" | "label" });
  const [reviewId, setReviewId] = useState<string | null>(null);
  const [eventView, setEventView] = useState<"real" | "test">("real");
  const [testOpen, setTestOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const [list, opts, jobs] = await Promise.all([
        apiFetch<GeneratedReport[]>("/generated-reports"),
        apiFetch<ReportOptions>("/generated-reports/options"),
        apiFetch<ReportJob[]>("/generated-reports/jobs"),
      ]);
      setReports(list);
      setOptions(opts);
      setJob((current) => current ?? jobs.find((j) => j.status === "running") ?? null);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load reports");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!job || job.status !== "running") return;
    const timer = window.setInterval(async () => {
      try {
        const next = await apiFetch<ReportJob>(`/generated-reports/jobs/${job.id}`);
        setJob(next);
        if (next.status !== "running") void load();
      } catch { /* keep polling */ }
    }, 3000);
    return () => window.clearInterval(timer);
  }, [job, load]);

  const running = job?.status === "running";
  const start = async (path: string, body: object) => {
    setError(null);
    try {
      setJob(await apiFetch<ReportJob>(path, { method: "POST", body: JSON.stringify(body) }));
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start report generation");
      return false;
    }
  };
  const remove = async (id: string, label: string) => {
    if (!window.confirm(`Delete ${label}? This cannot be undone.`)) return;
    try {
      await apiFetch(`/generated-reports?id=${encodeURIComponent(id)}`, { method: "DELETE" });
      void load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete");
    }
  };

  const dailyReports = useMemo(() => reports.filter((r) => r.kind === "daily"), [reports]);
  const groups = useMemo(() => {
    const map = new Map<string, EventGroup>();
    reports.filter((r) => r.kind === "event").forEach((r) => {
      const no = r.event_no ?? r.title;
      const g = map.get(no) ?? { eventNo: no, dir: r.id.split("/").slice(0, -1).join("/"), river: r.river ?? "", peak: r.event_peak ?? r.level ?? "", status: r.event_status ?? "", isTest: r.is_test, versions: [] };
      g.versions.push(r);
      map.set(no, g);
    });
    map.forEach((g) => g.versions.sort((a, b) => (a.version ?? 0) - (b.version ?? 0)));
    return [...map.values()].sort((a, b) => b.versions[b.versions.length - 1].created_at.localeCompare(a.versions[a.versions.length - 1].created_at));
  }, [reports]);
  const realGroups = groups.filter((g) => !g.isTest);
  const testGroups = groups.filter((g) => g.isTest);
  const shownGroups = eventView === "real" ? realGroups : testGroups;

  return (
    <div className="rp">
      <div className="rp-tabs" role="tablist" aria-label="Report type">
        <button type="button" role="tab" aria-selected={tab === "daily"} className={tab === "daily" ? "on" : ""} onClick={() => setTab("daily")}>
          <FileText size={18} /><span><b>Daily reports</b><small>National situation, every day</small></span><em>{dailyReports.length}</em>
        </button>
        <button type="button" role="tab" aria-selected={tab === "events"} className={tab === "events" ? "on" : ""} onClick={() => setTab("events")}>
          <Waves size={18} /><span><b>Flood event reports</b><small>One flood, from start to end</small></span><em>{groups.length}</em>
        </button>
      </div>

      {job && <JobBanner job={job} onClose={() => setJob(null)} />}
      {error && <div className="rp-banner rp-banner-failed" role="alert"><AlertTriangle size={16} /><span>{error}</span><button type="button" className="rp-icon" aria-label="Dismiss" onClick={() => setError(null)}><X size={14} /></button></div>}

      {tab === "daily" ? (
        <section className="rp-lane" aria-label="Daily reports">
          <header className="rp-head">
            <div>
              <h2>Daily Flood Situation Report</h2>
              <p>The national flood situation for the 24 hours ending 06:00 PKT: rivers, forecasts, rainfall, satellite and impact.</p>
              <div className="rp-facts">
                <span><CalendarClock size={14} />{options?.schedule.enabled ? <>Automatic every day at {options.schedule.time_pkt} PKT{options.schedule.next_run && <> · next {when(options.schedule.next_run)}</>}</> : "Automatic schedule is off"}</span>
              </div>
            </div>
            <div className="rp-head-actions">
              <button type="button" className={`rp-icon${showDailyOptions ? " on" : ""}`} aria-label="Generation options" aria-expanded={showDailyOptions} title="Generation options" onClick={() => setShowDailyOptions((v) => !v)}><Settings2 size={16} /></button>
              <button type="button" className="rp-primary" disabled={running} onClick={() => void start("/generated-reports/daily", { ...daily, test_flood_region: daily.test_flood_region || null })}><RefreshCw size={15} />Generate now</button>
            </div>
          </header>
          {showDailyOptions && (
            <div className="rp-options">
              <label className="rp-check"><input type="checkbox" checked={daily.run_satellite} onChange={(e) => setDaily({ ...daily, run_satellite: e.target.checked })} />Satellite checks <small>slower</small></label>
              <label className="rp-check"><input type="checkbox" checked={daily.capture_snapshots} onChange={(e) => setDaily({ ...daily, capture_snapshots: e.target.checked })} />Flood visuals from the portal</label>
              <label className="rp-inline">Simulated test flood
                <select value={daily.test_flood_region} onChange={(e) => setDaily({ ...daily, test_flood_region: e.target.value })}>
                  <option value="">None</option>
                  {(options?.test_flood_regions ?? []).map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                </select>
              </label>
              <label className="rp-check"><input type="checkbox" checked={daily.ai_analysis} onChange={(e) => setDaily({ ...daily, ai_analysis: e.target.checked })} />AI analysis of flagged signals <small>Claude</small></label>
              {daily.ai_analysis && (
                <label className="rp-inline">AI notes
                  <select value={daily.ai_review} onChange={(e) => setDaily({ ...daily, ai_review: e.target.value as "portal" | "label" })}>
                    <option value="portal">Review in portal</option>
                    <option value="label">Draft label only</option>
                  </select>
                </label>
              )}
              <p className="rp-hint rp-options-note">Scheduled reports always include AI analysis (when an API key is set) and publish it without human review.</p>
            </div>
          )}

          {loading ? <div className="rp-empty">Loading…</div> : dailyReports.length === 0 ? <div className="rp-empty">No daily reports yet. The first one is generated at the scheduled time, or press Generate now.</div> : (
            <ul className="rp-list">
              {dailyReports.map((r) => (
                <li key={r.id} className="rp-item">
                  <div className="rp-item-main">
                    <div className="rp-item-title"><b>{day(r.created_at)}</b><span className="rp-mono">{r.title}</span>
                      <span className={`rp-tag ${r.trigger === "scheduled" ? "rp-tag-auto" : ""}`}>{r.trigger === "scheduled" ? "Scheduled" : "Generated manually"}</span>
                      {r.has_simulated && <span className="rp-tag rp-tag-test">Includes simulated test</span>}
                      <AiTag ai={r.ai} />
                    </div>
                    {r.headline && <p>{r.headline}</p>}
                  </div>
                  <ReportActions id={r.id} ai={r.ai} onReview={() => setReviewId(r.id)} onDelete={() => void remove(r.id, r.title)} meta={`${r.generated ?? when(r.created_at)}`} />
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : (
        <section className="rp-lane" aria-label="Flood event reports">
          <header className="rp-head">
            <div>
              <h2>Flood Event Report</h2>
              <p>Issued automatically when river gauges, flood forecasts or models show a flood: when it starts, when it rises, and when it ends. The same flood at the same level never gets a second report.</p>
              <div className="rp-facts">
                <span><Radar size={14} />{options?.watcher_enabled ? "Automatic watch is on: checks after every river data update" : "Automatic watch is off"}</span>
              </div>
            </div>
            <div className="rp-head-actions">
              <button type="button" className="rp-secondary" disabled={running} onClick={() => void start("/generated-reports/flood-event", { mode: "real" })}>Check real data now</button>
              <button type="button" className="rp-primary" disabled={running} onClick={() => setTestOpen(true)}><FlaskConical size={15} />Test with a simulated flood</button>
            </div>
          </header>

          <div className="rp-seg" role="tablist" aria-label="Event source">
            <button type="button" role="tab" aria-selected={eventView === "real"} className={eventView === "real" ? "on" : ""} onClick={() => setEventView("real")}>Real floods <small>{realGroups.length}</small></button>
            <button type="button" role="tab" aria-selected={eventView === "test"} className={eventView === "test" ? "on" : ""} onClick={() => setEventView("test")}>Tests <small>{testGroups.length}</small></button>
          </div>

          {loading ? <div className="rp-empty">Loading…</div> : shownGroups.length === 0 ? (
            <div className="rp-empty">{eventView === "real" ? "No real flood events. Reports appear here automatically when a flood is detected." : "No test events. Use “Test with a simulated flood” to try the report."}</div>
          ) : (
            <div className="rp-events">
              {shownGroups.map((g) => (
                <article key={g.eventNo} className="rp-event">
                  <header>
                    <div className="rp-event-title">
                      <h3>{g.river} flood</h3>
                      <button type="button" className="rp-icon rp-danger" aria-label={`Delete ${g.eventNo}`} title="Delete this event and all its reports" onClick={() => void remove(g.dir, `${g.eventNo} and all its reports`)}><Trash2 size={14} /></button>
                    </div>
                    <div className="rp-event-state">
                      <span className={`rp-level rp-level-${levelTone(g.peak)}`}>{g.peak || "—"}</span>
                      <span className={`rp-status ${g.status === "OPEN" ? "open" : ""}`}>{g.status === "OPEN" ? "Ongoing" : "Closed"}</span>
                      {g.isTest && <span className="rp-tag rp-tag-test">Test</span>}
                      <span className="rp-mono">{g.eventNo}</span>
                    </div>
                  </header>
                  <ol className="rp-versions">
                    {g.versions.map((v) => (
                      <li key={v.id}>
                        <span className="rp-dot" aria-hidden="true" />
                        <div className="rp-version-text"><b>{v.reason}</b><span>{v.level} · {v.generated ?? when(v.created_at)}</span><AiTag ai={v.ai} /></div>
                        <ReportActions id={v.id} ai={v.ai} onReview={() => setReviewId(v.id)} compact />
                      </li>
                    ))}
                  </ol>
                </article>
              ))}
            </div>
          )}
        </section>
      )}

      {reviewId && <ReviewDialog reportId={reviewId} onClose={() => setReviewId(null)} onChanged={() => void load()} />}

      {testOpen && options && (
        <TestDialog
          options={options}
          running={running}
          onClose={() => setTestOpen(false)}
          onRun={async (body) => { if (await start("/generated-reports/flood-event", body)) { setTestOpen(false); setEventView("test"); } }}
        />
      )}
    </div>
  );
}

function AiTag({ ai }: { ai?: AiSummary | null }) {
  if (!ai || ai.status === "no_flags") return null;
  if (!ai.notes) {
    const why = ai.status === "pending" || ai.status === "running" ? "AI analysis did not finish" : ai.reason || "AI analysis not run";
    return ai.status === "off" ? null : <span className="rp-tag" title={why}>AI not run</span>;
  }
  const text = ai.review_mode === "none" ? "automatic" : ai.review_mode === "label" ? "draft" : ai.to_review ? `${ai.to_review} to review` : "reviewed";
  const cls = ai.review_mode === "portal" && ai.to_review ? "rp-tag rp-tag-ai rp-tag-due" : "rp-tag rp-tag-ai";
  return <span className={cls}><Sparkles size={11} />AI notes: {ai.notes} · {text}</span>;
}

function ReportActions({ id, meta, compact, onDelete, ai, onReview }: { id: string; meta?: string; compact?: boolean; onDelete?: () => void; ai?: AiSummary | null; onReview?: () => void }) {
  const canReview = !!ai && ai.notes > 0 && !!onReview;
  return (
    <div className="rp-actions">
      {meta && <span className="rp-meta">{meta}</span>}
      {canReview && <button type="button" className={`rp-btn${ai!.review_mode === "portal" && ai!.to_review ? " rp-btn-due" : ""}`} onClick={onReview}><Sparkles size={14} />Review</button>}
      <a className="rp-btn" href={fileUrl(id, "view")} target="_blank" rel="noreferrer"><ExternalLink size={14} />Open</a>
      <a className="rp-icon" href={fileUrl(id, "download")} download aria-label="Download" title="Download"><Download size={14} /></a>
      {!compact && onDelete && <button type="button" className="rp-icon rp-danger" aria-label="Delete" title="Delete" onClick={onDelete}><Trash2 size={14} /></button>}
    </div>
  );
}

function JobBanner({ job, onClose }: { job: ReportJob; onClose: () => void }) {
  return (
    <div className={`rp-banner rp-banner-${job.status}`} role="status" aria-live="polite">
      {job.status === "running" ? <Loader2 size={17} className="spinning" /> : job.status === "done" ? <CheckCircle2 size={17} /> : <AlertTriangle size={17} />}
      <span><b>{job.label}</b> {job.status === "running" ? "is being generated. This can take a few minutes." : job.error ?? job.message}</span>
      {job.reports.map((r) => <a key={r.id} className="rp-btn" href={fileUrl(r.id, "view")} target="_blank" rel="noreferrer"><ExternalLink size={14} />Open report</a>)}
      {job.status !== "running" && <button type="button" className="rp-icon" aria-label="Dismiss" onClick={onClose}><X size={14} /></button>}
    </div>
  );
}

function TestDialog({ options, running, onClose, onRun }: { options: ReportOptions; running: boolean; onClose: () => void; onRun: (body: object) => void }) {
  const [source, setSource] = useState<"scenario" | "manual">("scenario");
  const [scenarioId, setScenarioId] = useState(options.scenarios[0]?.id ?? "");
  const [readings, setReadings] = useState<Reading[]>([{ station_id: "TRIMMU", category: "High flood", discharge: 9500 }]);
  const [mode, setMode] = useState<"new" | "continue">("new");
  const [satellite, setSatellite] = useState(true);
  const [ai, setAi] = useState(false);
  const [aiReview, setAiReview] = useState<"portal" | "label">("portal");
  const [visuals, setVisuals] = useState(true);
  const dialog = useRef<HTMLDivElement>(null);
  const scenario = options.scenarios.find((s) => s.id === scenarioId);
  const openTest = options.open_test_events[0];
  const name = (id: string) => options.stations.find((s) => s.id === id)?.name ?? id;
  const update = (i: number, patch: Partial<Reading>) => setReadings((rows) => rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  useEffect(() => {
    dialog.current?.querySelector<HTMLElement>("select, button")?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const run = (m: "new" | "continue" | "close") => onRun({
    mode: m,
    scenario_id: m !== "close" && source === "scenario" ? scenarioId : null,
    signals: m !== "close" && source === "manual" ? readings : [],
    run_satellite: satellite,
    capture_snapshots: visuals,
    ai_analysis: ai,
    ai_review: aiReview,
  });

  return (
    <div className="rp-modal" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="rp-dialog" role="dialog" aria-modal="true" aria-labelledby="rp-test-title" ref={dialog}>
        <header>
          <div><h2 id="rp-test-title">Test with a simulated flood</h2><p>Simulated gauge readings go through the real trigger and produce a report marked TEST.</p></div>
          <button type="button" className="rp-icon" aria-label="Close" onClick={onClose}><X size={16} /></button>
        </header>

        <div className="rp-step">
          <h3><span>1</span>Where is the flood?</h3>
          <div className="rp-seg">
            <button type="button" className={source === "scenario" ? "on" : ""} aria-pressed={source === "scenario"} onClick={() => setSource("scenario")}>Ready-made scenario</button>
            <button type="button" className={source === "manual" ? "on" : ""} aria-pressed={source === "manual"} onClick={() => setSource("manual")}>Set it up myself</button>
          </div>
          {source === "scenario" ? (
            <div className="rp-stack">
              <select aria-label="Scenario" value={scenarioId} onChange={(e) => setScenarioId(e.target.value)}>
                {options.scenarios.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
              {scenario && <p className="rp-hint">{scenario.description} Readings: {scenario.signals.map((s) => `${name(s.station_id)} ${s.category}`).join(", ")}.</p>}
            </div>
          ) : (
            <div className="rp-stack">
              {readings.map((row, i) => (
                <div className="rp-reading" key={i}>
                  <select aria-label="Station" value={row.station_id} onChange={(e) => update(i, { station_id: e.target.value })}>
                    {options.stations.map((s) => <option key={s.id} value={s.id}>{s.river}: {s.name}{s.impact_available ? " ●" : ""}</option>)}
                  </select>
                  <select aria-label="Flood category" value={row.category} onChange={(e) => update(i, { category: e.target.value })}>
                    {options.categories.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                  <input aria-label="Discharge in cumecs" type="number" min={0} step={100} placeholder="Cumecs (optional)" value={row.discharge ?? ""} onChange={(e) => update(i, { discharge: e.target.value === "" ? null : Number(e.target.value) })} />
                  <button type="button" className="rp-icon" aria-label="Remove station" disabled={readings.length === 1} onClick={() => setReadings((rows) => rows.filter((_, j) => j !== i))}><X size={14} /></button>
                </div>
              ))}
              <button type="button" className="rp-link" onClick={() => setReadings((rows) => [...rows, { station_id: "PANJNAD", category: "Low flood", discharge: null }])}><Plus size={14} />Add a station</button>
              <p className="rp-hint">● Station with population data: the report can estimate people affected.</p>
            </div>
          )}
        </div>

        <div className="rp-step">
          <h3><span>2</span>New test or continue?</h3>
          <div className="rp-choice">
            <label><input type="radio" name="rp-mode" checked={mode === "new"} onChange={() => setMode("new")} /><span><b>Start a new test flood</b><small>Gives the first report of a new event.</small></span></label>
            <label className={!openTest ? "disabled" : ""}><input type="radio" name="rp-mode" disabled={!openTest} checked={mode === "continue"} onChange={() => setMode("continue")} /><span><b>Continue {openTest ? openTest.event_no : "the open test"}</b><small>{openTest ? `Now at ${openTest.level}. A report is issued only if the level rises.` : "No open test flood."}</small></span></label>
          </div>
        </div>

        <details className="rp-more">
          <summary>Report options</summary>
          <label className="rp-check"><input type="checkbox" checked={satellite} onChange={(e) => setSatellite(e.target.checked)} />Satellite checks <small>slower</small></label>
          <label className="rp-check"><input type="checkbox" checked={visuals} onChange={(e) => setVisuals(e.target.checked)} />Flood visuals from the portal</label>
          <label className="rp-check"><input type="checkbox" checked={ai} onChange={(e) => setAi(e.target.checked)} />AI analysis of the flagged signal <small>Claude, uses API credit</small></label>
          {ai && (
            <label className="rp-inline">AI notes
              <select value={aiReview} onChange={(e) => setAiReview(e.target.value as "portal" | "label")}>
                <option value="portal">Review in portal</option>
                <option value="label">Draft label only</option>
              </select>
            </label>
          )}
        </details>

        <footer>
          {openTest && <button type="button" className="rp-secondary" disabled={running} onClick={() => run("close")} title="Issues the closure report">End {openTest.event_no}</button>}
          <span />
          <button type="button" className="rp-secondary" onClick={onClose}>Cancel</button>
          <button type="button" className="rp-primary" disabled={running} onClick={() => run(mode)}><FlaskConical size={15} />Generate test report</button>
        </footer>
      </div>
    </div>
  );
}

function ReviewDialog({ reportId, onClose, onChanged }: { reportId: string; onClose: () => void; onChanged: () => void }) {
  const [detail, setDetail] = useState<AiDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [reviewer, setReviewer] = useState(() => { try { return window.localStorage.getItem("floodguard.reviewer") ?? ""; } catch { return ""; } });
  const dialog = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try { setDetail(await apiFetch<AiDetail>(`/generated-reports/ai?id=${encodeURIComponent(reportId)}`)); setError(null); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not load the AI notes"); }
  }, [reportId]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    dialog.current?.querySelector<HTMLElement>("input, button")?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const decide = async (flagId: string, decision: "accepted" | "rejected") => {
    if (!reviewer.trim()) { setError("Enter your name first."); return; }
    try { window.localStorage.setItem("floodguard.reviewer", reviewer.trim()); } catch { /* per-browser convenience only */ }
    setBusy(flagId);
    try {
      await apiFetch(`/generated-reports/review`, { method: "POST", body: JSON.stringify({ id: reportId, flag_id: flagId, decision, note: notes[flagId] ?? "", reviewer: reviewer.trim() }) });
      await load(); onChanged(); setError(null);
    } catch (err) { setError(err instanceof Error ? err.message : "Could not save the review"); }
    finally { setBusy(null); }
  };
  const undo = async (flagId: string) => {
    setBusy(flagId);
    try { await apiFetch(`/generated-reports/review?id=${encodeURIComponent(reportId)}&flag_id=${flagId}`, { method: "DELETE" }); await load(); onChanged(); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not undo"); }
    finally { setBusy(null); }
  };

  const ai = detail?.ai_analysis;
  const items = (detail?.flags ?? []).filter((f) => { const e = ai?.flags?.[f.id]; return e && ((e.explanation?.status === "complete") || (e.agent && ["complete", "incomplete"].includes(e.agent.status))); });
  const modeText = ai?.review_mode === "none" ? "Automatic report: these notes were published without human review. You can still review them."
    : ai?.review_mode === "label" ? "These notes were published as drafts. Reviewing them is optional." : "These notes need a review before they are relied on.";

  return (
    <div className="rp-modal" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="rp-dialog rp-review" role="dialog" aria-modal="true" aria-labelledby="rp-review-title" ref={dialog}>
        <header>
          <div><h2 id="rp-review-title">Review AI notes{detail ? ` · ${detail.title}` : ""}</h2><p>{modeText} Accepting or rejecting a note never changes the report's measured values, categories or status.</p></div>
          <button type="button" className="rp-icon" aria-label="Close" onClick={onClose}><X size={16} /></button>
        </header>
        <label className="rp-inline rp-reviewer">Your name
          <input type="text" value={reviewer} maxLength={80} placeholder="e.g. Duty officer, PEOC" onChange={(e) => setReviewer(e.target.value)} />
        </label>
        <p className="rp-hint">The portal has no sign-in, so this name is what the report will show as the reviewer.</p>
        {error && <div className="rp-banner rp-banner-failed" role="alert"><AlertTriangle size={16} /><span>{error}</span></div>}
        {!detail ? <div className="rp-empty">Loading…</div> : items.length === 0 ? <div className="rp-empty">This report has no AI notes.</div> : (
          <div className="rp-review-list">
            {items.map((f) => {
              const entry = ai!.flags[f.id]; const ex = entry.explanation; const ag = entry.agent; const r = detail.review.flags?.[f.id];
              return (
                <article key={f.id} className={`rp-review-item${r ? ` is-${r.decision}` : ""}`}>
                  <header><span className="rp-mono">{f.id}</span><b>{f.title}</b>{f.simulated && <span className="rp-tag rp-tag-test">Simulated</span>}</header>
                  <div className="rp-facts-grid">
                    <div><span>Measured value · code</span><b>{f.measured.value}</b><small>{f.measured.label}{f.measured.detail ? ` · ${f.measured.detail}` : ""}</small></div>
                    <div><span>Risk category · FloodGuard rule</span><b>{f.category.label}</b><small>{f.category.status_effect}</small></div>
                  </div>
                  <div className="rp-ai-note">
                    <span className="rp-ai-label"><Sparkles size={12} />AI explanation · draft</span>
                    {ex?.status === "complete" ? <p>{(ex.segments ?? []).map((seg, i) => <span key={i}>{seg.text}{seg.cites.map((n) => <sup key={n}>[{n}]</sup>)}</span>)}</p> : <p className="rp-hint">{ex?.note ?? "No explanation."}</p>}
                    {(ex?.sources ?? []).length > 0 && <ol className="rp-sources">{ex!.sources!.map((s) => <li key={s.n}>{s.url ? <a href={s.url} target="_blank" rel="noreferrer">{s.title}</a> : s.title}</li>)}</ol>}
                    {ag?.summary && <p><b>Deeper analysis:</b> {ag.summary} {ag.uncertainty ? <span className="rp-hint">Uncertainty: {ag.uncertainty.level}.</span> : null}</p>}
                    <a className="rp-link" href={`${fileUrl(reportId, "view")}#flag-${f.id}`} target="_blank" rel="noreferrer"><ExternalLink size={13} />Full analysis and sources in the report</a>
                  </div>
                  {r ? (
                    <div className={`rp-decision rp-decision-${r.decision}`}>
                      {r.decision === "accepted" ? <CheckCircle2 size={15} /> : <X size={15} />}
                      <span>{r.decision === "accepted" ? "Accepted" : "Rejected"} by {r.reviewer}, {when(r.at)}{r.note ? `: ${r.note}` : ""}</span>
                      <button type="button" className="rp-link" disabled={busy === f.id} onClick={() => void undo(f.id)}><Undo2 size={13} />Undo</button>
                    </div>
                  ) : (
                    <div className="rp-decide">
                      <input type="text" aria-label={`Note for ${f.id}`} placeholder="Note (optional), e.g. confirmed with FFD" maxLength={1000} value={notes[f.id] ?? ""} onChange={(e) => setNotes({ ...notes, [f.id]: e.target.value })} />
                      <button type="button" className="rp-secondary" disabled={busy === f.id} onClick={() => void decide(f.id, "rejected")}><X size={14} />Reject</button>
                      <button type="button" className="rp-primary" disabled={busy === f.id} onClick={() => void decide(f.id, "accepted")}><CheckCircle2 size={14} />Accept</button>
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        )}
        <footer><span /><button type="button" className="rp-secondary" onClick={onClose}>Done</button></footer>
      </div>
    </div>
  );
}
