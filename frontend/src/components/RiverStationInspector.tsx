import { ArrowDownRight, ArrowRight, ArrowUpRight, ChevronDown, CloudRain, RefreshCw, X } from "lucide-react";
import { lazy, Suspense, useEffect, useRef, useState, type CSSProperties } from "react";

import type { RiverMonitoringStation, RiverMonitoringResponse } from "../types/api";
import { ForecastChart } from "./SourceFloodForecastTab";
import { formatFlow, type FlowUnit } from "./waterQuantities";
import { RiverDataSource } from "./RiverDataSource";
import { stationWaterLevel } from "./stationInfo";
import "../station-console.css";
const StationForecastWindow = lazy(() => import("./StationForecastWindow"));

// The station panel as a monitoring console: one hero reading with its
// hydrograph, three reading cards, compact status lists and a station card.
// Rarely needed detail (every model statistic, full model notes) sits in a
// collapsed drawer. Cards rise into place in sequence when a station opens.

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
  useEffect(() => setForecastOpen(false), [stationId]);
  const station = data?.stations.find((item) => item.id === stationId);
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

  return <><aside className="river-station-inspector station-console" aria-label="River station details" hidden={forecastOpen}>
    <header className="console-header">
      <div>
        <span className="console-eyebrow">River monitoring / {station?.id ?? stationId}</span>
        <h3 key={station?.id ?? stationId} className="station-title-ticket">{station?.name ?? stationId.replaceAll("_", " ")}</h3>
        {station && <p className="console-subtitle">{station.river} River · {station.basin || "Basin unavailable"} basin</p>}
      </div>
      <div className="console-header-side">
        {station && <span key={`status:${station.id}`} className="console-status" data-tone={categoryTone(station.flood_category)} title="Flood category · FFD observed status">{station.flood_category}</span>}
        <button type="button" className="console-close" title="Close station details" aria-label="Close station details" onClick={onClose}><X size={18} /></button>
      </div>
    </header>
    <div className="station-details-tabs" role="tablist" aria-label="Station views">
      <button type="button" role="tab" id="station-details-tab" aria-selected="true" aria-controls="station-details-panel">Station details</button>
      <button type="button" role="tab" aria-selected="false" disabled={!station} onClick={() => setForecastOpen(true)}>Discharge forecast</button>
    </div>
    <div id="station-details-panel" className="console-scroll" role="tabpanel" aria-labelledby="station-details-tab">
      {error && <p role="status" className="console-note">{error}</p>}
      {data?.refresh_error && <p role="status" className="console-note">{data.refresh_error}</p>}
      {!station ? <p className="console-empty">{refreshing ? "Fetching station readings" : "Station data is unavailable"}</p> : <div className="console-grid" key={station.id}>

        <section className="console-card console-hero" style={rise(0)} aria-label={`${station.name} current discharge and hydrograph`}>
          <div className="console-hero-reading">
            <span className="console-label">Current discharge <Live /></span>
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
            <span className="console-label">Hydrograph</span>
            <ForecastChart providers={station.providers} />
            <RiverDataSource source="GloFAS via Open-Meteo" station={station} />
          </div>
        </section>

        <section className="console-card console-kpi" style={rise(1)}>
          <span className="console-label">Water level</span>
          <strong className="console-value">{level.value}</strong>
          {level.recordedAt && <small className="console-time">{timestamp(level.recordedAt)}</small>}
          <RiverDataSource source={level.source} station={station} />
        </section>

        <section className="console-card console-kpi" style={rise(2)}>
          <span className="console-label">Forecast discharge</span>
          <strong className="console-value"><CountUp value={station.forecast_discharge_cumecs} from={previous?.forecast ?? null} format={discharge} /></strong>
          <small className="console-time">{timestamp(station.forecast_valid_at)}</small>
          <span className="console-subline">Expected peak time · <b>{timestamp(station.expected_peak_at)}</b>{station.expected_peak_cumecs != null && <> · {discharge(station.expected_peak_cumecs)}</>}</span>
          {station.official_forecast_text && <span className="console-subline">FFD forecast · <b>{station.official_forecast_text}{/\d/.test(station.official_forecast_text) ? " thousand cusecs" : ""}</b></span>}
          <RiverDataSource source="GloFAS modeled" station={station} />
          {station.official_forecast_text && <RiverDataSource source="FFD official forecast" station={station} />}
        </section>

        <section className="console-card console-kpi console-rain" style={rise(3)}>
          <span className="console-label"><CloudRain size={13} aria-hidden="true" />Rainfall context</span>
          <strong className="console-value"><CountUp value={maxRain} from={previous?.rain ?? null} format={(value) => `${numberLabel(value)} mm`} /></strong>
          <span className="console-subline">Max forecast rain · <b>{numberLabel(rainProbability, 0)}%</b> chance</span>
          <RainBars station={station} />
          <RiverDataSource source="Open-Meteo model precipitation" station={station} />
        </section>

        <section className="console-card console-list" style={rise(4)}>
          <h4 className="console-label">Flood risk signals</h4>
          {floodSignals.length ? <ul>{floodSignals.map((signal, index) => (
            <li key={`${station.id}:risk:${signal.type}`} style={{ "--row-delay": `${360 + index * 60}ms` } as CSSProperties} title={signal.basis}>
              <i className="console-dot" data-tone={severityTone[signal.severity] ?? "neutral"} aria-hidden="true" />
              <span><strong>{signal.type}</strong><small>{numberLabel(signal.probability, 0)}% probability · {signal.lead_time}</small></span>
              <b data-tone={severityTone[signal.severity] ?? "neutral"}>{signal.severity}</b>
            </li>
          ))}</ul> : <p className="console-empty">Flood-type signals unavailable.</p>}
        </section>

        <section className="console-card console-list" style={rise(5)}>
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

        <section className="console-card console-station" style={rise(6)}>
          <h4 className="console-label">Station</h4>
          <dl className="console-facts">
            <div><dt>Station ID</dt><dd>{station.id}</dd></div>
            <div><dt>Coordinates</dt><dd>{station.latitude.toFixed(4)}, {station.longitude.toFixed(4)}</dd></div>
            <div><dt>Monitoring focus</dt><dd>{station.source_focus || "River gauge"}</dd></div>
          </dl>
          <div className="console-network">
            <span className="console-label">Upstream stations</span>
            {station.upstream_station_ids.length
              ? <div className="river-upstream-stations">{station.upstream_station_ids.map((id) => <button type="button" key={id} onClick={() => onSelect(id)}>{stationName(id)}</button>)}</div>
              : <p className="console-empty">First monitored station in this corridor</p>}
            {chains.map(([river, ids]) => <details className="river-station-chain console-chain" key={river}>
              <summary>{river} river chain · {ids.length} stations <ChevronDown size={13} aria-hidden="true" /></summary>
              <ol>{ids.map((id) => <li key={id}><button type="button" aria-current={id === stationId ? "true" : undefined} onClick={() => onSelect(id)}>{stationName(id)}</button></li>)}</ol>
            </details>)}
          </div>
          {(station.why_selected || station.facts.length > 0) && <details className="console-about">
            <summary>Why this station is monitored <ChevronDown size={13} aria-hidden="true" /></summary>
            {station.why_selected && <p>{station.why_selected}</p>}
            {station.facts.length > 0 && <ul>{station.facts.map((fact, index) => <li key={`${station.id}:${index}`}>{fact}</li>)}</ul>}
          </details>}
        </section>

        {(metrics.length > 0 || providers.some((provider) => provider.note)) && <details className="console-card console-more" style={rise(7)}>
          <summary><span className="console-label">All model statistics · {metrics.length}</span><ChevronDown size={14} aria-hidden="true" /></summary>
          <dl className="console-metrics">{metrics.map(([key, value]) => <div key={`${station.id}:metric:${key}`} data-metric-key={key}>
            <dt>{metricLabel(key)}</dt><dd>{metricValue(key, value, flowUnit)}</dd>
          </div>)}</dl>
          {providers.filter((provider) => provider.note).map((provider) => <p key={`${station.id}:note:${provider.provider}`} className="console-model-note"><b>{provider.provider}</b> {provider.note}</p>)}
          <p className="console-model-note">Hydrograph and peak: GloFAS modeled discharge. Flood category: FFD observed status.</p>
        </details>}
      </div>}
    </div>
    <footer className="console-footer"><span>Stored {timestamp(data?.cached_at)} · updates every {data?.refresh_interval_minutes ?? 15} min</span><button type="button" onClick={onRefresh} disabled={refreshing} title="Refresh river station data"><RefreshCw size={15} className={refreshing ? "spinning" : ""} />{refreshing ? "Refreshing" : "Refresh"}</button></footer>
  </aside>{forecastOpen && station && <Suspense fallback={<p role="status">Loading station forecast...</p>}><StationForecastWindow key={station.id} station={station} intervalMinutes={data?.refresh_interval_minutes ?? 15} flowUnit={flowUnit} onDetails={() => setForecastOpen(false)} onClose={onClose} /></Suspense>}</>;
}
