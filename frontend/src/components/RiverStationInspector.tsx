import { CloudRain, RefreshCw, X } from "lucide-react";
import { lazy, Suspense, useEffect, useState, type CSSProperties } from "react";

import type { RiverMonitoringResponse } from "../types/api";
import { ForecastChart } from "./SourceFloodForecastTab";
import { formatFlow, type FlowUnit } from "./waterQuantities";
import { RiverDataSource } from "./RiverDataSource";
import { stationWaterLevel } from "./stationInfo";
const StationForecastWindow = lazy(() => import("./StationForecastWindow"));

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

function ticketMotion(order: number): CSSProperties {
  return { "--ticket-delay": `${order * 170}ms` } as CSSProperties;
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
  const level = stationWaterLevel(station);
  const chains = Object.entries(data?.chains ?? {}).filter(([, ids]) => ids.includes(stationId));
  const rainfallForecast = (station?.rainfall ?? []).filter((point) => point.phase === "forecast");
  const maxRain = typeof station?.stats.max_forecast_rain_mm === "number" ? station.stats.max_forecast_rain_mm : null;
  const rainProbability = typeof station?.stats.max_rain_probability_percent === "number" ? station.stats.max_rain_probability_percent : null;
  return <><aside className="river-station-inspector" aria-label="River station details" hidden={forecastOpen}>
    <header><div><span>River monitoring / {station?.id ?? stationId}</span><h3 key={station?.id ?? stationId} className="station-title-ticket">{station?.name ?? stationId.replaceAll("_", " ")}</h3></div><button type="button" title="Close station details" aria-label="Close station details" onClick={onClose}><X size={18} /></button></header>
    <div className="station-details-tabs" role="tablist" aria-label="Station views">
      <button type="button" role="tab" id="station-details-tab" aria-selected="true" aria-controls="station-details-panel">Station details</button>
      <button type="button" role="tab" aria-selected="false" disabled={!station} onClick={() => setForecastOpen(true)}>Discharge forecast</button>
    </div>
    <div id="station-details-panel" role="tabpanel" aria-labelledby="station-details-tab">
    {error && <p role="status">{error}</p>}
    {data?.refresh_error && <p role="status">{data.refresh_error}</p>}
    {!station ? <p>{refreshing ? "Fetching station readings" : "Station data is unavailable"}</p> : <div className="station-panel-grid">
      <section className="station-identity-group" aria-label="Station identity">
        <div className="river-station-category station-ticket" key={`category:${station.id}`} style={ticketMotion(0)}><span>{station.river} River</span><div><small>Flood category</small><strong>{station.flood_category}</strong><RiverDataSource source="FFD observed status" station={station} /></div></div>
        <dl className="station-identity-tickets" key={`identity:${station.id}`} aria-label={`${station.name} station information`}>
          <div className="station-ticket" style={ticketMotion(1)}><dt>Station ID</dt><dd>{station.id}</dd></div>
          <div className="station-ticket" style={ticketMotion(2)}><dt>Basin</dt><dd>{station.basin || "Unavailable"}</dd></div>
          <div className="station-ticket" style={ticketMotion(3)}><dt>Coordinates</dt><dd>{station.latitude.toFixed(4)}, {station.longitude.toFixed(4)}</dd></div>
          <div className="station-ticket" style={ticketMotion(4)}><dt>Monitoring focus</dt><dd>{station.source_focus || "River gauge"}</dd></div>
        </dl>
        {station.why_selected && <div className="station-context-ticket station-ticket" key={`context:${station.id}`} style={ticketMotion(5)}><span>Why this station is monitored</span><p>{station.why_selected}</p></div>}
        {station.facts.length > 0 && <details className="station-facts-ticket station-ticket" key={`facts:${station.id}`} style={ticketMotion(6)}><summary>Station context / {station.facts.length} details</summary><ul>{station.facts.map((fact, index) => <li key={`${station.id}:${index}`}>{fact}</li>)}</ul></details>}
      </section>
      <section className="station-reading-group" aria-label="Station readings">
        <dl className="river-station-stats station-reading-tickets" key={`readings:${station.id}`} aria-label={`${station.name} live readings`}>
          <div className="station-ticket" style={ticketMotion(7)}><dt>Current discharge</dt><dd>{discharge(station.current_discharge_cumecs)}</dd><RiverDataSource source={station.current_source} station={station} /><small>{timestamp(station.observed_at ?? station.providers[0]?.series.filter((point) => point.phase === "past").slice(-1)[0]?.time)}</small></div>
          <div className="station-ticket" style={ticketMotion(8)}><dt>Water level</dt><dd>{level.value}</dd><RiverDataSource source={level.source} station={station} />{level.recordedAt && <small>{timestamp(level.recordedAt)}</small>}</div>
          <div className="station-ticket" style={ticketMotion(9)}><dt>Forecast discharge</dt><dd>{discharge(station.forecast_discharge_cumecs)}</dd><RiverDataSource source="GloFAS modeled" station={station} /><small>{timestamp(station.forecast_valid_at)}</small></div>
          <div className="station-ticket" style={ticketMotion(10)}><dt>24h change</dt><dd>{station.change_24h_cumecs != null && station.change_24h_cumecs > 0 ? "+" : ""}{discharge(station.change_24h_cumecs)}</dd><RiverDataSource source={station.change_source} station={station} /></div>
          <div className="station-ticket" style={ticketMotion(11)}><dt>Expected peak time</dt><dd>{timestamp(station.expected_peak_at)}</dd><RiverDataSource source="GloFAS modeled peak" station={station} /><small>{discharge(station.expected_peak_cumecs)}</small></div>
        </dl>
        {station.official_forecast_text && <div className="station-official-forecast station-ticket" key={`official:${station.id}`} style={ticketMotion(12)}><strong>FFD forecast</strong><span>{station.official_forecast_text}{/\d/.test(station.official_forecast_text) ? " thousand cusecs" : ""}</span><RiverDataSource source="FFD official forecast" station={station} /></div>}
      </section>
      <section className="station-hydrograph-group" key={`hydrograph:${station.id}`} aria-label="Station hydrograph">
        <h4>Hydrograph</h4>
        <ForecastChart providers={station.providers} />
        <RiverDataSource source="GloFAS via Open-Meteo" station={station} />
      </section>
      <section className="station-rainfall-group" aria-label="Station rainfall context">
        <h4 className="river-rainfall-heading"><CloudRain size={15} />Rainfall context</h4>
        <dl className="river-station-stats river-rainfall-summary" key={`rain-summary:${station.id}`}>
          <div className="station-ticket" style={ticketMotion(13)}><dt>Max forecast rain</dt><dd>{numberLabel(maxRain)} mm</dd><RiverDataSource source="Open-Meteo model precipitation" station={station} /></div>
          <div className="station-ticket" style={ticketMotion(14)}><dt>Max rain probability</dt><dd>{numberLabel(rainProbability, 0)}%</dd><RiverDataSource source="Open-Meteo model precipitation" station={station} /></div>
        </dl>
        {rainfallForecast.length ? <div className="source-rain-strip river-rain-strip" key={`rain-strip:${station.id}`}>
          {rainfallForecast.map((point, index) => (
            <div className="station-ticket" key={point.date} style={ticketMotion(15 + index)}>
              <span>{compactDate(point.date)}</span>
              <strong>{numberLabel(point.precipitation_mm)} mm</strong>
              <small>{numberLabel(point.probability_percent, 0)}%</small>
            </div>
          ))}
        </div> : <p>Rainfall context unavailable from the current weather feed.</p>}
      </section>
      <section className="station-network-group" aria-label="Station river network">
        <div><h4>Upstream stations</h4>{station.upstream_station_ids.length ? <div className="river-upstream-stations">{station.upstream_station_ids.map((id) => <button type="button" key={id} onClick={() => onSelect(id)}>{data?.stations.find((item) => item.id === id)?.name ?? id}</button>)}</div> : <p>First monitored station in this corridor</p>}</div>
        {chains.map(([river, ids]) => <details className="station-chain-details" key={river}><summary>{river} river chain / {ids.length} stations</summary><ol>{ids.map((id) => <li key={id}><button type="button" aria-current={id === stationId ? "true" : undefined} onClick={() => onSelect(id)}>{data?.stations.find((item) => item.id === id)?.name ?? id}</button></li>)}</ol></details>)}
        <p className="station-method-note">Hydrograph and peak: GloFAS modeled discharge. Flood category: FFD observed status.</p>
      </section>
    </div>}
    </div><footer><span>Stored {timestamp(data?.cached_at)}<br />Updates every {data?.refresh_interval_minutes ?? 15} min</span><button type="button" onClick={onRefresh} disabled={refreshing} title="Refresh river station data"><RefreshCw size={15} className={refreshing ? "spinning" : ""} />{refreshing ? "Refreshing" : "Refresh"}</button></footer>
  </aside>{forecastOpen && station && <Suspense fallback={<p role="status">Loading station forecast...</p>}><StationForecastWindow key={station.id} station={station} intervalMinutes={data?.refresh_interval_minutes ?? 15} flowUnit={flowUnit} onDetails={() => setForecastOpen(false)} onClose={onClose} /></Suspense>}</>;
}
