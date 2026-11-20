import { Eye, EyeOff, History, Trophy } from "lucide-react";
import { useMemo, useState } from "react";
import type { ModelReplay, ReplayFamily } from "../types/api";
import { type ChartSeries, DAY, TimeChart, fmtDate, fmtFlow, toT } from "./riverineCharts";
import { MODEL_INFO, ModelTag } from "./riverineModels";

const FAMILIES: Record<ReplayFamily, { label: string; color: string; dash: string[] }> = {
  ai: { label: "AI (deep learning)", color: "#3987e5", dash: ["", "8 4", "2 4", "12 4 2 4"] },
  physics: { label: "Physics-based", color: "#d95926", dash: ["", "8 4"] },
  hybrid: { label: "Hybrid physics + AI", color: "#199e70", dash: ["", "8 4", "2 4", "12 4 2 4"] },
  statistical: { label: "Statistical ML", color: "#8ea3a4", dash: ["8 4"] },
  baseline: { label: "Baseline", color: "#8ea3a4", dash: ["2 4", "12 4 2 4"] },
};
const FAMILY_ORDER: ReplayFamily[] = ["ai", "hybrid", "physics", "statistical", "baseline"];
const share = (v: number | null | undefined) => v == null ? "—" : `${Math.round(v * 100)}%`;

export function ReplaySkeleton({ stationName }: { stationName: string }) {
  return <div className="ro-replay empty">
    <div className="ro-card"><p className="ro-foot">Replays appear once short-range models are trained and tested for {stationName}. So far 24 models are trained for Marala only.</p></div>
  </div>;
}

export function ModelReplaySection({ replay }: { replay: ModelReplay }) {
  const biggest = [...replay.events].sort((a, b) => (b.peak ?? 0) - (a.peak ?? 0))[0];
  const [eventId, setEventId] = useState(biggest?.id ?? "");
  const [lead, setLead] = useState(replay.leads.includes(10) ? 10 : replay.leads[0]);
  const scores = replay.scores[String(lead)]?.models ?? {};
  const available = replay.models.filter((m) => m.max_lead >= lead && scores[m.id]);
  const ranked = [...available].sort((a, b) => (scores[b.id]?.csi ?? 0) - (scores[a.id]?.csi ?? 0) || (scores[a.id]?.rmse ?? 0) - (scores[b.id]?.rmse ?? 0));
  const bestByFamily = useMemo(() => {
    const out = new Map<ReplayFamily, string>();
    for (const m of ranked) if (!out.has(m.family)) out.set(m.family, m.id);
    return out;
  }, [ranked]);
  const [picked, setPicked] = useState<Set<string> | null>(null);
  const defaults = new Set(["ai", "hybrid", "physics"].map((f) => bestByFamily.get(f as ReplayFamily)).filter(Boolean) as string[]);
  defaults.add("persistence");
  const selected = new Set([...(picked ?? defaults)].filter((id) => available.some((m) => m.id === id)));
  const toggle = (id: string) => setPicked(() => { const next = new Set(selected); if (next.has(id)) next.delete(id); else next.add(id); return next; });

  const event = replay.events.find((e) => e.id === eventId) ?? replay.events[0];
  const eventSeries = replay.series[event.id]?.[String(lead)] ?? {};
  const start = toT(event.start);
  const days = event.observed.map((o, i) => ({ t: start + i * DAY, v: o.v }));
  const dashIndex = new Map<string, number>();
  const styleFor = (id: string) => {
    const model = replay.models.find((m) => m.id === id)!;
    const fam = FAMILIES[model.family];
    const order = [...selected].filter((s) => replay.models.find((m) => m.id === s)?.family === model.family);
    const i = Math.max(0, order.indexOf(id));
    dashIndex.set(id, i);
    return { "--fam": fam.color, "--dash": fam.dash[i % fam.dash.length] || "none" } as React.CSSProperties;
  };
  const series: ChartSeries[] = [
    ...[...selected].map((id) => ({ id, kind: "line" as const, className: "ro-line-family", style: styleFor(id), points: (eventSeries[id]?.values ?? []).map((v, i) => ({ t: start + i * DAY, v })) })),
    { id: "observed", kind: "line", className: "ro-line-observed", points: days },
  ];
  const best = ranked[0];
  const persistence = scores.persistence;
  const label = (id: string) => MODEL_INFO[id]?.name ?? replay.models.find((m) => m.id === id)?.label ?? id;

  return <>
    <div className="ro-replay-controls">
      <div className="ro-toggle ro-events" role="group" aria-label="Flood event">
        {replay.events.map((e) => <button key={e.id} type="button" aria-pressed={e.id === event.id} onClick={() => setEventId(e.id)}>
          {fmtDate(toT(e.peak_date), { month: "short", year: "numeric" })}<small>peak {fmtFlow(e.peak)} m³/s</small>
        </button>)}
      </div>
      <div className="ro-lead-picker" role="group" aria-label="Forecast made this many days ahead">
        <span>Forecast made</span>
        {replay.leads.map((l) => <button key={l} type="button" aria-pressed={l === lead} onClick={() => setLead(l)}>{l}</button>)}
        <span>days ahead</span>
      </div>
    </div>

    {best && <p className="ro-replay-summary"><Trophy size={16} aria-hidden />Made {lead} day{lead === 1 ? "" : "s"} ahead, <b>{label(best.id)}</b> scored best across 2022–2024: it caught <b>{share(scores[best.id]?.hit_rate)}</b> of high-flow days{persistence ? `, against ${share(persistence.hit_rate)} for “no change”` : ""}.</p>}

    <div className="ro-grid-replay">
      <div className="ro-card">
        <div className="ro-card-head">
          <h4><History size={16} aria-hidden />{event.label}: what each model forecast {lead} day{lead === 1 ? "" : "s"} before</h4>
        </div>
        <TimeChart ariaLabel={`Model forecasts made ${lead} days ahead during the ${event.label}`} height={360} start={start} end={toT(event.end)} series={series} ticks="week"
          hlines={[{ v: replay.threshold, label: "High-flow level", className: "ro-hline flood" }]}
          markers={[{ t: toT(event.peak_date), label: "Peak", className: "ro-marker" }]}
          tooltip={(t) => {
            const i = Math.round((t - start) / DAY);
            const obs = event.observed[i]?.v;
            return <><strong>{fmtDate(t, { weekday: "short", day: "numeric", month: "short", year: "numeric" })}</strong>
              <span>Measured: <b>{fmtFlow(obs)} m³/s</b></span>
              {[...selected].map((id) => <span key={id} className="ro-tip-row"><i style={{ background: FAMILIES[replay.models.find((m) => m.id === id)!.family].color }} />{label(id)}: <b>{fmtFlow(eventSeries[id]?.values[i])}</b></span>)}
            </>;
          }} />
        <ul className="ro-legend">
          <li><i className="observed" aria-hidden />Measured inflow</li>
          {[...selected].map((id) => {
            const fam = replay.models.find((m) => m.id === id)!.family;
            return <li key={id}><svg width="22" height="10" aria-hidden><line x1="1" x2="21" y1="5" y2="5" stroke={FAMILIES[fam].color} strokeWidth="2.5" strokeDasharray={FAMILIES[fam].dash[(dashIndex.get(id) ?? 0) % FAMILIES[fam].dash.length] || undefined} /></svg>{label(id)}</li>;
          })}
          <li><i className="flood-line" aria-hidden />{replay.threshold_label}</li>
        </ul>
      </div>
      <div className="ro-family-best">
        {FAMILY_ORDER.filter((f) => f !== "statistical" && bestByFamily.has(f)).map((f) => {
          const id = bestByFamily.get(f)!;
          const s = scores[id];
          return <article key={f} className="ro-fam" style={{ "--fam": FAMILIES[f].color } as React.CSSProperties}>
            <span className="ro-fam-label">Best {FAMILIES[f].label}</span>
            <ModelTag id={id} compact />
            <b>{share(s?.hit_rate)}<small> high-flow days caught</small></b>
            <small>{share(s?.false_alarm_ratio)} of its alarms were false · typical error {fmtFlow(s?.rmse)} m³/s</small>
          </article>;
        })}
      </div>
    </div>

    <div className="ro-card ro-replay-table">
      <h4>All {available.length} models able to forecast {lead} days ahead</h4>
      <table className="ro-table">
        <thead><tr><th>Show</th><th>Model</th><th>High-flow days caught</th><th>False alarms</th><th>Typical error</th><th>{fmtDate(toT(event.peak_date), { month: "short", year: "numeric" })} peak forecast</th></tr></thead>
        <tbody>{ranked.map((m, rank) => {
          const s = scores[m.id];
          const ev = eventSeries[m.id];
          const on = selected.has(m.id);
          return <tr key={m.id} className={on ? "on" : ""}>
            <td><button type="button" className="ro-eye" aria-pressed={on} aria-label={`${on ? "Hide" : "Show"} ${label(m.id)} on the chart`} onClick={() => toggle(m.id)} style={{ "--fam": FAMILIES[m.family].color } as React.CSSProperties}>{on ? <Eye size={14} /> : <EyeOff size={14} />}</button></td>
            <th scope="row"><span className="ro-rank">{rank + 1}</span><ModelTag id={m.id} compact /></th>
            <td><span className="ro-hbar"><i style={{ width: `${(s?.hit_rate ?? 0) * 100}%`, background: FAMILIES[m.family].color }} /></span>{share(s?.hit_rate)}</td>
            <td>{share(s?.false_alarm_ratio)}</td>
            <td>{fmtFlow(s?.rmse)} m³/s</td>
            <td>{ev?.peak != null ? <>{fmtFlow(ev.peak)} <small className={Math.abs(ev.peak_error_pct ?? 0) <= 20 ? "good" : "muted"}>({(ev.peak_error_pct ?? 0) > 0 ? "+" : ""}{Math.round(ev.peak_error_pct ?? 0)}%)</small></> : "—"}</td>
          </tr>;
        })}</tbody>
      </table>
      <p className="ro-foot">Ranked by flood score (critical success index: high-flow days caught, penalised for misses and false alarms). Every model is scored on the same {replay.scores[String(lead)]?.pairs.toLocaleString()} forecast–outcome pairs. {replay.test_period}. Measured peak: {fmtFlow(event.peak)} m³/s.</p>
      <p className="ro-note"><History size={14} aria-hidden />{replay.weather_caveat}</p>
    </div>
  </>;
}
