import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ComponentType } from "react";
import {
  BellRing, CheckCheck, CheckCircle2, CircleArrowUp, CircleDashed, Database, FlaskConical, GitBranch, History,
  Link2, Loader2, Play, Radio, RotateCcw, Save, ScrollText, Send, Timer, Webhook, Wrench, XCircle, Zap,
} from "lucide-react";
import "../alarm-network.css";

/* The n8n alarm workflow as a glowing network. The selected run is replayed in the order its
   steps really ran: a pulse of light travels along each link that was used and lights the next
   step; failed steps glow red, unused ones stay dim. Past runs are listed as a history. */

export interface NetLayout {
  triggers: { name: string; type: string }[];
  blocks: { name: string; description: string; nodes: { name: string; type: string; disabled: boolean }[] }[];
  links: { from: string; to: string }[];
}
export interface NetRun {
  id: string; status: string; mode: string; trigger: string | null; started_at: string | null; stopped_at: string | null;
  blocks: Record<string, string>;
  nodes: { name: string; block: string | null; status: string; items: number; ms: number; error: string | null; started_at?: number }[];
}

const STEP_MS = 900; // time between steps lighting up during a replay
const ICONS: Record<string, ComponentType<{ size?: number }>> = {
  "Forecast webhook": Webhook, "Escalation check": Timer, "Acknowledge link": Link2, "Set up & test": FlaskConical,
  "Load settings & duty roster": Database, "Validate & decide": GitBranch, "Reply to portal": Send,
  "Escalate unacknowledged alarms": CircleArrowUp, "Record acknowledgement": CheckCheck, "Save alarm": Save,
  "Notify on duty officers": BellRing, "Audit trail & backend callback": ScrollText, "Set up tables & test data": Wrench,
};
const iconOf = (name: string, trigger: boolean) => ICONS[name] ?? (trigger ? Zap : Radio);
const clock = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString([], { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";
const duration = (r: NetRun) => (r.started_at && r.stopped_at ? `${((+new Date(r.stopped_at) - +new Date(r.started_at)) / 1000).toFixed(1)} s` : "running");

type Kind = { label: string; tone: "alarm" | "warn" | "ack" | "check" | "test" | "fail"; alarm: boolean };
/** What a run did, in plain words. */
export function runKind(r: NetRun): Kind {
  if (r.status === "error" || r.status === "crashed") return { label: `Failed · ${r.trigger ?? r.mode}`, tone: "fail", alarm: true };
  const notified = !!r.blocks["Notify on duty officers"];
  switch (r.trigger) {
    case "Forecast webhook": return { label: notified ? "Forecast alarm · officers alerted" : "Forecast received", tone: "alarm", alarm: true };
    case "Escalation check": return notified ? { label: "Alarm escalated", tone: "warn", alarm: true } : { label: "Routine escalation check", tone: "check", alarm: false };
    case "Acknowledge link": return { label: "Alarm acknowledged", tone: "ack", alarm: true };
    case "Set up & test": return { label: "Setup & test run", tone: "test", alarm: false };
    default: return { label: r.trigger ?? r.mode, tone: "check", alarm: false };
  }
}

/** Steps (triggers and blocks) in the order they first ran. */
function sequenceOf(run: NetRun | undefined): string[] {
  if (!run) return [];
  const first = new Map<string, number>();
  run.nodes.forEach((n, i) => {
    const key = n.block ?? (n.name === run.trigger ? n.name : null);
    if (!key) return;
    const at = n.started_at ?? i;
    if (!first.has(key) || at < (first.get(key) as number)) first.set(key, at);
  });
  if (run.trigger && !first.has(run.trigger)) first.set(run.trigger, -Infinity);
  return [...first.entries()].sort((a, b) => a[1] - b[1]).map(([k]) => k);
}

type Box = { x: number; y: number; w: number; h: number };

export function AlarmNetwork({ layout, runs: recent, history = [], selectedId, onPick, offline }: {
  layout: NetLayout | null; runs: NetRun[];
  /** Older alarm runs (forecasts, acknowledgements, tests, failures) found further back than the recent runs. */
  history?: NetRun[];
  selectedId: string | null; onPick: (id: string | null) => void; offline?: boolean;
}) {
  // Recent runs plus the older alarm runs, newest first, each once.
  const runs = useMemo(() => {
    const byId = new Map<string, NetRun>();
    for (const r of [...recent, ...history]) if (!byId.has(r.id)) byId.set(r.id, r);
    return [...byId.values()].sort((a, b) => +new Date(b.started_at ?? 0) - +new Date(a.started_at ?? 0));
  }, [recent, history]);
  const [open, setOpen] = useState<string | null>(null);
  const [filter, setFilter] = useState<"alarms" | "all">("alarms");
  const canvas = useRef<HTMLDivElement>(null);
  const nodeEls = useRef(new Map<string, HTMLElement>());
  const [boxes, setBoxes] = useState<Record<string, Box>>({});
  const [size, setSize] = useState({ w: 0, h: 0 });
  const run = runs.find((r) => r.id === selectedId) ?? recent[0] ?? runs[0];

  // Columns by distance from the triggers, following the workflow's links. Triggers with no
  // links (test helpers) are left out of the picture.
  const { columns, links, triggers } = useMemo(() => {
    if (!layout) return { columns: [] as string[][], links: [] as NetLayout["links"], triggers: new Set<string>() };
    const linked = new Set(layout.links.flatMap((l) => [l.from, l.to]));
    const trig = layout.triggers.map((t) => t.name).filter((n) => linked.has(n));
    const depth = new Map<string, number>(trig.map((t) => [t, 0]));
    for (let pass = 0; pass < 12; pass += 1)
      for (const link of layout.links) {
        const d = depth.get(link.from);
        if (d !== undefined && link.to !== link.from && (depth.get(link.to) ?? -1) < d + 1 && d + 1 < 10) depth.set(link.to, d + 1);
      }
    const cols: string[][] = [trig];
    for (const block of layout.blocks) { const d = depth.get(block.name) ?? 1; (cols[d] ??= []).push(block.name); }
    return { columns: cols.filter(Boolean), links: layout.links.filter((l) => linked.has(l.from) && l.from !== l.to), triggers: new Set(trig) };
  }, [layout]);

  // Measure node cards (layout pixels, unaffected by the portal's page zoom) to draw the links.
  useLayoutEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const measure = () => {
      const next: Record<string, Box> = {};
      nodeEls.current.forEach((node, name) => { next[name] = { x: node.offsetLeft, y: node.offsetTop, w: node.offsetWidth, h: node.offsetHeight }; });
      setBoxes(next);
      setSize({ w: el.offsetWidth, h: el.offsetHeight });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [columns, open]);

  // Replay: light the steps one by one in the order they ran.
  const sequence = useMemo(() => sequenceOf(run), [run]);
  // Runs are re-fetched every few seconds; replay only when the run or its steps really change.
  const sequenceKey = `${run?.id ?? ""}:${sequence.join("|")}`;
  const [phase, setPhase] = useState(0);
  const [replayKey, setReplayKey] = useState(0);
  useEffect(() => {
    setPhase(0);
    if (!sequence.length) return;
    let step = 0;
    const first = window.setTimeout(() => { step = 1; setPhase(1); }, 250);
    const timer = window.setInterval(() => {
      step += 1;
      setPhase(step);
      if (step >= sequence.length) window.clearInterval(timer);
    }, STEP_MS);
    return () => { window.clearTimeout(first); window.clearInterval(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- sequenceKey stands for sequence
  }, [sequenceKey, replayKey]);
  const order = useMemo(() => new Map(sequence.map((name, i) => [name, i])), [sequence]);
  const lit = (name: string) => (order.get(name) ?? Infinity) < phase;
  const stateOf = (name: string) => (triggers.has(name) ? (run?.trigger === name ? "success" : undefined) : run?.blocks[name]);
  const playing = phase < sequence.length;

  const shownRuns = runs.filter((r) => filter === "all" || runKind(r).alarm);
  const alarmCount = runs.filter((r) => runKind(r).alarm).length;
  const okRate = runs.length ? Math.round((100 * runs.filter((r) => r.status === "success").length) / runs.length) : 0;
  const lastAlarm = runs.find((r) => runKind(r).alarm);

  if (!layout && offline) return <div className="aa-card aa-loading"><CircleDashed size={18} /> No saved copy of the workflow yet.</div>;
  if (!layout) return <div className="aa-card aa-loading"><Loader2 size={18} className="aa-spin" /> Loading the workflow…</div>;
  const blockOf = (name: string) => layout.blocks.find((b) => b.name === name);

  const path = (a: Box, b: Box) => {
    const x1 = a.x + a.w, y1 = a.y + a.h / 2, x2 = b.x, y2 = b.y + b.h / 2;
    const dx = Math.max(50, Math.abs(x2 - x1) / 2);
    return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
  };
  const openBlock = open ? blockOf(open) : undefined;

  return (
    <section className="an">
      <div className="an-stats">
        <div className="an-stat"><span className="an-stat-icon"><History size={16} /></span><div><small>Recent runs</small><b>{recent.length}</b></div></div>
        <div className="an-stat alarm"><span className="an-stat-icon"><BellRing size={16} /></span><div><small>Alarm runs</small><b>{alarmCount}</b></div></div>
        <div className="an-stat"><span className="an-stat-icon"><CheckCircle2 size={16} /></span><div><small>Succeeded</small><b>{okRate}%</b></div></div>
        <div className="an-stat"><span className="an-stat-icon"><Timer size={16} /></span><div><small>Last alarm</small><b className="an-stat-small">{lastAlarm ? clock(lastAlarm.started_at) : "none yet"}</b></div></div>
      </div>

      <div className="an-main">
        <div className="an-panel an-graph">
          <div className="an-graph-head">
            <div>
              <h3>Workflow network</h3>
              <p>{run ? <>Run <b>#{run.id}</b> · {runKind(run).label} · {clock(run.started_at)} · {duration(run)}</> : "No runs yet."}</p>
            </div>
            <div className="an-graph-actions">
              {run && <span className={`an-progress ${playing ? "on" : ""}`}>{playing ? "Replaying" : "Replayed"} · step {Math.min(phase, sequence.length)}/{sequence.length}</span>}
              <button type="button" className="an-btn" onClick={() => setReplayKey((k) => k + 1)} disabled={!run}><RotateCcw size={14} /> Replay</button>
              {selectedId && <button type="button" className="an-btn" onClick={() => onPick(null)}><Play size={14} /> Follow live</button>}
            </div>
          </div>

          <div className="an-canvas-wrap">
            <div className="an-canvas" ref={canvas}>
              <svg className="an-links" width={size.w} height={size.h} aria-hidden="true">
                <defs>
                  <linearGradient id="an-edge" x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0%" stopColor="#a855f7" />
                    <stop offset="100%" stopColor="#38bdf8" />
                  </linearGradient>
                  <linearGradient id="an-edge-red" x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0%" stopColor="#f472b6" />
                    <stop offset="100%" stopColor="#ef4444" />
                  </linearGradient>
                </defs>
                {links.map((l) => {
                  const a = boxes[l.from], b = boxes[l.to];
                  if (!a || !b) return null;
                  const d = path(a, b);
                  const used = order.has(l.from) && order.has(l.to) && (order.get(l.from) as number) < (order.get(l.to) as number);
                  const target = order.get(l.to) ?? -1;
                  const pulsing = used && phase === target; // the light is on its way to this step
                  const done = used && phase > target;
                  const failed = stateOf(l.to) === "error";
                  const key = `${l.from}→${l.to}`;
                  return (
                    <g key={key} className={`an-edge ${used ? "used" : "unused"} ${done ? "done" : ""} ${failed ? "failed" : ""}`}>
                      <path d={d} className="an-edge-base" />
                      {done && <path d={d} className="an-edge-lit" stroke={failed ? "url(#an-edge-red)" : "url(#an-edge)"} />}
                      {done && <path d={d} className="an-edge-flow" pathLength={100} />}
                      {pulsing && <path key={`${key}-${replayKey}-${run?.id}`} d={d} className="an-edge-pulse" pathLength={100} style={{ animationDuration: `${STEP_MS}ms` }} />}
                    </g>
                  );
                })}
              </svg>
              {columns.map((col, i) => (
                <div className="an-col" key={i}>
                  {col.map((name) => {
                    const trigger = triggers.has(name);
                    const Icon = iconOf(name, trigger);
                    const state = stateOf(name);
                    const isLit = lit(name);
                    const ranHere = order.has(name);
                    const block = blockOf(name);
                    const nodes = run?.nodes.filter((n) => n.block === name) ?? [];
                    const ms = nodes.reduce((sum, n) => sum + n.ms, 0);
                    const cls = ["an-node", trigger ? "trigger" : "", ranHere ? (isLit ? `lit ${state ?? "success"}` : "waiting") : "unused", open === name ? "open" : ""].join(" ");
                    return (
                      <button type="button" key={name} className={cls} ref={(el) => { if (el) nodeEls.current.set(name, el); else nodeEls.current.delete(name); }}
                        onClick={() => setOpen(open === name ? null : name)} title={block?.description ?? (trigger ? "Starts the workflow" : undefined)}>
                        <span className="an-node-icon"><Icon size={17} /></span>
                        <span className="an-node-text">
                          <b>{name}</b>
                          <small>{trigger ? (run?.trigger === name ? "started this run" : "trigger") : ranHere ? `${nodes.length} steps · ${ms} ms` : block ? `${block.nodes.length} steps · not used` : ""}</small>
                        </span>
                        {isLit && state === "error" && <XCircle size={14} className="an-node-badge bad" />}
                        {isLit && state !== "error" && ranHere && <CheckCircle2 size={14} className="an-node-badge" />}
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
          </div>
          <div className="an-legend">
            <span><i className="lit" /> ran in this run</span>
            <span><i className="bad" /> failed</span>
            <span><i className="dim" /> not used</span>
            <span><i className="pulse" /> light travels along each link that was used, in the order it ran</span>
          </div>

          {openBlock && (
            <div className="an-detail">
              <h4>{openBlock.name}</h4>
              <p>{openBlock.description}</p>
              <ul>
                {openBlock.nodes.map((n) => {
                  const r = run?.nodes.find((x) => x.name === n.name);
                  return (
                    <li key={n.name} className={r?.status ?? "idle"}>
                      {r?.status === "success" ? <CheckCircle2 size={13} /> : r?.status === "error" ? <XCircle size={13} /> : <CircleDashed size={13} />}
                      <b>{n.name}</b>
                      <em>{n.disabled ? "switched off" : r ? `${r.items} items · ${r.ms} ms` : "not used in this run"}</em>
                      {r?.error && <span className="an-err">{r.error}</span>}
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </div>

        <aside className="an-panel an-history">
          <div className="an-history-head">
            <h3><History size={15} /> Execution history</h3>
            <div className="an-chips" role="group" aria-label="Which runs">
              <button type="button" className={filter === "alarms" ? "on" : ""} onClick={() => setFilter("alarms")}>Alarms</button>
              <button type="button" className={filter === "all" ? "on" : ""} onClick={() => setFilter("all")}>All runs</button>
            </div>
          </div>
          <ol className="an-history-list">
            {shownRuns.map((r) => {
              const kind = runKind(r);
              return (
                <li key={r.id}>
                  <button type="button" className={`an-run ${kind.tone} ${run?.id === r.id ? "on" : ""}`} onClick={() => onPick(r.id)}>
                    <span className="an-run-dot" />
                    <span className="an-run-text">
                      <b>{kind.label}</b>
                      <small>#{r.id} · {clock(r.started_at)} · {duration(r)} · {Object.keys(r.blocks).length} steps</small>
                    </span>
                    {run?.id === r.id ? <span className="an-run-tag">{playing ? "replaying" : "shown"}</span> : <Play size={13} className="an-run-play" />}
                  </button>
                </li>
              );
            })}
            {!shownRuns.length && (
              <li className="an-empty">
                {filter === "alarms"
                  ? <>No alarm runs found yet. <button type="button" className="an-link" onClick={() => setFilter("all")}>Show all runs</button></>
                  : "No runs yet."}
              </li>
            )}
          </ol>
        </aside>
      </div>
    </section>
  );
}
