import { AlertTriangle, BellRing, CheckCircle2, CircleDashed, ExternalLink, History, Loader2, Mail, MessageCircle, Plus, RefreshCw, Hash, Send, ShieldCheck, Trash2, Users, Workflow, XCircle, Zap } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, apiFetch } from "../services/api";
import "../alarm-automation.css";

/* The n8n flood alarm workflow, seen and edited from FloodGuard (backend: /api/v1/alarm-automation). */

interface Status { connected: boolean; message: string | null; editor_url: string; workflow_url?: string; active?: boolean; workflow_name: string }
interface Layout {
  id: string; name: string; active: boolean;
  triggers: { name: string; type: string }[];
  blocks: { name: string; description: string; nodes: { name: string; type: string; disabled: boolean }[] }[];
  links: { from: string; to: string }[];
}
interface RunNode { name: string; block: string | null; status: string; items: number; ms: number; error: string | null }
interface Run { id: string; status: string; mode: string; trigger: string | null; started_at: string | null; stopped_at: string | null; blocks: Record<string, string>; nodes: RunNode[] }
type Row = Record<string, string | number | boolean | null> & { id: number };

const BASE = "/alarm-automation";
const TABS = [
  { id: "flow", label: "Live flow", icon: Workflow },
  { id: "runs", label: "Runs", icon: History },
  { id: "roster", label: "Duty roster", icon: Users },
  { id: "channels", label: "Alert channels", icon: BellRing },
  { id: "alarms", label: "Alarms", icon: AlertTriangle },
  { id: "log", label: "Delivery & audit log", icon: ShieldCheck },
] as const;
type TabId = (typeof TABS)[number]["id"];

const send = <T,>(path: string, method: string, body?: unknown) =>
  apiFetch<T>(`${BASE}${path}`, { method, body: body === undefined ? undefined : JSON.stringify(body) });
const errorText = (error: unknown) => (error instanceof ApiError || error instanceof Error ? error.message : "Something went wrong");
const when = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString([], { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—");
const seconds = (run: Run) => (run.started_at && run.stopped_at ? `${((+new Date(run.stopped_at) - +new Date(run.started_at)) / 1000).toFixed(1)} s` : "running");

function StatusIcon({ status }: { status?: string }) {
  if (status === "success") return <CheckCircle2 size={15} className="aa-ok" />;
  if (status === "error" || status === "crashed") return <XCircle size={15} className="aa-bad" />;
  if (status === "running" || status === "waiting" || status === "new") return <Loader2 size={15} className="aa-spin" />;
  return <CircleDashed size={15} className="aa-idle" />;
}

export function AlarmAutomation() {
  const [tab, setTab] = useState<TabId>("flow");
  const [status, setStatus] = useState<Status | null>(null);
  const [layout, setLayout] = useState<Layout | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadRuns = useCallback(async () => {
    try {
      const result = await apiFetch<{ runs: Run[] }>(`${BASE}/runs?limit=25`);
      setRuns(result.runs);
      setError(null);
    } catch (e) { setError(errorText(e)); }
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const s = await apiFetch<Status>(`${BASE}/status`);
        setStatus(s);
        if (!s.connected) return;
        setLayout(await apiFetch<Layout>(`${BASE}/workflow`));
        await loadRuns();
      } catch (e) { setError(errorText(e)); }
    })();
  }, [loadRuns]);

  // Live: check for new runs every 4 s while the flow or runs tab is open.
  useEffect(() => {
    if (!status?.connected || (tab !== "flow" && tab !== "runs")) return;
    const timer = window.setInterval(() => void loadRuns(), 4000);
    return () => window.clearInterval(timer);
  }, [status?.connected, tab, loadRuns]);

  const run = runs.find((r) => r.id === runId) ?? runs[0];

  if (status && !status.connected) {
    return (
      <div className="aa">
        <section className="aa-card aa-offline">
          <AlertTriangle size={22} />
          <div><h2>n8n is not connected</h2><p>{status.message}</p><p>Start n8n (<code>automation/n8n/start-n8n-docker.ps1</code>) and check <code>N8N_API_KEY</code> in the backend <code>.env</code>.</p></div>
        </section>
      </div>
    );
  }

  return (
    <div className="aa">
      <header className="aa-card aa-head">
        <div>
          <h2><Workflow size={18} /> {layout?.name ?? status?.workflow_name ?? "Flood alarm workflow"}</h2>
          <p>Forecasts from the portal become alarms; on-duty officers are alerted on Slack, Gmail and WhatsApp, and unacknowledged alarms escalate District → PDMA → NDMA.</p>
          <div className="aa-facts">
            <span className={status?.active ? "on" : "off"}>{status?.active ? "Published: running" : status ? "Not published" : "Connecting…"}</span>
            {run && <span>Last run {when(run.started_at)} · {run.trigger ?? run.mode}</span>}
          </div>
        </div>
        <div className="aa-head-actions">
          <TestForecast onSent={(text) => { setNotice(text); setTab("flow"); setRunId(null); window.setTimeout(() => void loadRuns(), 1500); }} />
          {status?.workflow_url && <a className="secondary-button aa-link" href={status.workflow_url} target="_blank" rel="noreferrer"><ExternalLink size={14} /> Open in n8n</a>}
        </div>
      </header>

      {error && <div className="aa-msg bad"><AlertTriangle size={15} /> {error}</div>}
      {notice && <div className="aa-msg" onClick={() => setNotice(null)}><CheckCircle2 size={15} /> {notice}</div>}

      <nav className="aa-tabs">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button key={id} type="button" className={tab === id ? "on" : ""} onClick={() => setTab(id)}><Icon size={15} /> {label}</button>
        ))}
      </nav>

      {tab === "flow" && <LiveFlow layout={layout} run={run} runs={runs} onPick={setRunId} />}
      {tab === "runs" && <RunList runs={runs} selected={run?.id} onOpen={(id) => { setRunId(id); setTab("flow"); }} />}
      {tab === "roster" && <RosterEditor />}
      {tab === "channels" && <ChannelEditor />}
      {tab === "alarms" && <AlarmList />}
      {tab === "log" && <LogView />}
    </div>
  );
}

/* ---- live flow: the workflow's blocks, coloured by the selected run ------------ */
function LiveFlow({ layout, run, runs, onPick }: { layout: Layout | null; run?: Run; runs: Run[]; onPick: (id: string) => void }) {
  const [open, setOpen] = useState<string | null>(null);
  // Columns by distance from the triggers, following the workflow's links.
  const columns = useMemo(() => {
    if (!layout) return [] as string[][];
    const depth = new Map<string, number>(layout.triggers.map((t) => [t.name, 0]));
    for (let pass = 0; pass < 12; pass += 1) {
      for (const link of layout.links) {
        const d = depth.get(link.from);
        if (d !== undefined && link.to !== link.from && (depth.get(link.to) ?? -1) < d + 1 && d + 1 < 10) depth.set(link.to, d + 1);
      }
    }
    const cols: string[][] = [];
    for (const block of layout.blocks) { const d = depth.get(block.name) ?? 1; (cols[d] ??= []).push(block.name); }
    return [layout.triggers.map((t) => t.name), ...cols.slice(1).filter(Boolean)];
  }, [layout]);
  if (!layout) return <div className="aa-card aa-loading"><Loader2 size={18} className="aa-spin" /> Loading the workflow…</div>;
  const triggerNames = new Set(layout.triggers.map((t) => t.name));
  const blockOf = (name: string) => layout.blocks.find((b) => b.name === name);
  const nodeRun = (name: string) => run?.nodes.find((n) => n.name === name);

  return (
    <section className="aa-card">
      <div className="aa-flow-bar">
        <label>Showing run <select value={run?.id ?? ""} onChange={(e) => onPick(e.target.value)}>
          {runs.map((r) => <option key={r.id} value={r.id}>#{r.id} · {when(r.started_at)} · {r.trigger ?? r.mode} · {r.status}</option>)}
        </select></label>
        <span className="aa-legend"><span><CheckCircle2 size={13} className="aa-ok" /> ran</span><span><XCircle size={13} className="aa-bad" /> failed</span><span><CircleDashed size={13} className="aa-idle" /> not used in this run</span><span><Loader2 size={13} /> new runs appear by themselves</span></span>
      </div>
      <div className="aa-flow">
        {columns.map((col, i) => (
          <div className="aa-col" key={i}>
            {col.map((name) => {
              const isTrigger = triggerNames.has(name);
              const state = isTrigger ? (run?.trigger === name ? "success" : undefined) : run?.blocks[name];
              const block = blockOf(name);
              return (
                <button type="button" key={name} className={`aa-block ${isTrigger ? "trigger" : ""} ${state ?? "idle"} ${open === name ? "open" : ""}`}
                  onClick={() => setOpen(open === name ? null : name)} title={block?.description}>
                  <span className="aa-block-title">{isTrigger ? <Zap size={14} /> : <StatusIcon status={state} />} {name}</span>
                  {block && <small>{block.nodes.length} nodes{block.nodes.some((n) => n.disabled) ? " · some switched off" : ""}</small>}
                  {open === name && block && (
                    <ul>
                      <li className="aa-desc">{block.description}</li>
                      {block.nodes.map((n) => {
                        const r = nodeRun(n.name);
                        return (
                          <li key={n.name} className={r?.status ?? "idle"}>
                            <StatusIcon status={r?.status} /> <b>{n.name}</b>
                            <em>{n.disabled ? "switched off" : r ? `${r.items} items · ${r.ms} ms` : "—"}</em>
                            {r?.error && <span className="aa-err">{r.error}</span>}
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </button>
              );
            })}
          </div>
        ))}
      </div>
    </section>
  );
}

function RunList({ runs, selected, onOpen }: { runs: Run[]; selected?: string; onOpen: (id: string) => void }) {
  return (
    <section className="aa-card aa-table-wrap">
      <table className="data-table aa-table">
        <thead><tr><th>Run</th><th>Started</th><th>Started by</th><th>Status</th><th>Time</th><th>Blocks</th><th>Nodes</th><th /></tr></thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id} className={r.id === selected ? "sel" : ""}>
              <td>#{r.id}</td><td>{when(r.started_at)}</td><td>{r.trigger ?? r.mode}</td>
              <td><span className={`aa-pill ${r.status}`}><StatusIcon status={r.status} /> {r.status}</span></td>
              <td>{seconds(r)}</td><td>{Object.keys(r.blocks).length}</td><td>{r.nodes.length}{r.nodes.some((n) => n.error) ? " (errors)" : ""}</td>
              <td><button type="button" className="secondary-button" onClick={() => onOpen(r.id)}>View flow</button></td>
            </tr>
          ))}
          {!runs.length && <tr><td colSpan={8}>No runs yet.</td></tr>}
        </tbody>
      </table>
    </section>
  );
}

/* ---- test forecast ------------------------------------------------------------- */
function TestForecast({ onSent }: { onSent: (text: string) => void }) {
  const [risk, setRisk] = useState("High");
  const [busy, setBusy] = useState(false);
  return (
    <div className="aa-test">
      <select value={risk} onChange={(e) => setRisk(e.target.value)} aria-label="Test forecast risk">
        {["Moderate", "High", "Very high", "Extreme", "Normal"].map((r) => <option key={r}>{r}</option>)}
      </select>
      <button type="button" className="primary-button" disabled={busy} onClick={async () => {
        setBusy(true);
        try {
          const reply = await send<{ alarms?: { action: string; level_name: string }[]; alerts_sent?: number }>("/test-forecast", "POST", { risk_class: risk, probability: risk === "Normal" ? 0.05 : 0.7 });
          const a = reply.alarms?.[0];
          onSent(`Test forecast sent: ${a ? `${a.level_name} → ${a.action}` : "accepted"}, ${reply.alerts_sent ?? 0} alert(s). Watch it run below.`);
        } catch (e) { onSent(`Test forecast failed: ${errorText(e)}`); } finally { setBusy(false); }
      }}>{busy ? <Loader2 size={14} className="aa-spin" /> : <Send size={14} />} Send test forecast</button>
    </div>
  );
}

/* ---- data tables ------------------------------------------------------------------ */
function useTable(table: string, alarmId?: string) {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      const q = alarmId ? `?alarm_id=${encodeURIComponent(alarmId)}&limit=100` : "?limit=200";
      setRows((await apiFetch<{ rows: Row[] }>(`${BASE}/tables/${table}${q}`)).rows);
      setError(null);
    } catch (e) { setError(errorText(e)); }
  }, [table, alarmId]);
  useEffect(() => { void load(); }, [load]);
  return { rows, setRows, error, setError, load };
}

const TIERS: Record<number, string> = { 1: "1 · District", 2: "2 · PDMA", 3: "3 · NDMA" };

function RosterEditor() {
  const { rows, setRows, error, setError, load } = useTable("duty_roster");
  const [saving, setSaving] = useState<number | null>(null);
  const [confirm, setConfirm] = useState<number | null>(null);
  const [draft, setDraft] = useState({ name: "", role: "", tier: 1, email: "", whatsapp: "" });

  const save = async (row: Row, change: Record<string, unknown>) => {
    setSaving(row.id);
    try {
      const updated = await send<Row>(`/duty-roster/${row.id}`, "PATCH", change);
      setRows((all) => all?.map((r) => (r.id === row.id ? { ...r, ...updated } : r)) ?? null);
      setError(null);
    } catch (e) { setError(errorText(e)); void load(); } finally { setSaving(null); }
  };
  const text = (row: Row, key: string) => (
    <input defaultValue={String(row[key] ?? "")} onBlur={(e) => { if (e.target.value !== String(row[key] ?? "")) void save(row, { [key]: e.target.value }); }} />
  );
  const toggle = (row: Row, key: string, disabled = false) => (
    <input type="checkbox" checked={Boolean(row[key])} disabled={disabled || saving === row.id} onChange={(e) => void save(row, { [key]: e.target.checked })} />
  );

  return (
    <section className="aa-card">
      <p className="aa-help">Who gets email and WhatsApp alerts. A person is alerted on a channel only when they are <b>on duty</b>, their own toggle for it is on, and the channel is on for the alarm level. Changes apply to the next alert.</p>
      {error && <div className="aa-msg bad">{error}</div>}
      <div className="aa-table-wrap">
        <table className="data-table aa-table aa-edit">
          <thead><tr><th>On duty</th><th>Name</th><th>Role</th><th>Tier</th><th><Mail size={12} /> Email</th><th>Gmail</th><th><MessageCircle size={12} /> WhatsApp</th><th>WhatsApp</th><th>Notes</th><th /></tr></thead>
          <tbody>
            {rows?.map((row) => (
              <tr key={row.id} className={row.on_duty ? "" : "off"}>
                <td>{toggle(row, "on_duty")}</td>
                <td>{text(row, "name")}</td><td>{text(row, "role")}</td>
                <td><select value={Number(row.tier)} onChange={(e) => void save(row, { tier: Number(e.target.value) })}>{[1, 2, 3].map((t) => <option key={t} value={t}>{TIERS[t]}</option>)}</select></td>
                <td>{text(row, "email")}</td><td>{toggle(row, "gmail_on", !row.email)}</td>
                <td>{text(row, "whatsapp")}</td><td>{toggle(row, "whatsapp_on", !row.whatsapp)}</td>
                <td>{text(row, "notes")}</td>
                <td>{confirm === row.id
                  ? <span className="aa-confirm">Remove? <button type="button" className="secondary-button" onClick={async () => { try { await send(`/duty-roster/${row.id}`, "DELETE"); setConfirm(null); void load(); } catch (e) { setError(errorText(e)); } }}>Yes</button><button type="button" className="secondary-button" onClick={() => setConfirm(null)}>No</button></span>
                  : <button type="button" className="icon-button" title="Remove person" aria-label="Remove person" onClick={() => setConfirm(row.id)}><Trash2 size={14} /></button>}</td>
              </tr>
            ))}
            {rows === null && <tr><td colSpan={10}><Loader2 size={14} className="aa-spin" /> Loading…</td></tr>}
          </tbody>
        </table>
      </div>
      <form className="aa-add" onSubmit={async (e) => {
        e.preventDefault();
        try { await send("/duty-roster", "POST", draft); setDraft({ name: "", role: "", tier: 1, email: "", whatsapp: "" }); void load(); } catch (err) { setError(errorText(err)); }
      }}>
        <b><Plus size={14} /> Add person</b>
        <input required placeholder="Name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
        <input placeholder="Role" value={draft.role} onChange={(e) => setDraft({ ...draft, role: e.target.value })} />
        <select value={draft.tier} onChange={(e) => setDraft({ ...draft, tier: Number(e.target.value) })}>{[1, 2, 3].map((t) => <option key={t} value={t}>{TIERS[t]}</option>)}</select>
        <input type="email" placeholder="Email" value={draft.email} onChange={(e) => setDraft({ ...draft, email: e.target.value })} />
        <input placeholder="WhatsApp (+92…)" value={draft.whatsapp} onChange={(e) => setDraft({ ...draft, whatsapp: e.target.value })} />
        <button type="submit" className="primary-button">Add</button>
      </form>
    </section>
  );
}

function ChannelEditor() {
  const { rows, setRows, error, setError } = useTable("alert_channels");
  const save = async (row: Row, key: string, value: boolean) => {
    try {
      const updated = await send<Row>(`/alert-channels/${row.id}`, "PATCH", { [key]: value });
      setRows((all) => all?.map((r) => (r.id === row.id ? { ...r, ...updated } : r)) ?? null);
    } catch (e) { setError(errorText(e)); }
  };
  return (
    <section className="aa-card">
      <p className="aa-help">Which channels each alarm level alerts on. Level 0 is the all-clear sent when an alarm closes. Gmail and WhatsApp also need the person's own toggle in the duty roster.</p>
      {error && <div className="aa-msg bad">{error}</div>}
      <table className="data-table aa-table aa-channels">
        <thead><tr><th>Level</th><th><Hash size={12} /> Slack</th><th><Mail size={12} /> Gmail</th><th><MessageCircle size={12} /> WhatsApp</th></tr></thead>
        <tbody>
          {rows?.map((row) => (
            <tr key={row.id}>
              <td><b>{String(row.level)}</b> {String(row.level_name ?? "")}</td>
              {["slack", "gmail", "whatsapp"].map((k) => <td key={k}><input type="checkbox" checked={Boolean(row[k])} onChange={(e) => void save(row, k, e.target.checked)} aria-label={`${k} for ${row.level_name}`} /></td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function AlarmList() {
  const { rows, error, setError, load } = useTable("flood_alarms");
  const [busy, setBusy] = useState<string | null>(null);
  const [events, setEvents] = useState<string | null>(null);
  const act = async (alarmId: string, action: "acknowledge" | "resolve") => {
    setBusy(alarmId);
    try { await send(`/alarms/${encodeURIComponent(alarmId)}/${action}`, "POST", { by: "FloodGuard control room" }); await load(); } catch (e) { setError(errorText(e)); } finally { setBusy(null); }
  };
  return (
    <section className="aa-card">
      <div className="aa-row-actions"><p className="aa-help">Every alarm the workflow has raised. <b>Acknowledge</b> stops tier escalation (it runs through the workflow, so it is audited and reported to the backend); <b>Resolve</b> closes an alarm by hand.</p><button type="button" className="secondary-button" onClick={() => void load()}><RefreshCw size={14} /> Refresh</button></div>
      {error && <div className="aa-msg bad">{error}</div>}
      <div className="aa-table-wrap">
        <table className="data-table aa-table">
          <thead><tr><th>Status</th><th>Target</th><th>Level</th><th>Tier</th><th>Raised</th><th>Last change</th><th>Acknowledged</th><th /></tr></thead>
          <tbody>
            {rows?.map((a) => {
              const id = String(a.alarm_id);
              return [
                <tr key={a.id}>
                  <td><span className={`aa-pill ${a.status}`}>{String(a.status)}</span></td>
                  <td><strong>{String(a.target_name)}</strong><small>{String(a.model_case)} · {id}</small></td>
                  <td>{String(a.level)} {String(a.level_name)}</td><td>{String(a.tier_name ?? a.tier)}</td>
                  <td>{when(String(a.first_raised_at))}</td><td>{String(a.last_action)} · {when(String(a.last_forecast_at))}</td>
                  <td>{a.acknowledged_by ? `${a.acknowledged_by}` : "—"}</td>
                  <td className="aa-btns">
                    {a.status === "open" && <button type="button" className="secondary-button" disabled={busy === id} onClick={() => void act(id, "acknowledge")}>Acknowledge</button>}
                    {a.status !== "resolved" && <button type="button" className="secondary-button" disabled={busy === id} onClick={() => void act(id, "resolve")}>Resolve</button>}
                    <button type="button" className="secondary-button" onClick={() => setEvents(events === id ? null : id)}>{events === id ? "Hide" : "History"}</button>
                  </td>
                </tr>,
                events === id && <tr key={`${a.id}-ev`} className="aa-sub"><td colSpan={8}><EventRows alarmId={id} /></td></tr>,
              ];
            })}
            {rows?.length === 0 && <tr><td colSpan={8}>No alarms yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function EventRows({ alarmId }: { alarmId: string }) {
  const { rows } = useTable("alarm_events", alarmId);
  if (!rows) return <Loader2 size={14} className="aa-spin" />;
  return <ul className="aa-events">{rows.map((e) => <li key={e.id}><b>{String(e.event)}</b> {when(String(e.at))} · {String(e.actor)} · {String(e.detail)}</li>)}</ul>;
}

function LogView() {
  const [which, setWhich] = useState<"alarm_notifications" | "alarm_events">("alarm_notifications");
  const { rows, error, load } = useTable(which);
  return (
    <section className="aa-card">
      <div className="aa-row-actions">
        <div className="aa-seg">
          <button type="button" className={which === "alarm_notifications" ? "on" : ""} onClick={() => setWhich("alarm_notifications")}>Deliveries</button>
          <button type="button" className={which === "alarm_events" ? "on" : ""} onClick={() => setWhich("alarm_events")}>Audit trail</button>
        </div>
        <button type="button" className="secondary-button" onClick={() => void load()}><RefreshCw size={14} /> Refresh</button>
      </div>
      {error && <div className="aa-msg bad">{error}</div>}
      <div className="aa-table-wrap">
        {which === "alarm_notifications" ? (
          <table className="data-table aa-table">
            <thead><tr><th>Sent</th><th>Alarm</th><th>Channel</th><th>To</th><th>Status</th><th>Detail</th></tr></thead>
            <tbody>{rows?.map((r) => <tr key={r.id}><td>{when(String(r.sent_at))}</td><td>{String(r.alarm_id)}</td><td>{String(r.channel)}</td><td>{String(r.recipient)}</td><td><span className={`aa-pill ${r.status}`}>{String(r.status)}</span></td><td className="aa-wrap">{String(r.detail)}</td></tr>)}</tbody>
          </table>
        ) : (
          <table className="data-table aa-table">
            <thead><tr><th>At</th><th>Alarm</th><th>Event</th><th>Tier</th><th>By</th><th>Detail</th></tr></thead>
            <tbody>{rows?.map((r) => <tr key={r.id}><td>{when(String(r.at))}</td><td>{String(r.alarm_id)}</td><td>{String(r.event)}</td><td>{String(r.tier)}</td><td>{String(r.actor)}</td><td className="aa-wrap">{String(r.detail)}</td></tr>)}</tbody>
          </table>
        )}
      </div>
    </section>
  );
}
