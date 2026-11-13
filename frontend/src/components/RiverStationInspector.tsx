import { Activity, ArrowDownRight, ArrowRight, ArrowUpRight, ChartColumn, ChevronDown, CloudRain, Gauge, Info, RadioTower, RefreshCw, TrendingUp, Waves, X } from "lucide-react";
import { lazy, Suspense, useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";

import type { RiverMonitoringStation, RiverMonitoringResponse } from "../types/api";
import { ForecastChart } from "./SourceFloodForecastTab";
import { formatFlow, type FlowUnit } from "./waterQuantities";
import { RiverDataSource } from "./RiverDataSource";
import { stationWaterLevel } from "./stationInfo";
import "../station-console.css";
const StationForecastWindow = lazy(() => import("./StationForecastWindow"));

// The station panel as a monitoring console: one hero reading with its
// hydrograph, three reading cards, compact status lists and a station strip.
// Everything fits the panel without scrolling: the cards are sized to the
// height available, and on a short panel they split into two pages. Rarely
// needed detail (every model statistic, why the station is monitored) opens
// as a sheet over the cards. Cards rise into place in sequence.

function timestamp(value: string | null | undefined) {
  if (!value) return "Unavailable";
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return `${new Intl.DateTimeFormat("en-PK", { month: "short", day: "numeric", timeZone: "UTC" }).format(new Date(value))} (daily forecast)`;
  return `${new Intl.DateTimeFormat("en-PK", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: "Asia/Karachi" }).format(new Date(value))} PKT`;
}

function compactDate(value: string | null | undefined) {
  if (!value) return "Unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-PK", { month: "short", day: "numeric", timeZone: "UTC" }).format(date);
}

function numberLabel(value: number | null | undefined, digits = 1) {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString("en-PK", { maximumFractionDigits: digits })
    : "Unavailable";
}

function metricLabel(key: string) {
  return key.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase())
    .replace(/Geoglows/gi, "GEOGloWS").replace(/Glofas/gi, "GloFAS");
}

function metricValue(key: string, value: number | string | null, flowUnit: FlowUnit) {
  if (value == null) return "Unavailable";
  if (typeof value !== "number") return value;
  if (key.endsWith("_cumecs")) return formatFlow(value, flowUnit);
  if (key.endsWith("_mm")) return `${numberLabel(value)} mm`;
  if (key.endsWith("_percent")) return `${numberLabel(value, 0)}%`;
  if (key.endsWith("_ratio")) return `${numberLabel(value, 2)}×`;
  return numberLabel(value, 2);
}

/** Colour tone for an FFD flood category. */
function categoryTone(category: string) {
  const value = category.toLowerCase();
  if (/exceptional|very high|danger/.test(value)) return "danger";
  if (/high/.test(value)) return "warning";
  if (/medium|moderate/.test(value)) return "watch";
  if (/below|low|normal/.test(value)) return "calm";
  return "neutral";
}
const severityTone: Record<string, string> = { LOW: "calm", MEDIUM: "watch", HIGH: "warning", CRITICAL: "danger" };
const providerTone = (status: string) => /avail|ok|live|active/i.test(status) && !/unavail/i.test(status) ? "calm" : /unavail|error|fail/i.test(status) ? "muted" : "watch";

const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const rise = (order: number): CSSProperties => ({ "--rise-delay": `${order * 70}ms` } as CSSProperties);

/** A number that eases from the value shown before (e.g. the previous station's) to the new one. */
function CountUp({ value, from, format }: { value: number | null; from: number | null; format: (value: number | null) => string }) {
  const [shown, setShown] = useState(value === null || from === null || reducedMotion() ? value : from);
  useEffect(() => {
    if (value === null || from === null || reducedMotion() || from === value) { setShown(value); return; }
    let frame = 0;
    const started = performance.now(), duration = 900;
    const step = (now: number) => {
      const t = Math.min(1, (now - started) / duration), eased = 1 - (1 - t) ** 3;
      setShown(from + (value - from) * eased);
      if (t < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [value, from]);
  return <>{format(shown)}</>;
}

/**
 * Sizes the cards to the panel so nothing scrolls. Spare height goes to the
 * hydrograph; a small shortfall shrinks the cards slightly; a large one splits
 * them into two pages (returned as `paged`), each fitted the same way.
 */
function useFitToPanel(page: number, contentKey: string) {
  const bodyRef = useRef<HTMLDivElement>(null), gridRef = useRef<HTMLDivElement>(null);
  const [paged, setPaged] = useState(false);
  useLayoutEffect(() => {
    const body = bodyRef.current, grid = gridRef.current;
    if (!body || !grid) return;
    const overflows = () => body.scrollHeight > body.clientHeight + 0.5;
    const shrink = (floor: number) => {
      let zoom = 1;
      for (let pass = 0; pass < 6 && overflows() && zoom > floor; pass++) {
        zoom = Math.max(floor, zoom * (body.clientHeight / body.scrollHeight) * 0.995);
        grid.style.setProperty("zoom", String(zoom));
      }
      return !overflows();
    };
    const fit = () => {
      grid.style.removeProperty("zoom");
      grid.style.removeProperty("--chart-height");
      grid.removeAttribute("data-page");
      // Narrow screens stack the panel under the map, where the page itself scrolls.
      if (getComputedStyle(body).overflowY === "visible") { setPaged(false); return; }
      let split = false;
      if (!shrink(0.86)) {
        split = true;
        grid.style.removeProperty("zoom");
        grid.setAttribute("data-page", String(page));
        shrink(0.7);
      }
      const spare = body.getBoundingClientRect().bottom - grid.getBoundingClientRect().bottom - 8;
      if (!grid.style.getPropertyValue("zoom") && spare > 6 && (!split || page === 1)) {
        grid.style.setProperty("--chart-height", `${100 + Math.min(spare, 130)}px`);
        if (overflows()) grid.style.removeProperty("--chart-height");
      }
      setPaged(split);
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(body);
    observer.observe(grid);
    return () => observer.disconnect();
  }, [page, contentKey]);
  return { bodyRef, gridRef, paged };
}

/**
 * Keeps the panel clear of the bars it shares the map with: below the command
 * stats bar, and above the analytics ticker and the legend's entries, so the
 * station name and cards never sit on top of them.
 */
function useClearOfMapBars() {
  const panelRef = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    const panel = panelRef.current;
    if (!panel) return;
    const find = (selector: string) => document.querySelector<HTMLElement>(selector);
    const place = () => {
      panel.style.removeProperty("--console-top");
      panel.style.removeProperty("--console-bottom");
      const own = panel.getBoundingClientRect();
      // Narrow screens stack the panel under the map, where nothing overlaps it.
      if (getComputedStyle(panel).position !== "absolute") return;
      const crosses = (box: DOMRect) => box.width > 0 && box.right > own.left && box.left < own.right;
      const bar = find(".command-stats-deck")?.getBoundingClientRect();
      const top = bar && crosses(bar) ? Math.round(bar.bottom - own.top + 10) : 0;
      // Never at the cost of most of the panel's height (an opened bar tab).
      if (top > 0 && top < own.height * 0.3) panel.style.setProperty("--console-top", `${top}px`);
      // The legend only counts where its entries reach under the panel; its empty end does not.
      const legendEnd = find(".map-legend > :last-child")?.getBoundingClientRect();
      const below = [find(".hourly-analytics-ticker")?.getBoundingClientRect(), legendEnd && crosses(legendEnd) ? find(".map-legend")?.getBoundingClientRect() : undefined]
        .filter((box): box is DOMRect => Boolean(box && crosses(box) && box.top > own.top + own.height / 2));
      const bottom = below.length ? Math.round(own.bottom - Math.min(...below.map((box) => box.top)) + 8) : 0;
      if (bottom > 0 && bottom < own.height * 0.3) panel.style.setProperty("--console-bottom", `${bottom}px`);
    };
    place();
    const observer = new ResizeObserver(place);
    for (const element of [panel, find(".command-stats-deck"), find(".map-legend"), find(".hourly-analytics-ticker")]) if (element) observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return panelRef;
}

const Live = () => <span className="console-live"><i aria-hidden="true" />Live</span>;

function RainBars({ station }: { station: RiverMonitoringStation }) {
  const points = station.rainfall ?? [];
  if (!points.length) return <p className="console-empty">Rainfall context unavailable from the current weather feed.</p>;
  const peak = Math.max(1, ...points.map((point) => point.precipitation_mm ?? 0));
  return <div className="river-rain-strip console-rain-bars" role="img"
    aria-label={`Daily rainfall: ${points.map((point) => `${compactDate(point.date)} ${numberLabel(point.precipitation_mm)} mm`).join(", ")}`}>
    {points.map((point, index) => {
      const mm = point.precipitation_mm ?? 0;
      return <div key={point.date} data-phase={point.phase === "past" ? "observed" : "forecast"} style={{ "--bar": `${Math.max(4, (mm / peak) * 100)}%`, "--bar-delay": `${320 + index * 35}ms` } as CSSProperties}
        title={`${compactDate(point.date)} · ${point.phase === "past" ? "Observed" : "Forecast"} · ${numberLabel(point.precipitation_mm)} mm${point.probability_percent == null ? "" : ` · ${numberLabel(point.probability_percent, 0)}% chance`}`}>
        <i />
        <small>{Number.isNaN(Date.parse(point.date)) ? "" : new Date(point.date).getUTCDate()}</small>
      </div>;
    })}
  </div>;
}

export function RiverStationInspector({ stationId, data, error, refreshing, onRefresh, onClose, onSelect, flowUnit = "cumecs" }: {
  stationId: string;
  data: RiverMonitoringResponse | null;
  error: string | null;
  refreshing: boolean;
  onRefresh: () => void;
  onClose: () => void;
  onSelect: (id: string) => void;
  flowUnit?: FlowUnit;
}) {
  const discharge = (value: number | null | undefined) => formatFlow(value, flowUnit);
  const [forecastOpen, setForecastOpen] = useState(false);
  const [sheet, setSheet] = useState<"about" | "stats" | null>(null);
  const [page, setPage] = useState(1);
  useEffect(() => { setForecastOpen(false); setSheet(null); setPage(1); }, [stationId]);
  const station = data?.stations.find((item) => item.id === stationId);
  const { bodyRef, gridRef, paged } = useFitToPanel(page, `${station?.id ?? ""}:${forecastOpen}`);
  const panelRef = useClearOfMapBars();
  // On a short panel the two pages take turns, pausing while the pointer or focus is on the panel.
  const engaged = useRef(false);
  useEffect(() => {
    if (!paged || forecastOpen || sheet || reducedMotion()) return;
    const timer = window.setInterval(() => { if (!engaged.current) setPage((current) => current === 1 ? 2 : 1); }, 5000);
    return () => window.clearInterval(timer);
  }, [paged, forecastOpen, sheet, page]);
  // The values shown for the previous station, so numbers count from them to this station's.
  const shownBefore = useRef<{ id: string | null; current: number | null; forecast: number | null; rain: number | null }>({ id: null, current: null, forecast: null, rain: null });
  const previous = shownBefore.current.id === stationId ? null : shownBefore.current;
  const maxRain = typeof station?.stats.max_forecast_rain_mm === "number" ? station.stats.max_forecast_rain_mm : null;
  useEffect(() => {
    if (station) shownBefore.current = { id: station.id, current: station.current_discharge_cumecs, forecast: station.forecast_discharge_cumecs, rain: maxRain };
  });
  const level = stationWaterLevel(station);
  const chains = Object.entries(data?.chains ?? {}).filter(([, ids]) => ids.includes(stationId));
  const floodSignals = station?.flood_types ?? [];
  const gaugeReadings = station?.gauge_readings ?? [];
  const providers = station?.providers ?? [];
  const metrics = Object.entries(station?.stats ?? {}).filter(([, value]) => value != null);
  const rainProbability = typeof station?.stats.max_rain_probability_percent === "number" ? station.stats.max_rain_probability_percent : null;
  const change = station?.change_24h_cumecs ?? null;
  const direction = change == null ? "unknown" : change > 0 ? "rising" : change < 0 ? "falling" : "steady";
  const TrendIcon = direction === "rising" ? ArrowUpRight : direction === "falling" ? ArrowDownRight : ArrowRight;
  const stationName = (id: string) => data?.stations.find((item) => item.id === id)?.name ?? id;

  const hasAbout = Boolean(station && (station.why_selected || station.facts.length > 0));
  const hasStats = metrics.length > 0 || providers.some((provider) => provider.note);

  return <><aside ref={panelRef} className="river-station-inspector station-console" aria-label="River station details" hidden={forecastOpen}
    onPointerEnter={() => { engaged.current = true; }} onPointerLeave={() => { engaged.current = false; }}
    onFocus={() => { engaged.current = true; }} onBlur={() => { engaged.current = false; }}>
    <header className="console-header">
      <div>
        <span className="console-eyebrow">River monitoring / {station?.id ?? stationId}</span>
        <h3 key={station?.id ?? stationId} className="station-title-ticket">{station?.name ?? stationId.replaceAll("_", " ")}</h3>
        {station && <p className="console-subtitle">{station.river} River · {station.basin || "Basin unavailable"} basin</p>}
      </div>
      <div className="console-header-side">
        {station && <span key={`status:${station.id}`} className="console-status" data-tone={categoryTone(station.flood_category)} title="Flood category · FFD observed status">{station.flood_category}</span>}
        <button type="button" className="console-refresh" title="Refresh river station data" aria-label="Refresh" onClick={onRefresh} disabled={refreshing}><RefreshCw size={15} className={refreshing ? "spinning" : ""} /></button>
        <button type="button" className="console-close" title="Close station details" aria-label="Close station details" onClick={onClose}><X size={18} /></button>
      </div>
    </header>
    <div className="station-details-tabs" role="tablist" aria-label="Station views">
      <button type="button" role="tab" id="station-details-tab" aria-selected="true" aria-controls="station-details-panel">Station details</button>
      <button type="button" role="tab" aria-selected="false" disabled={!station} onClick={() => setForecastOpen(true)}>Discharge forecast</button>
      <span className="console-stored">Stored {timestamp(data?.cached_at)} · updates every {data?.refresh_interval_minutes ?? 15} min</span>
    </div>
    <div id="station-details-panel" className="console-body" role="tabpanel" aria-labelledby="station-details-tab" ref={bodyRef}>
      {error && <p role="status" className="console-note">{error}</p>}
      {data?.refresh_error && <p role="status" className="console-note">{data.refresh_error}</p>}
      {!station ? <p className="console-empty">{refreshing ? "Fetching station readings" : "Station data is unavailable"}</p> : <div className="console-grid" key={station.id} ref={gridRef} data-page={paged ? page : undefined}>

        <section className="console-card console-hero" data-on-page="1" style={rise(0)} aria-label={`${station.name} current discharge and hydrograph`}>
          <div className="console-hero-reading">
            <span className="console-label"><Waves size={13} aria-hidden="true" />Current discharge <Live /></span>
            <strong className="console-value console-value-hero"><CountUp value={station.current_discharge_cumecs} from={previous?.current ?? null} format={discharge} /></strong>
            <span className="console-trend" data-direction={direction}>
              <TrendIcon size={14} aria-hidden="true" />
              {change == null ? "Unavailable" : `${change > 0 ? "+" : ""}${discharge(change)}`}<small>24h change</small>
            </span>
            <small className="console-time">{timestamp(station.observed_at ?? station.providers[0]?.series.filter((point) => point.phase === "past").slice(-1)[0]?.time)}</small>
            <RiverDataSource source={station.current_source} station={station} />
            <RiverDataSource source={station.change_source} station={station} />
          </div>
          <div className="console-hero-chart">
            <span className="console-label"><Activity size={13} aria-hidden="true" />Hydrograph</span>
            <ForecastChart providers={station.providers} />
            <RiverDataSource source="GloFAS via Open-Meteo" station={station} />
          </div>
        </section>

        <section className="console-card console-kpi" data-on-page="1" style={rise(1)}>
          <span className="console-label"><Gauge size={13} aria-hidden="true" />Water level</span>
          <strong className="console-value">{level.value}</strong>
          {level.recordedAt && <small className="console-time">{timestamp(level.recordedAt)}</small>}
          <RiverDataSource source={level.source} station={station} />
        </section>

        <section className="console-card console-kpi" data-on-page="1" style={rise(2)}>
          <span className="console-label"><TrendingUp size={13} aria-hidden="true" />Forecast discharge</span>
          <strong className="console-value"><CountUp value={station.forecast_discharge_cumecs} from={previous?.forecast ?? null} format={discharge} /></strong>
          <small className="console-time">{timestamp(station.forecast_valid_at)}</small>
          <span className="console-subline">Expected peak time · <b>{timestamp(station.expected_peak_at)}</b>{station.expected_peak_cumecs != null && <> · {discharge(station.expected_peak_cumecs)}</>}</span>
          {station.official_forecast_text && <span className="console-subline">FFD forecast · <b>{station.official_forecast_text}{/\d/.test(station.official_forecast_text) ? " thousand cusecs" : ""}</b></span>}
          <RiverDataSource source="GloFAS modeled" station={station} />
          {station.official_forecast_text && <RiverDataSource source="FFD official forecast" station={station} />}
        </section>

        <section className="console-card console-kpi console-rain" data-on-page="1" style={rise(3)}>
          <span className="console-label"><CloudRain size={13} aria-hidden="true" />Rainfall context</span>
          <strong className="console-value"><CountUp value={maxRain} from={previous?.rain ?? null} format={(value) => `${numberLabel(value)} mm`} /></strong>
          <span className="console-subline">Max forecast rain · <b>{numberLabel(rainProbability, 0)}%</b> chance</span>
          <RainBars station={station} />
          <RiverDataSource source="Open-Meteo model precipitation" station={station} />
        </section>

        <section className="console-card console-list" data-on-page="2" style={rise(4)}>
          <h4 className="console-label">Flood risk signals</h4>
          {floodSignals.length ? <ul>{floodSignals.map((signal, index) => (
            <li key={`${station.id}:risk:${signal.type}`} style={{ "--row-delay": `${360 + index * 60}ms`, "--meter": `${Math.max(0, Math.min(100, signal.probability ?? 0))}%` } as CSSProperties} title={signal.basis}>
              <i className="console-dot" data-tone={severityTone[signal.severity] ?? "neutral"} aria-hidden="true" />
              <span><strong>{signal.type}</strong><small>{numberLabel(signal.probability, 0)}% probability · {signal.lead_time}</small></span>
              <b data-tone={severityTone[signal.severity] ?? "neutral"}>{signal.severity}</b>
              <em className="console-meter" data-tone={severityTone[signal.severity] ?? "neutral"} aria-hidden="true" />
            </li>
          ))}</ul> : <p className="console-empty">Flood-type signals unavailable.</p>}
        </section>

        <section className="console-card console-list" data-on-page="2" style={rise(5)}>
          <h4 className="console-label">Gauges &amp; models</h4>
          <ul>
            {gaugeReadings.map((reading, index) => (
              <li key={`${station.id}:gauge:${reading.gauge}`} style={{ "--row-delay": `${380 + index * 60}ms` } as CSSProperties} title={`${timestamp(reading.time)} · ${reading.source}`}>
                <i className="console-dot" data-tone="calm" aria-hidden="true" />
                <span><strong>{reading.gauge} gauge</strong><small>{timestamp(reading.time)}</small></span>
                <b>{discharge(reading.value)}</b>
              </li>
            ))}
            {providers.map((provider, index) => (
              <li key={`${station.id}:provider:${provider.provider}`} style={{ "--row-delay": `${380 + (gaugeReadings.length + index) * 60}ms` } as CSSProperties} title={provider.note ?? provider.source}>
                <i className="console-dot" data-tone={providerTone(provider.status)} aria-hidden="true" />
                <span><strong>{provider.provider}</strong><small>Peak {discharge(provider.peak_forecast_cumecs)} · {timestamp(provider.peak_forecast_time)}</small></span>
                <b data-tone={providerTone(provider.status)}>{provider.status}</b>
              </li>
            ))}
          </ul>
          {gaugeReadings.length > 0 && <RiverDataSource source="FFD official gauges" station={station} />}
        </section>

        <section className="console-card console-station" data-on-page="2" style={rise(6)}>
          <dl className="console-facts">
            <div><dt>Coordinates</dt><dd>{station.latitude.toFixed(4)}, {station.longitude.toFixed(4)}</dd></div>
            <div><dt>Monitoring focus</dt><dd>{station.source_focus || "River gauge"}</dd></div>
          </dl>
          <div className="console-network">
            <span className="console-label"><RadioTower size={13} aria-hidden="true" />Upstream stations</span>
            {station.upstream_station_ids.length
              ? <div className="river-upstream-stations">{station.upstream_station_ids.map((id) => <button type="button" key={id} onClick={() => onSelect(id)}>{stationName(id)}</button>)}</div>
              : <p className="console-empty">First monitored station in this corridor</p>}
            {chains.map(([river, ids]) => <details className="river-station-chain console-chain" key={river}>
              <summary>{river} river chain · {ids.length} stations <ChevronDown size={13} aria-hidden="true" /></summary>
              <ol>{ids.map((id) => <li key={id}><button type="button" aria-current={id === stationId ? "true" : undefined} onClick={() => onSelect(id)}>{stationName(id)}</button></li>)}</ol>
            </details>)}
          </div>
          {(hasAbout || hasStats) && <div className="console-actions">
            {hasAbout && <button type="button" onClick={() => setSheet("about")}><Info size={13} aria-hidden="true" />Why this station is monitored</button>}
            {hasStats && <button type="button" onClick={() => setSheet("stats")}><ChartColumn size={13} aria-hidden="true" />All model statistics · {metrics.length}</button>}
          </div>}
        </section>
      </div>}
    </div>
    {paged && station && <div className="console-pager" role="group" aria-label="Station detail pages">
      <button type="button" aria-pressed={page === 1} onClick={() => setPage(1)}>Live readings</button>
      <button type="button" aria-pressed={page === 2} onClick={() => setPage(2)}>Signals &amp; network</button>
    </div>}
    {sheet && station && <section className="console-sheet" role="dialog" aria-label={sheet === "about" ? "Why this station is monitored" : "All model statistics"}
      onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); setSheet(null); } }}>
      <div className="console-sheet-head">
        <span className="console-label">{sheet === "about" ? <><Info size={13} aria-hidden="true" />Why this station is monitored</> : <><ChartColumn size={13} aria-hidden="true" />All model statistics · {metrics.length}</>}</span>
        <button type="button" autoFocus title="Back to station cards" aria-label="Back to station cards" onClick={() => setSheet(null)}><X size={16} /></button>
      </div>
      <div className="console-sheet-body">
        {sheet === "about" ? <div className="console-about">
          {station.why_selected && <p>{station.why_selected}</p>}
          {station.facts.length > 0 && <ul>{station.facts.map((fact, index) => <li key={`${station.id}:${index}`}>{fact}</li>)}</ul>}
        </div> : <>
          <dl className="console-metrics">{metrics.map(([key, value], index) => <div key={`${station.id}:metric:${key}`} data-metric-key={key} style={{ "--row-delay": `${60 + index * 18}ms` } as CSSProperties}>
            <dt>{metricLabel(key)}</dt><dd>{metricValue(key, value, flowUnit)}</dd>
          </div>)}</dl>
          {providers.filter((provider) => provider.note).map((provider) => <p key={`${station.id}:note:${provider.provider}`} className="console-model-note"><b>{provider.provider}</b> {provider.note}</p>)}
          <p className="console-model-note">Hydrograph and peak: GloFAS modeled discharge. Flood category: FFD observed status.</p>
        </>}
      </div>
    </section>}
  </aside>{forecastOpen && station && <Suspense fallback={<p role="status">Loading station forecast...</p>}><StationForecastWindow key={station.id} station={station} intervalMinutes={data?.refresh_interval_minutes ?? 15} flowUnit={flowUnit} onDetails={() => setForecastOpen(false)} onClose={onClose} /></Suspense>}</>;
}
