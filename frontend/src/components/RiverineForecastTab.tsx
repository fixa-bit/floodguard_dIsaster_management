import { Activity, Brain, CalendarRange, CheckCircle2, ChevronDown, CloudRain, Gauge, Globe2, Info, MapPin, Mountain, RefreshCw, ShieldAlert, Snowflake, Sparkles, Thermometer, TrendingDown, TrendingUp, Waves } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../services/api";
import type { MaralaStationForecastData, OutlookScenario, RiverMonitoringResponse, RiverMonitoringStation, RiverineExtendedForecastData, RiverineOutlookAvailable, RiverineOutlookData } from "../types/api";
import { type ChartSeries, DAY, OddsBars, TimeChart, fmtDate, fmtFlow, toT, utcDay } from "./riverineCharts";
import { ModelReplaySection, ReplaySkeleton } from "./RiverineModelReplay";
import { ModelTag, ModelTags } from "./riverineModels";
import "../riverine-forecast.css";

const REFRESH_MS = 15 * 60_000;
const CUMECS_TO_CUSECS = 35.3147;
const DEFAULT_STATION = "MARALA";
const CLASS_ORDER = ["Low", "Medium", "High", "Very High", "Exceptional"] as const;

type Status = "good" | "warning" | "serious" | "critical" | "none";
const cusecs = (m3s: number | null | undefined) => m3s == null ? "—" : `${Math.round(m3s * CUMECS_TO_CUSECS / 100) * 100 >= 1000 ? (Math.round(m3s * CUMECS_TO_CUSECS / 100) * 100).toLocaleString("en-US") : Math.round(m3s * CUMECS_TO_CUSECS)} cusecs`;
const pct = (v: number | null | undefined, digits = 0) => v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(digits)}%`;
const share = (v: number | null | undefined) => v == null ? "—" : `${Math.round(v * 100)}%`;
const oneIn = (p: number | null | undefined) => !p ? "—" : p >= 0.5 ? `${Math.round(p * 10) / 10 >= 0.95 ? "almost every" : `${Math.round(p * 100)}% of`} years` : `1 in ${Math.round(1 / p)} years`;
const monthName = (ym: string) => fmtDate(toT(`${ym}-01`), { month: "short" });

function classify(flow: number | null | undefined, thresholds: Record<string, number> | undefined): { label: string; status: Status } {
  if (flow == null || !thresholds) return { label: "No reading", status: "none" };
  let reached: string | null = null;
  for (const name of CLASS_ORDER) if (thresholds[name] != null && flow >= thresholds[name]) reached = name;
  if (!reached) return { label: "Below flood level", status: "good" };
  const status: Status = reached === "Low" || reached === "Medium" ? "warning" : reached === "High" ? "serious" : "critical";
  return { label: `${reached} flood`, status };
}

function categoryStatus(category: string | undefined, flow: number | null): { label: string; status: Status } {
  if (!category || flow == null) return { label: "No reading", status: "none" };
  const c = category.toLowerCase();
  if (c.startsWith("below") || c.includes("normal")) return { label: "Below flood level", status: "good" };
  if (c.includes("very") || c.includes("exceptional")) return { label: category, status: "critical" };
  if (c.includes("high")) return { label: category, status: "serious" };
  return { label: category, status: "warning" };
}

function StatusPill({ label, status }: { label: string; status: Status }) {
  const Icon = status === "good" ? CheckCircle2 : status === "none" ? Info : ShieldAlert;
  return <span className={`ro-status ${status}`}><Icon size={13} aria-hidden />{label}</span>;
}

function TrustMeter({ level, label }: { level: number; label: string }) {
  return <span className="ro-trust" title={`Confidence: ${label}`}>
    <span aria-hidden>{[1, 2, 3, 4, 5].map((i) => <i key={i} className={i <= level ? "on" : ""} />)}</span>
    <small>{label}</small>
  </span>;
}

function Delta({ value, suffix = "vs normal" }: { value: number | null | undefined; suffix?: string }) {
  if (value == null) return <span className="ro-delta none">—</span>;
  const near = Math.abs(value) < 10;
  const Icon = value >= 0 ? TrendingUp : TrendingDown;
  return <span className={`ro-delta ${near ? "near" : value > 0 ? "up" : "down"}`}><Icon size={13} aria-hidden />{pct(value)} {suffix}</span>;
}

function FloodLadder({ flow, thresholds }: { flow: number | null; thresholds?: Record<string, number> }) {
  if (!thresholds) return null;
  const top = (thresholds.Exceptional ?? 17_000) * 1.15;
  const pos = (v: number) => `${Math.min(100, Math.sqrt(Math.max(0, v) / top) * 100)}%`;
  const low = thresholds.Low;
  return <div className="ro-ladder" aria-label="Current flow against official flood levels">
    <div className="ro-ladder-track">
      <span className="seg good" style={{ left: 0, width: pos(low) }} />
      <span className="seg warning" style={{ left: pos(low), width: `calc(${pos(thresholds.High)} - ${pos(low)})` }} />
      <span className="seg serious" style={{ left: pos(thresholds.High), width: `calc(${pos(thresholds["Very High"])} - ${pos(thresholds.High)})` }} />
      <span className="seg critical" style={{ left: pos(thresholds["Very High"]), right: 0 }} />
      {flow != null && <span className="ro-ladder-needle" style={{ left: pos(flow) }} />}
    </div>
    <div className="ro-ladder-labels">
      {(["Low", "High", "Very High"] as const).map((name) => <span key={name} style={{ left: pos(thresholds[name]) }}>{name === "Very High" ? "Very high+" : name}</span>)}
    </div>
    {flow != null && <small>{Math.round(flow / low * 100)}% of the low-flood level ({fmtFlow(low)} m³/s · 100,000 cusecs)</small>}
  </div>;
}

function Section({ id, step, icon, title, lede, children, aside }: { id: string; step: string; icon: ReactNode; title: string; lede: string; children: ReactNode; aside?: ReactNode }) {
  return <section className="ro-section" id={id} aria-labelledby={`${id}-title`}>
    <header className="ro-section-head">
      <div className="ro-section-icon" aria-hidden>{icon}</div>
      <div><span className="ro-eyebrow">{step}</span><h3 id={`${id}-title`}>{title}</h3><p>{lede}</p></div>
      {aside && <div className="ro-section-aside">{aside}</div>}
    </header>
    {children}
  </section>;
}

function EmptyPlot({ height, title, note }: { height: number; title: string; note: string }) {
  return <div className="ro-empty" style={{ minHeight: height }}>
    <svg viewBox="0 0 400 120" preserveAspectRatio="none" aria-hidden>
      {[20, 50, 80, 110].map((yy) => <line key={yy} x1="0" x2="400" y1={yy} y2={yy} />)}
      <path d="M0,92 C40,88 70,70 110,74 S180,96 220,80 S300,40 340,52 S380,70 400,64" />
    </svg>
    <div><Sparkles size={18} aria-hidden /><strong>{title}</strong><span>{note}</span></div>
  </div>;
}

function Legend({ items }: { items: Array<{ cls: string; label: string }> }) {
  return <ul className="ro-legend">{items.map((item) => <li key={item.label}><i className={item.cls} aria-hidden />{item.label}</li>)}</ul>;
}

function Tip({ title, rows }: { title: string; rows: Array<[string, ReactNode] | null | false> }) {
  const shown = rows.filter((r): r is [string, ReactNode] => Boolean(r));
  if (!shown.length) return null;
  return <><strong>{title}</strong>{shown.map(([k, v]) => <span key={k}>{k}: <b>{v}</b></span>)}</>;
}

/* ------------------------------------------------------------------ data helpers */
interface NormalDay { lo: number | null; mid: number | null; hi: number | null }
function normalsByDay(outlook: RiverineOutlookAvailable) {
  const map = new Map<number, NormalDay>();
  for (const r of outlook.seasonal.observed_last_365) map.set(toT(r.date), { lo: r.normal_p10, mid: r.normal_p50, hi: r.normal_p90 });
  for (const r of outlook.seasonal.daily) map.set(toT(r.date), { lo: r.normal_p10, mid: r.normal_p50, hi: r.normal_p90 });
  return map;
}

function gaugeReadings(forecast: MaralaStationForecastData | null) {
  const byDay = new Map<number, number>();
  for (const r of forecast?.history ?? []) if (r.inflow_cumecs != null) byDay.set(utcDay(Date.parse(r.observed_at) + 5 * 3_600_000), r.inflow_cumecs);
  return byDay;
}

function stationNow(station: RiverMonitoringStation | undefined, readings: Map<number, number>) {
  const days = [...readings.keys()].sort((a, b) => a - b);
  if (days.length) return { flow: readings.get(days[days.length - 1]) ?? null, at: days[days.length - 1], source: "FFD inflow · 06:00 PKT" };
  const inflow = station?.gauge_readings?.find((g) => g.gauge === "INFLOW");
  if (inflow) return { flow: inflow.value, at: Date.parse(inflow.time), source: "Inflow gauge" };
  return { flow: station?.current_discharge_cumecs ?? null, at: station?.observed_at ? Date.parse(station.observed_at) : null, source: station?.current_source ?? "River monitoring" };
}

/* ------------------------------------------------------------------ main tab */
/** `snapshotAt` (ms) freezes "today" and turns off auto refresh, for the shareable saved copy of this page. */
export function RiverineForecastTab({ snapshotAt }: { snapshotAt?: number } = {}) {
  const [monitoring, setMonitoring] = useState<RiverMonitoringResponse | null>(null);
  const [stationId, setStationId] = useState(DEFAULT_STATION);
  const [outlook, setOutlook] = useState<RiverineOutlookData | null>(null);
  const [forecast, setForecast] = useState<MaralaStationForecastData | null>(null);
  const [extended, setExtended] = useState<RiverineExtendedForecastData | null>(null);
  const [loading, setLoading] = useState(true);
  const [errors, setErrors] = useState<string[]>([]);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const marala = stationId === DEFAULT_STATION;
    const [stations, model, longRange, saved] = await Promise.allSettled([
      api.riverMonitoring(),
      marala ? api.maralaStationForecast() : Promise.resolve(null),
      marala ? api.riverineExtendedForecast() : Promise.resolve(null),
      api.riverineOutlook(stationId),
    ]);
    if (stations.status === "fulfilled") setMonitoring(stations.value);
    setForecast(model.status === "fulfilled" ? model.value : null);
    setExtended(longRange.status === "fulfilled" ? longRange.value : null);
    setOutlook(saved.status === "fulfilled" ? saved.value : null);
    const labels = ["River monitoring", "Gauge model", "Global 30-day model", "Saved outlook"];
    setErrors([stations, model, longRange, saved].flatMap((r, i) => r.status === "rejected" ? [`${labels[i]}: ${r.reason instanceof Error ? r.reason.message : "unavailable"}`] : []));
    setUpdatedAt(new Date(snapshotAt ?? Date.now()));
    setLoading(false);
  }, [stationId]);

  useEffect(() => {
    void load();
    if (snapshotAt) return;
    const timer = window.setInterval(() => void load(), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [load, snapshotAt]);

  const stations = monitoring?.stations ?? [];
  const station = stations.find((s) => s.id === stationId);
  const ready = outlook?.available ? outlook : null;
  const stationName = ready?.station.name ?? station?.name ?? stationId;
  const river = ready?.station.river ?? station?.river ?? "";
  const thresholds = ready?.flood_classes_cumecs ?? forecast?.thresholds_cumecs;
  const readings = useMemo(() => gaugeReadings(stationId === DEFAULT_STATION ? forecast : null), [forecast, stationId]);
  const now = stationNow(station, readings);
  const today = utcDay(snapshotAt ?? Date.now());
  const normals = useMemo(() => ready ? normalsByDay(ready) : new Map<number, NormalDay>(), [ready]);
  const nowNormal = normals.get(today) ?? (now.at ? normals.get(utcDay(now.at)) : undefined);
  const nowClass = thresholds ? classify(now.flow, thresholds) : categoryStatus(station?.flood_category, now.flow);

  const byRiver = useMemo(() => {
    const groups = new Map<string, RiverMonitoringStation[]>();
    for (const s of stations) groups.set(s.river, [...(groups.get(s.river) ?? []), s]);
    return [...groups];
  }, [stations]);

  const live = forecast?.forecast_mode === "rolling_live_origin";
  const glofas = (extended?.daily_forecast ?? []).filter((r) => toT(r.date) >= today);
  const next7 = [
    ...(live ? forecast!.forecasts.map((f) => f.candidates?.[0]?.inflow_cumecs ?? f.champion.inflow_cumecs) : []),
    ...glofas.slice(0, 8).map((r) => r.p75_cumecs ?? r.median_cumecs ?? 0),
  ];
  const next7Max = next7.length ? Math.max(...next7) : null;
  const next30Max = glofas.length ? Math.max(...glofas.map((r) => r.p75_cumecs ?? r.median_cumecs ?? 0)) : next7Max;
  const next7Class = classify(next7Max, thresholds);
  const glofas7 = glofas[7] ?? glofas[glofas.length - 1];
  const sevenDay = live ? forecast!.forecasts.find((f) => f.horizon_days === 7) : null;
  const sevenValue = sevenDay ? (sevenDay.candidates?.[0]?.inflow_cumecs ?? sevenDay.champion.inflow_cumecs) : glofas7?.median_cumecs ?? null;

  const season = ready?.seasonal;
  const seasonDelta = season?.mean_p50 && season.mean_normal_p50 ? (season.mean_p50 / season.mean_normal_p50 - 1) * 100 : null;
  const seasonWord = seasonDelta == null ? "" : Math.abs(seasonDelta) < 10 ? "near-normal" : seasonDelta > 0 ? "above-normal" : "below-normal";
  const ssp245 = ready?.climate.scenarios.find((s) => s.id === "ssp245");

  const headline = !ready
    ? `No trained forecast models for ${stationName} yet`
    : next30Max != null && thresholds && next30Max < thresholds.Low
      ? `No flood-level flow expected at ${stationName} in the next ${glofas.length >= 28 ? "30" : "7"} days`
      : next7Class.status !== "good" ? `${stationName} may reach ${next7Class.label.toLowerCase()} level within 7 days` : `${river} at ${stationName}: forecast outlook`;
  const detail = !ready
    ? `Forecast models are trained for Marala on the Chenab so far. ${now.flow != null ? `The live reading below comes from river monitoring.` : ""} The layout below shows what will appear once ${stationName} has its own models.`
    : `The ${river} is carrying ${fmtFlow(now.flow)} m³/s${nowNormal?.mid ? `, ${Math.abs(((now.flow ?? 0) / nowNormal.mid - 1) * 100) < 10 ? "close to" : (now.flow ?? 0) > nowNormal.mid ? "above" : "below"} the usual ${fmtFlow(nowNormal.mid)} m³/s for this date` : ""}. `
      + (season ? `Over the next six months the models expect ${seasonWord} flow, rising to about ${fmtFlow(season.peak.p50)} m³/s by ${fmtDate(toT(season.peak.date), { month: "long" })} as snowmelt begins. ` : "")
      + (ssp245?.pooled_flood_odds.p400k ? `Looking further ahead, a very high flood (≥400,000 cusecs) is projected in about ${oneIn(ssp245.pooled_flood_odds.p400k)} during 2026–2040.` : "");

  const jump = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });

  return <section className="ro" aria-label="Riverine forecast outlook">
    <header className="ro-hero">
      <div className="ro-hero-glow" aria-hidden />
      <div className="ro-hero-main">
        <div className="ro-hero-top">
          <span className="ro-eyebrow"><Waves size={14} aria-hidden /> Riverine outlook</span>
          <label className="ro-picker">
            <MapPin size={15} aria-hidden />
            <span className="sr-only">Forecast station</span>
            <select value={stationId} onChange={(e) => setStationId(e.target.value)} aria-label="Forecast station">
              {!stations.some((s) => s.id === DEFAULT_STATION) && <option value={DEFAULT_STATION}>Marala · Chenab — models trained</option>}
              {byRiver.map(([name, list]) => <optgroup key={name} label={`${name} River`}>
                {list.map((s) => <option key={s.id} value={s.id}>{s.name}{s.id === DEFAULT_STATION ? " — models trained" : ""}</option>)}
              </optgroup>)}
            </select>
            <ChevronDown size={15} aria-hidden />
          </label>
          <button type="button" className="ro-refresh" onClick={() => void load()} aria-label="Refresh outlook">
            <RefreshCw size={14} className={loading ? "spinning" : ""} aria-hidden />{updatedAt ? updatedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "Refresh"}
          </button>
        </div>
        <h2>{headline}</h2>
        <p>{detail}</p>
        <div className="ro-hero-chips">
          <span><Activity size={13} aria-hidden />{ready ? `${6 + ready.replay.models.length} trained models` : "No trained models yet"}</span>
          {ready && <span><CalendarRange size={13} aria-hidden />Seasonal outlook issued {fmtDate(toT(ready.seasonal.issue_date), { day: "numeric", month: "short", year: "numeric" })}</span>}
          {ready?.stale && <span className="warn">Outlook is {ready.issue_age_days} days old — rebuild it</span>}
          <span><Gauge size={13} aria-hidden />{river ? `${river} River` : "River"}{ready ? ` · ${ready.station.latitude.toFixed(2)}°N ${ready.station.longitude.toFixed(2)}°E` : ""}</span>
        </div>
      </div>
      <aside className="ro-now" aria-label="Flow now">
        <span className="ro-eyebrow">Flow now</span>
        <strong className="ro-now-value">{fmtFlow(now.flow)}<small> m³/s</small></strong>
        <span className="ro-now-sub">{cusecs(now.flow)} · {now.source}{now.at ? ` · ${fmtDate(now.at, { day: "numeric", month: "short" })}` : ""}</span>
        <StatusPill {...nowClass} />
        <FloodLadder flow={now.flow} thresholds={thresholds} />
      </aside>
    </header>

    {errors.length > 0 && <p className="ro-banner" role="status"><Info size={15} aria-hidden />Some sources could not refresh — {errors.join(" · ")}</p>}

    <nav className="ro-ribbon" aria-label="Forecast horizons">
      <button type="button" onClick={() => jump("ro-days")}>
        <span className="ro-ribbon-when">Now</span>
        <strong>{fmtFlow(now.flow)} <small>m³/s</small></strong>
        <Delta value={nowNormal?.mid && now.flow != null ? (now.flow / nowNormal.mid - 1) * 100 : null} suffix="vs normal today" />
        <TrustMeter level={now.flow != null ? 5 : 0} label={now.flow != null ? "Measured" : "No reading"} />
      </button>
      <button type="button" onClick={() => jump("ro-days")}>
        <span className="ro-ribbon-when">Next 7 days</span>
        <strong>{fmtFlow(ready ? sevenValue : null)} <small>m³/s</small></strong>
        {ready ? <StatusPill label={next7Class.status === "good" ? "Stays below flood level" : next7Class.label} status={next7Class.status} /> : <span className="ro-delta none">No model yet</span>}
        <TrustMeter level={ready ? 2 : 0} label={ready ? (live ? "Low–moderate" : "Global model only") : "—"} />
      </button>
      <button type="button" onClick={() => jump("ro-season")}>
        <span className="ro-ribbon-when">Next 6 months</span>
        <strong>{fmtFlow(season?.mean_p50)} <small>m³/s avg</small></strong>
        <Delta value={seasonDelta} />
        <TrustMeter level={ready ? 2 : 0} label={ready ? "Low" : "—"} />
      </button>
      <button type="button" onClick={() => jump("ro-climate")}>
        <span className="ro-ribbon-when">2026–2040</span>
        <strong>{ssp245 ? oneIn(ssp245.pooled_flood_odds.p400k) : "—"}</strong>
        <span className="ro-ribbon-note">{ssp245 ? "very high flood (≥400k cusecs)" : "No projection yet"}</span>
        <TrustMeter level={ready ? 3 : 0} label={ready ? "Direction clear, size uncertain" : "—"} />
      </button>
    </nav>

    {loading && !outlook && <div className="ro-loading"><RefreshCw className="spinning" aria-hidden /><strong>Loading the outlook</strong></div>}

    {outlook && <>
      <DaysSection ready={ready} stationName={stationName} today={today} readings={readings} normals={normals} forecast={forecast} live={live} glofas={glofas} extended={extended} thresholds={thresholds} />
      <Section id="ro-replay" step="Model replay · real floods" icon={<Brain size={20} />} title="How the trained models forecast past floods"
        lede="Every short-range model trained for Marala, replayed on the three biggest high-flow events of 2022–2024 that they never saw in training. Pick an event and how many days ahead the forecast was made; click a model name to learn how it works.">
        {ready ? <ModelReplaySection replay={ready.replay} /> : <ReplaySkeleton stationName={stationName} />}
      </Section>
      <SeasonSection ready={ready} stationName={stationName} today={today} readings={readings} />
      <ClimateSection ready={ready} stationName={stationName} />
      <EvidenceSection ready={ready} forecast={forecast} stationName={stationName} />
    </>}
  </section>;
}

/* ------------------------------------------------------------------ horizon 1: days */
function DaysSection({ ready, stationName, today, readings, normals, forecast, live, glofas, extended, thresholds }: {
  ready: RiverineOutlookAvailable | null; stationName: string; today: number; readings: Map<number, number>; normals: Map<number, NormalDay>;
  forecast: MaralaStationForecastData | null; live: boolean; glofas: RiverineExtendedForecastData["daily_forecast"]; extended: RiverineExtendedForecastData | null; thresholds?: Record<string, number>;
}) {
  const start = today - 30 * DAY;
  const end = today + 30 * DAY;
  const gauge = live && forecast ? forecast.forecasts.map((f) => {
    const values = (f.candidates ?? []).map((c) => c.inflow_cumecs);
    return { t: utcDay(Date.parse(f.target_at) + 5 * 3_600_000), lead: f.horizon_days, v: f.candidates?.[0]?.inflow_cumecs ?? f.champion.inflow_cumecs, lo: values.length ? Math.min(...values) : null, hi: values.length ? Math.max(...values) : null };
  }) : [];
  const glofasByDay = new Map(glofas.map((r) => [toT(r.date), r]));
  const series: ChartSeries[] = [];
  if (ready) {
    const days = Array.from({ length: 61 }, (_, i) => start + i * DAY);
    series.push({ id: "normal", kind: "band", className: "ro-band-normal", points: days.map((t) => ({ t, lo: normals.get(t)?.lo, hi: normals.get(t)?.hi })) });
    series.push({ id: "normal-mid", kind: "line", className: "ro-line-normal", points: days.map((t) => ({ t, v: normals.get(t)?.mid })) });
    series.push({ id: "glofas-band", kind: "band", className: "ro-band-provider", points: glofas.map((r) => ({ t: toT(r.date), lo: r.p25_cumecs, hi: r.p75_cumecs })) });
    series.push({ id: "glofas", kind: "line", className: "ro-line-provider", points: glofas.map((r) => ({ t: toT(r.date), v: r.median_cumecs })) });
    series.push({ id: "observed", kind: "line", className: "ro-line-observed", markers: true, points: [...readings].sort((a, b) => a[0] - b[0]).map(([t, v]) => ({ t, v })) });
    if (gauge.length) series.push({ id: "gauge", kind: "dots", className: "ro-dots-model", points: gauge });
  }
  const showFloodLine = thresholds && series.some((s) => !s.id.startsWith("normal") && s.points.some((p) => p.t >= start && p.t <= end && (p.hi ?? p.v ?? 0) > thresholds.Low * 0.45));
  const leads = [1, 3, 7, 14, 30];

  return <Section id="ro-days" step="Horizon 1 · Days ahead" icon={<Activity size={20} />} title="The next 30 days"
    lede="Recent gauge readings, the station gauge model for 1, 3 and 7 days, and the global GloFAS river model to 30 days — set against the normal range for the time of year.">
    {!ready ? <div className="ro-grid-days">
      <EmptyPlot height={380} title={`No day-ahead model for ${stationName}`} note="A gauge model needs at least two seasons of daily 06:00 readings from this station." />
      <div className="ro-card ro-lead-table">
        <h4>Day-ahead estimates</h4>
        <table>
          <thead><tr><th>Ahead</th><th>Gauge model</th><th>Global model</th><th>Normal</th></tr></thead>
          <tbody>{leads.map((lead) => <tr key={lead}><th scope="row">+{lead} d<small>{fmtDate(today + lead * DAY, { day: "numeric", month: "short" })}</small></th><td className="muted">—</td><td className="muted">—</td><td className="muted">—</td></tr>)}</tbody>
        </table>
        <p className="ro-foot">No model results for {stationName} yet.</p>
      </div>
    </div> : <div className="ro-grid-days">
      <div className="ro-card">
        <ModelTags ids={["gauge", "glofas", "normal"]} />
        <TimeChart ariaLabel={`${stationName} flow, 30 days back and 30 days ahead`} height={340} start={start} end={end} series={series} ticks="week"
          markers={[{ t: today, label: "Today", className: "ro-marker today" }]}
          hlines={showFloodLine ? [{ v: thresholds!.Low, label: "Low flood level", className: "ro-hline flood" }] : []}
          tooltip={(t) => {
            const g = glofasByDay.get(t); const n = normals.get(t); const m = gauge.find((p) => p.t === t); const o = readings.get(t);
            return <Tip title={fmtDate(t, { weekday: "short", day: "numeric", month: "short" })} rows={[
              o != null && ["Measured", `${fmtFlow(o)} m³/s`],
              m != null && [`Gauge model +${m.lead}d`, `${fmtFlow(m.v)} m³/s (${fmtFlow(m.lo)}–${fmtFlow(m.hi)})`],
              g?.median_cumecs != null && ["Global model", `${fmtFlow(g.median_cumecs)} m³/s`],
              n?.mid != null && ["Normal", `${fmtFlow(n.mid)} m³/s (${fmtFlow(n.lo)}–${fmtFlow(n.hi)})`],
            ]} />;
          }} />
        <Legend items={[
          { cls: "observed", label: "Measured 06:00 inflow (FFD)" },
          ...(gauge.length ? [{ cls: "model", label: "Gauge model estimate, range of top 5 models" }] : []),
          { cls: "provider", label: "Global model GloFAS, median and middle 50%" },
          { cls: "normal", label: "Normal range for the date (2016–2025, 10–90%)" },
        ]} />
        {!live && <p className="ro-note"><Info size={14} aria-hidden />The station gauge model reruns as soon as FFD publishes today’s 06:00 Marala reading; until then only the global model looks ahead.{forecast ? ` Its last run was issued from the ${fmtDate(Date.parse(forecast.origin.observed_at), { day: "numeric", month: "short" })} reading.` : ""}</p>}
      </div>
      <div className="ro-card ro-lead-table">
        <h4>Day-ahead estimates</h4>
        <ModelTags ids={["gauge", "glofas"]} label="From" />
        <table>
          <thead><tr><th>Ahead</th><th>Gauge model</th><th>Global model</th><th>Normal</th></tr></thead>
          <tbody>{leads.map((lead) => {
            const t = today + lead * DAY;
            const g = gauge.find((p) => p.lead === lead);
            const gl = glofasByDay.get(t);
            const n = normals.get(t);
            return <tr key={lead}>
              <th scope="row">+{lead} d<small>{fmtDate(t, { day: "numeric", month: "short" })}</small></th>
              <td>{g ? <><b>{fmtFlow(g.v)}</b><small>{fmtFlow(g.lo)}–{fmtFlow(g.hi)}</small></> : <span className="muted">{lead <= 7 ? (live ? "—" : "waiting") : "not trained"}</span>}</td>
              <td>{gl?.median_cumecs != null ? <><b>{fmtFlow(gl.median_cumecs)}</b>{gl.p25_cumecs != null && gl.p75_cumecs != null && Math.round(gl.p25_cumecs) !== Math.round(gl.p75_cumecs) && <small>{fmtFlow(gl.p25_cumecs)}–{fmtFlow(gl.p75_cumecs)}</small>}</> : <span className="muted">{lead > glofas.length ? "beyond run" : "—"}</span>}</td>
              <td>{n?.mid != null ? <><b>{fmtFlow(n.mid)}</b><small>{fmtFlow(n.lo)}–{fmtFlow(n.hi)}</small></> : <span className="muted">—</span>}</td>
            </tr>;
          })}</tbody>
        </table>
        <p className="ro-foot">All values m³/s. The global model simulates the river reach, not the gauge; over 2024–2026 it carried about {Math.abs(Math.round(ready.evidence.glofas_pbias_pct ?? 0))}% less water than measured at Marala, so treat it as a trend line.{extended?.status === "stale" ? " Showing its last saved run." : ""}</p>
      </div>
    </div>}
  </Section>;
}

/* ------------------------------------------------------------------ horizon 2: season */
function SeasonSection({ ready, stationName, today, readings }: { ready: RiverineOutlookAvailable | null; stationName: string; today: number; readings: Map<number, number> }) {
  const [history, setHistory] = useState<30 | 365>(30);
  if (!ready) {
    const first = new Date(today);
    const months = Array.from({ length: 6 }, (_, i) => Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + i, 1));
    return <Section id="ro-season" step="Horizon 2 · Season ahead" icon={<CalendarRange size={20} />} title="The next 6 months" lede="Daily flow outlook with its likely range, monthly averages and how they compare with a normal year.">
      <EmptyPlot height={380} title={`No seasonal model for ${stationName}`} note="Seasonal models need several years of daily observed flow at the station plus catchment weather and snow data." />
      <div className="ro-months" role="list" aria-label="Monthly average outlook">
        {months.map((m) => <article role="listitem" key={m} className="ro-month empty">
          <header><strong>{fmtDate(m, { month: "short" })}</strong><small>{new Date(m).getUTCFullYear()}</small></header>
          <b>—<small> m³/s</small></b><div className="ro-month-bar" aria-hidden /><small className="ro-month-range">no outlook</small>
        </article>)}
      </div>
      <div className="ro-grid-3">
        <div className="ro-card ro-stat-card"><h4><Gauge size={16} aria-hidden />Average flow ahead</h4>{[90, 180].map((d) => <div className="ro-stat-row" key={d}><span>Next {d} days</span><b className="muted">—</b></div>)}</div>
        <div className="ro-card ro-stat-card"><h4><ShieldAlert size={16} aria-hidden />Flood headroom</h4><div className="ro-headroom"><b className="empty">—</b><span>Needs a seasonal outlook and official flood levels for {stationName}.</span></div></div>
        <div className="ro-card ro-stat-card"><h4><CheckCircle2 size={16} aria-hidden />Last year’s run</h4><EmptyPlot height={150} title="No track record" note="Appears after a model is tested here." /></div>
      </div>
    </Section>;
  }

  const s = ready.seasonal;
  const issue = toT(s.issue_date);
  const end = toT(s.daily[s.daily.length - 1].date);
  const start = issue - history * DAY;
  const observed = [...s.observed_last_365.map((r) => ({ t: toT(r.date), v: r.observed }))];
  const after = [...readings].filter(([t]) => t > issue).sort((a, b) => a[0] - b[0]).map(([t, v]) => ({ t, v }));
  const forecastByDay = new Map(s.daily.map((r) => [toT(r.date), r]));
  const lastByDay = new Map(s.observed_last_365.map((r) => [toT(r.date), r]));
  const afterByDay = new Map(after.map((p) => [p.t, p.v]));
  const insideSince = after.filter((p) => { const f = forecastByDay.get(p.t); return f && f.p10 != null && f.p90 != null && p.v >= f.p10 && p.v <= f.p90; }).length;
  const normalPoints = [...s.observed_last_365, ...s.daily].map((r) => ({ t: toT(r.date), lo: r.normal_p10, hi: r.normal_p90, v: r.normal_p50 }));
  const series: ChartSeries[] = [
    { id: "normal", kind: "band", className: "ro-band-normal", points: normalPoints },
    { id: "normal-mid", kind: "line", className: "ro-line-normal", points: normalPoints },
    { id: "fc-band", kind: "band", className: "ro-band-model", points: s.daily.map((r) => ({ t: toT(r.date), lo: r.p10, hi: r.p90 })) },
    { id: "fc", kind: "line", className: "ro-line-model", points: s.daily.map((r) => ({ t: toT(r.date), v: r.p50 })) },
    { id: "obs", kind: "line", className: "ro-line-observed", points: observed },
    { id: "obs-after", kind: "line", className: "ro-line-observed", markers: true, points: after },
  ];
  const tr = s.track_record;
  const trSeries: ChartSeries[] = [
    { id: "tr-band", kind: "band", className: "ro-band-model", points: tr.daily.map((r) => ({ t: toT(r.date), lo: r.p10, hi: r.p90 })) },
    { id: "tr-fc", kind: "line", className: "ro-line-model", points: tr.daily.map((r) => ({ t: toT(r.date), v: r.p50 })) },
    { id: "tr-obs", kind: "line", className: "ro-line-observed", points: tr.daily.map((r) => ({ t: toT(r.date), v: r.observed })) },
  ];
  const trByDay = new Map(tr.daily.map((r) => [toT(r.date), r]));
  const low = ready.flood_classes_cumecs.Low;

  return <Section id="ro-season" step="Horizon 2 · Season ahead" icon={<CalendarRange size={20} />} title="The next 6 months"
    lede={`Daily flow outlook from ${fmtDate(issue, { day: "numeric", month: "long" })} with the range it expects 8 days in 10, monthly averages, and how both compare with a normal year.`}
    aside={<div className="ro-toggle" role="group" aria-label="History shown">
      {([30, 365] as const).map((d) => <button key={d} type="button" aria-pressed={history === d} onClick={() => setHistory(d)}>{d === 30 ? "Past month" : "Past 12 months"}</button>)}
    </div>}>
    <div className="ro-card">
      <ModelTags ids={["tft_seasonal", "normal"]} />
      <TimeChart ariaLabel={`${stationName} six-month flow outlook`} height={380} start={start} end={end} series={series} ticks="month"
        markers={[{ t: issue, label: "Outlook issued", className: "ro-marker" }, { t: today, label: "Today", className: "ro-marker today" }]}
        tooltip={(t) => {
          const f = forecastByDay.get(t); const l = lastByDay.get(t); const o = afterByDay.get(t) ?? l?.observed;
          const n = f ?? l;
          return <Tip title={fmtDate(t, { weekday: "short", day: "numeric", month: "short", year: "numeric" })} rows={[
            o != null && ["Measured", `${fmtFlow(o)} m³/s`],
            f?.p50 != null && ["Outlook", `${fmtFlow(f.p50)} m³/s (${fmtFlow(f.p10)}–${fmtFlow(f.p90)})`],
            n?.normal_p50 != null && ["Normal", `${fmtFlow(n.normal_p50)} m³/s (${fmtFlow(n.normal_p10)}–${fmtFlow(n.normal_p90)})`],
          ]} />;
        }} />
      <Legend items={[
        { cls: "observed", label: "Measured inflow" },
        { cls: "model", label: "Outlook median and likely range (10–90%)" },
        { cls: "normal", label: "Normal range for the date (2016–2025)" },
      ]} />
      {after.length > 0 && <p className="ro-note good"><CheckCircle2 size={14} aria-hidden />Since the outlook was issued, {insideSince} of {after.length} measured days fell inside its likely range.</p>}
    </div>

    <ModelTags ids={["tft_seasonal"]} label="Monthly averages from" />
    <div className="ro-months" role="list" aria-label="Monthly average outlook">
      {s.monthly.filter((m) => m.days >= 7).map((m) => {
        const width = (v: number | null) => `${Math.min(100, ((v ?? 0) / Math.max(...s.monthly.map((x) => x.p90 ?? 0))) * 100)}%`;
        return <article role="listitem" key={m.month} className="ro-month">
          <header><strong>{monthName(m.month)}</strong><small>{m.month.slice(0, 4)}{m.partial ? ` · ${m.days} days` : ""}</small></header>
          <b>{fmtFlow(m.p50)}<small> m³/s</small></b>
          <div className="ro-month-bar" aria-hidden><span className="range" style={{ left: width(m.p10), width: `calc(${width(m.p90)} - ${width(m.p10)})` }} /><span className="normal" style={{ left: width(m.normal_p50) }} /></div>
          <small className="ro-month-range">{fmtFlow(m.p10)}–{fmtFlow(m.p90)}</small>
          <Delta value={m.change_vs_normal_pct} />
        </article>;
      })}
    </div>

    <div className="ro-grid-3">
      <div className="ro-card ro-stat-card">
        <h4><Gauge size={16} aria-hidden />Average flow ahead</h4>
        <ModelTags ids={["ridge"]} />
        {ready.seasonal_means.horizons.length ? ready.seasonal_means.horizons.map((h) => <div className="ro-stat-row" key={h.horizon_days}>
          <span>Next {h.horizon_days} days<small>to {fmtDate(toT(h.window_end), { day: "numeric", month: "short", year: "numeric" })}</small></span>
          <b>{fmtFlow(h.mean_flow)}<small> m³/s</small></b>
          <Delta value={h.change_vs_normal_pct} />
        </div>) : <p className="ro-foot">{ready.seasonal_means.unavailable_reason}</p>}
        <p className="ro-foot">Seasonal-average model, a separate check on the daily outlook. It beat the normal-season average by 7–8% over 2020–2024.</p>
      </div>
      <div className="ro-card ro-stat-card">
        <h4><ShieldAlert size={16} aria-hidden />Flood headroom</h4>
        <ModelTags ids={["tft_seasonal"]} />
        <div className="ro-headroom">
          <b>{Math.round(((s.peak.p90 ?? 0) / low) * 100)}%</b>
          <span>The top of the likely range peaks at {fmtFlow(s.peak.p90)} m³/s, {Math.round(((s.peak.p90 ?? 0) / low) * 100)}% of the low-flood level ({fmtFlow(low)} m³/s).</span>
        </div>
        <p className="ro-foot">Daily averages hide short flood peaks. The monsoon peak-risk model in Horizon 3 covers flood peaks.</p>
      </div>
      <div className="ro-card ro-stat-card">
        <h4><CheckCircle2 size={16} aria-hidden />Last year’s run</h4>
        <ModelTags ids={["tft_seasonal"]} />
        <TimeChart compact ariaLabel="Same outlook issued one year earlier against measured flow" height={150} start={toT(tr.daily[0].date)} end={toT(tr.daily[tr.daily.length - 1].date)} series={trSeries} ticks="month-name"
          tooltip={(t) => { const r = trByDay.get(t); return r ? <Tip title={fmtDate(t, { day: "numeric", month: "short", year: "numeric" })} rows={[r.observed != null && ["Measured", `${fmtFlow(r.observed)} m³/s`], ["Outlook", `${fmtFlow(r.p50)} (${fmtFlow(r.p10)}–${fmtFlow(r.p90)})`]]} /> : null; }} />
        <p className="ro-foot">Issued {fmtDate(toT(tr.issue_date), { day: "numeric", month: "short", year: "numeric" })}: <b>{share(tr.share_inside_band)}</b> of {tr.observed_days} measured days fell inside the likely range (aim: 80%).</p>
      </div>
    </div>
  </Section>;
}

/* ------------------------------------------------------------------ horizon 3: climate */
const KPI_SLOTS = [
  { icon: <Waves size={17} />, label: "Average river flow" },
  { icon: <CloudRain size={17} />, label: "Monsoon flow (Jul–Sep)" },
  { icon: <Snowflake size={17} />, label: "Snowmelt flow (Apr–Jun)" },
  { icon: <Thermometer size={17} />, label: "Air temperature" },
];
const ODDS_SLOTS = [
  { label: "High flood", sub: "≥200,000 cusecs" },
  { label: "Very high flood", sub: "≥400,000 cusecs" },
  { label: "Exceptional flood", sub: "≥600,000 cusecs" },
];

function ClimateSection({ ready, stationName }: { ready: RiverineOutlookAvailable | null; stationName: string }) {
  const [scenarioId, setScenarioId] = useState<OutlookScenario["id"]>("ssp245");
  if (!ready) return <Section id="ro-climate" step="Horizon 3 · Climate" icon={<Globe2 size={20} />} title="2026–2040 under climate change" lede="How river flow and flood odds change under two emission scenarios.">
    <div className="ro-kpis">
      {KPI_SLOTS.map((slot) => <article key={slot.label} className="ro-kpi">
        <span className="ro-kpi-label">{slot.icon}{slot.label}</span><b className="muted">—</b><div className="ro-kpi-range" aria-hidden><span className="zero" /></div><small>No projection yet</small>
      </article>)}
    </div>
    <div className="ro-grid-climate">
      <div className="ro-card">
        <h4><ShieldAlert size={16} aria-hidden />Chance of a flood in any one year</h4>
        <div className="ro-odds">{ODDS_SLOTS.map((slot) => <div key={slot.label} className="ro-odds-row">
          <span className="ro-odds-name">{slot.label}<small>{slot.sub}</small></span><div className="ro-odds-track" aria-hidden>{[0, 25, 50, 75, 100].map((g) => <i key={g} style={{ left: `${g}%` }} />)}</div><span className="ro-odds-values"><b className="muted">—</b></span>
        </div>)}</div>
      </div>
      <EmptyPlot height={300} title={`No climate projection for ${stationName}`} note="Projections need a station flow model and bias-corrected climate-model inputs for its catchment." />
    </div>
  </Section>;

  const c = ready.climate;
  const scenario = c.scenarios.find((s) => s.id === scenarioId) ?? c.scenarios[0];
  const all = scenario.periods.find((p) => p.period.startsWith("2026") && p.period.endsWith("2040"))!;
  const fiveYear = scenario.periods.filter((p) => p !== all);
  const tone = scenarioId === "ssp585" ? "b" : "a";
  const kpis = [
    { icon: <Waves size={17} />, label: "Average river flow", r: all.mean_flow_pct, unit: "%" },
    { icon: <CloudRain size={17} />, label: "Monsoon flow (Jul–Sep)", r: all.monsoon_pct, unit: "%" },
    { icon: <Snowflake size={17} />, label: "Snowmelt flow (Apr–Jun)", r: all.snowmelt_season_pct, unit: "%" },
    { icon: <Thermometer size={17} />, label: "Air temperature", r: all.temperature_c, unit: "°C" },
  ];
  const odds = [
    { label: "High flood", sub: "≥200,000 cusecs", base: c.baseline_flood_odds.p200k, now: scenario.pooled_flood_odds.p200k },
    { label: "Very high flood", sub: "≥400,000 cusecs", base: c.baseline_flood_odds.p400k, now: scenario.pooled_flood_odds.p400k },
    { label: "Exceptional flood", sub: "≥600,000 cusecs", base: c.baseline_flood_odds.p600k, now: scenario.pooled_flood_odds.p600k },
  ];
  const year = Date.UTC(2001, 0, 1);
  const hydro = c.typical_year_hydrograph;
  const future = hydro[scenarioId];
  const hydroSeries: ChartSeries[] = [
    { id: "gap", kind: "band", className: `ro-band-scenario ${tone}`, points: hydro.baseline.map((v, i) => ({ t: year + i * DAY, lo: v == null || future[i] == null ? null : Math.min(v, future[i] as number), hi: v == null || future[i] == null ? null : Math.max(v, future[i] as number) })) },
    { id: "base", kind: "line", className: "ro-line-baseline", points: hydro.baseline.map((v, i) => ({ t: year + i * DAY, v })) },
    { id: "fut", kind: "line", className: `ro-line-scenario ${tone}`, points: future.map((v, i) => ({ t: year + i * DAY, v })) },
  ];

  return <Section id="ro-climate" step="Horizon 3 · Climate" icon={<Globe2 size={20} />} title="2026–2040 under climate change"
    lede={`Eight climate models drive the flow model under two emission scenarios. Changes compare 2026–2040 with each model’s own 1986–2014 run. These are long-run odds, not a forecast for a particular year.`}
    aside={<div className="ro-toggle" role="group" aria-label="Emission scenario">
      {c.scenarios.map((sc) => <button key={sc.id} type="button" className={sc.id === "ssp585" ? "b" : "a"} aria-pressed={scenarioId === sc.id} onClick={() => setScenarioId(sc.id)}>
        {sc.label}<small>{sc.description}</small>
      </button>)}
    </div>}>
    <ModelTags ids={["tft_climate", "cmip6"]} />
    <div className="ro-kpis">
      {kpis.map((k) => {
        const span = Math.max(Math.abs(k.r.low ?? 0), Math.abs(k.r.high ?? 0), 1) * 1.15;
        const pos = (v: number | null) => `${50 + ((v ?? 0) / span) * 50}%`;
        return <article key={k.label} className="ro-kpi">
          <span className="ro-kpi-label">{k.icon}{k.label}</span>
          <b>{k.unit === "%" ? pct(k.r.median, 1) : `+${(k.r.median ?? 0).toFixed(2)} °C`}</b>
          <div className={`ro-kpi-range ${tone}`} aria-hidden><span className="zero" /><span className="spread" style={{ left: pos(k.r.low), width: `calc(${pos(k.r.high)} - ${pos(k.r.low)})` }} /><span className="mid" style={{ left: pos(k.r.median) }} /></div>
          <small>8 models: {k.unit === "%" ? `${pct(k.r.low, 1)} to ${pct(k.r.high, 1)}` : `+${(k.r.low ?? 0).toFixed(2)} to +${(k.r.high ?? 0).toFixed(2)} °C`}</small>
        </article>;
      })}
    </div>

    <div className="ro-grid-climate">
      <div className="ro-card">
        <h4><ShieldAlert size={16} aria-hidden />Chance of a flood in any one year</h4>
        <ModelTags ids={["peak_model", "cmip6"]} />
        <div className="ro-odds">
          {odds.map((o) => <div key={o.label} className="ro-odds-row">
            <span className="ro-odds-name">{o.label}<small>{o.sub}</small></span>
            <div className="ro-odds-track" aria-hidden>
              {[0, 25, 50, 75, 100].map((g) => <i key={g} style={{ left: `${g}%` }} />)}
              <span className={`line ${tone}`} style={{ left: `${Math.min(o.base ?? 0, o.now ?? 0) * 100}%`, width: `${Math.abs((o.now ?? 0) - (o.base ?? 0)) * 100}%` }} />
              <span className="dot base" style={{ left: `${(o.base ?? 0) * 100}%` }} />
              <span className={`dot now ${tone}`} style={{ left: `${(o.now ?? 0) * 100}%` }} />
            </div>
            <span className="ro-odds-values"><b>{share(o.base)} → {share(o.now)}</b><small>{oneIn(o.now)}</small></span>
          </div>)}
        </div>
        <Legend items={[{ cls: "baseline", label: "1986–2014 climate" }, { cls: `scenario ${tone}`, label: `2026–2040 · ${scenario.label}` }]} />
        <p className="ro-foot">From the storm-rainfall flood-peak model, run on every year of all 8 climate models. Flood classes are the official FFD limits for Marala.</p>
      </div>
      <div className="ro-card">
        <h4><Mountain size={16} aria-hidden />A typical year, then and now</h4>
        <ModelTags ids={["tft_climate", "cmip6"]} />
        <TimeChart ariaLabel="Typical-year daily flow, 1986–2014 against 2026–2040" height={260} start={year} end={year + 364 * DAY} series={hydroSeries} ticks="month-name"
          tooltip={(t) => {
            const i = Math.round((t - year) / DAY); const b = hydro.baseline[i]; const f = future[i];
            return b == null ? null : <Tip title={fmtDate(t, { day: "numeric", month: "long" })} rows={[["1986–2014", `${fmtFlow(b)} m³/s`], ["2026–2040", `${fmtFlow(f)} m³/s`], f != null && ["Change", pct((f / b - 1) * 100, 1)]]} />;
          }} />
        <Legend items={[{ cls: "baseline", label: "1986–2014 (median of 8 models)" }, { cls: `scenario ${tone}`, label: `2026–2040 · ${scenario.label}` }, { cls: `gap ${tone}`, label: "Change" }]} />
        <p className="ro-foot">The seasonal shape holds: the peak stays in July with no earlier snowmelt by 2040. More water arrives through most of the year.</p>
      </div>
    </div>

    <div className="ro-grid-climate">
      <div className="ro-card">
        <h4><CalendarRange size={16} aria-hidden />Very high flood odds, year by year</h4>
        <ModelTags ids={["peak_model", "cmip6"]} />
        <OddsBars ariaLabel="Chance of a very high flood each year 2026–2040" className={`ro-bars ${tone}`} baseline={c.baseline_flood_odds.p400k}
          rows={scenario.yearly_flood_odds.map((y) => ({ label: String(y.year), value: y.p400k, low: y.p400k_low, high: y.p400k_high }))} />
        <Legend items={[{ cls: `bar ${tone}`, label: `Chance of a very high flood · ${scenario.label}` }, { cls: "baseline-dash", label: `1986–2014 climate: ${share(c.baseline_flood_odds.p400k)}` }]} />
        <p className="ro-foot">Bars are the median of 8 climate models, whiskers their range. Single years swing with natural weather; read the overall level, not one year.</p>
      </div>
      <div className="ro-card">
        <h4><Sparkles size={16} aria-hidden />Five-year steps</h4>
        <ModelTags ids={["tft_climate", "peak_model"]} />
        <table className="ro-table">
          <thead><tr><th>Period</th><th>Average flow</th><th>Monsoon</th><th>Winter low flow</th><th>Very high flood</th></tr></thead>
          <tbody>{[...fiveYear, all].map((p) => <tr key={p.period} className={p === all ? "total" : ""}>
            <th scope="row">{p.period}</th>
            <td>{pct(p.mean_flow_pct.median, 1)}</td><td>{pct(p.monsoon_pct.median, 1)}</td><td>{pct(p.low_flow_season_pct.median, 1)}</td>
            <td>{share(p.p400k.baseline)} → {share(p.p400k.median)}</td>
          </tr>)}</tbody>
        </table>
        <p className="ro-foot">Medians across 8 climate models. Five-year values are mostly natural variability; the 2026–2040 row is the robust signal. Assumes no change in upstream regulation.</p>
      </div>
    </div>
  </Section>;
}

/* ------------------------------------------------------------------ evidence */
const MODEL_SLOTS = [
  { icon: <Activity size={18} />, id: "gauge", name: "Gauge model", horizon: "1 · 3 · 7 days", uses: "Recent FFD 06:00 inflow and outflow readings" },
  { icon: <Globe2 size={18} />, id: "glofas", name: "Global river model (GloFAS)", horizon: "to 30 days", uses: "Copernicus global hydrology model, nearest river cell" },
  { icon: <CalendarRange size={18} />, id: "tft_seasonal", name: "Seasonal flow model (TFT)", horizon: "180 days, daily", uses: "A year of catchment rain, snow and temperature, plus measured flow" },
  { icon: <Gauge size={18} />, id: "ridge", name: "Seasonal-average model", horizon: "90 and 180 days", uses: "Recent flow levels, rain, snow and temperature" },
  { icon: <Thermometer size={18} />, id: "tft_climate", name: "Climate flow model (TFT + 8 GCMs)", horizon: "2026–2040", uses: "Bias-corrected rain and temperature from 8 CMIP6 climate models" },
  { icon: <ShieldAlert size={18} />, id: "peak_model", name: "Flood-peak model", horizon: "each monsoon", uses: "Largest 3-day monsoon rainfall over the catchment" },
];

function EvidenceSection({ ready, forecast, stationName }: { ready: RiverineOutlookAvailable | null; forecast: MaralaStationForecastData | null; stationName: string }) {
  if (!ready) return <Section id="ro-evidence" step="Evidence" icon={<CheckCircle2 size={20} />} title="How far to trust each outlook" lede="Each model, what it uses and how it scored on years it never saw.">
    <div className="ro-models">
      {MODEL_SLOTS.map((slot) => <article className="ro-model empty" key={slot.name}>
        <header><span className="ro-model-icon" aria-hidden>{slot.icon}</span><div><strong>{slot.name}</strong><small>{slot.horizon}</small></div></header>
        <ModelTag id={slot.id} compact />
        <dl><dt>Uses</dt><dd>{slot.uses}</dd><dt>Tested</dt><dd>Not trained for {stationName} yet.</dd></dl>
        <footer><TrustMeter level={0} label="—" /><span className="ro-chip off">Not trained</span></footer>
      </article>)}
    </div>
  </Section>;

  const e = ready.evidence;
  const skill = (lead: number) => forecast?.skill.find((s) => s.horizon_days === lead)?.rmse_improvement_over_persistence_percent;
  const ridge90 = e.ridge.find((r) => r.horizon_days === 90);
  const vsNormal = (v: number | null) => v == null ? "—" : Math.abs(v) < 0.02 ? "matches" : `${Math.round(Math.abs(v) * 100)}% ${v > 0 ? "better than" : "worse than"}`;
  const cards = [
    { icon: <Activity size={18} />, id: "gauge", name: "Gauge model", horizon: "1 · 3 · 7 days", uses: "Recent FFD 06:00 inflow and outflow readings", result: forecast ? `7 days ahead it was ${skill(7) == null ? "—" : `${Math.abs(skill(7) as number).toFixed(1)}%`} more accurate than assuming no change; 1 day ahead it matched it, and 3 days ahead it was worse.` : "Test results unavailable.", trust: 2, trustLabel: "Low–moderate" },
    { icon: <Globe2 size={18} />, id: "glofas", name: "Global river model (GloFAS)", horizon: "to 30 days", uses: "Copernicus global hydrology model, nearest river cell", result: `Follows the seasonal rise and fall, but carried about ${Math.abs(Math.round(e.glofas_pbias_pct ?? 0))}% less water than Marala measured over 2024–2026.`, trust: 2, trustLabel: "Trend only" },
    { icon: <CalendarRange size={18} />, id: "tft_seasonal", name: "Seasonal flow model (TFT)", horizon: "180 days, daily", uses: "A year of catchment rain, snow and temperature, plus measured flow", result: `On 2024–2026 it ${vsNormal(e.tft_forecast.skill_vs_normal)} a normal-year guess; ${share(e.tft_forecast.band_coverage)} of days fell in its range (aim 80%).`, trust: 2, trustLabel: "Low" },
    { icon: <Gauge size={18} />, id: "ridge", name: "Seasonal-average model", horizon: "90 and 180 days", uses: "Recent flow levels, rain, snow and temperature", result: `${vsNormal(ridge90?.skill_vs_normal ?? null)} the normal-season average at 90 days (2020–2024) and flagged ${share(ridge90?.high_flow_hit_rate)} of high-flow seasons.`, trust: 3, trustLabel: "Moderate" },
    { icon: <Thermometer size={18} />, id: "tft_climate", name: "Climate flow model (TFT + 8 GCMs)", horizon: "2026–2040", uses: "Bias-corrected rain and temperature from 8 CMIP6 climate models", result: `Given the actual weather it was ${vsNormal(e.tft_projection.skill_vs_normal)} a normal-year guess, with ${share(e.tft_projection.band_coverage)} of days inside its range.`, trust: 3, trustLabel: "Moderate" },
    { icon: <ShieldAlert size={18} />, id: "peak_model", name: "Flood-peak model", horizon: "each monsoon", uses: "Largest 3-day monsoon rainfall over the catchment", result: `Its flood odds were ${Math.round((1 - (ready.peak_model.brier_400k_loo ?? 0) / (ready.peak_model.brier_400k_no_predictor ?? 1)) * 100)}% more accurate than the historical base rate; the 2025 flood (${fmtFlow(ready.peak_model.test_2025.observed_peak)} m³/s) fell inside its range.`, trust: 3, trustLabel: "Moderate" },
  ];

  return <Section id="ro-evidence" step="Evidence" icon={<CheckCircle2 size={20} />} title="How far to trust each outlook"
    lede="Every model was scored on years it never saw during training. All are experimental and none drives official alerts.">
    <div className="ro-models">
      {cards.map((card) => <article className="ro-model" key={card.name}>
        <header><span className="ro-model-icon" aria-hidden>{card.icon}</span><div><strong>{card.name}</strong><small>{card.horizon}</small></div></header>
        <ModelTag id={card.id} compact />
        <dl><dt>Uses</dt><dd>{card.uses}</dd><dt>Tested</dt><dd>{card.result}</dd></dl>
        <footer><TrustMeter level={card.trust} label={card.trustLabel} /><span className="ro-chip">Experimental</span></footer>
      </article>)}
    </div>
    <p className="ro-note"><Brain size={14} aria-hidden />The {ready.replay.models.length} short-range research models are compared on real floods in the Model replay section above.</p>
  </Section>;
}
