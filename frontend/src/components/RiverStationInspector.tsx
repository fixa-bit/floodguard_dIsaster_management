import { RefreshCw, X } from "lucide-react";

import type { RiverMonitoringResponse } from "../types/api";
import { ForecastChart } from "./SourceFloodForecastTab";

function discharge(value: number | null | undefined) {
  return value == null ? "Unavailable" : `${value.toLocaleString("en", { maximumFractionDigits: Math.abs(value) < 1 ? 3 : 1 })} m3/s`;
}

function timestamp(value: string | null | undefined) {
  if (!value) return "Unavailable";
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return `${new Intl.DateTimeFormat("en-PK", { month: "short", day: "numeric", timeZone: "UTC" }).format(new Date(value))} (daily forecast)`;
  return `${new Intl.DateTimeFormat("en-PK", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: "Asia/Karachi" }).format(new Date(value))} PKT`;
}

export function RiverStationInspector({ stationId, data, error, refreshing, onRefresh, onClose, onSelect }: {
  stationId: string;
  data: RiverMonitoringResponse | null;
  error: string | null;
  refreshing: boolean;
  onRefresh: () => void;
  onClose: () => void;
  onSelect: (id: string) => void;
}) {
  const station = data?.stations.find((item) => item.id === stationId);
  const chains = Object.entries(data?.chains ?? {}).filter(([, ids]) => ids.includes(stationId));
  return <aside className="river-station-inspector" aria-label="River station details">
    <header><div><span>River monitoring</span><h3>{station?.name ?? stationId.replaceAll("_", " ")}</h3></div><button type="button" title="Close station details" aria-label="Close station details" onClick={onClose}><X size={18} /></button></header>
    {error && <p role="status">{error}</p>}
    {data?.refresh_error && <p role="status">{data.refresh_error}</p>}
    {!station ? <p>{refreshing ? "Fetching station readings" : "Station data is unavailable"}</p> : <>
      <div className="river-station-category"><span>{station.river} River</span><div><small>Flood category</small><strong>{station.flood_category}</strong></div></div>
      <dl className="river-station-stats">
        <div><dt>Current discharge</dt><dd>{discharge(station.current_discharge_cumecs)}</dd><small>{station.current_source} / {timestamp(station.observed_at ?? station.providers[0]?.series.filter((point) => point.phase === "past").slice(-1)[0]?.time)}</small></div>
        <div><dt>Forecast discharge</dt><dd>{discharge(station.forecast_discharge_cumecs)}</dd><small>GloFAS / {timestamp(station.forecast_valid_at)}</small></div>
        <div><dt>24h change</dt><dd>{station.change_24h_cumecs != null && station.change_24h_cumecs > 0 ? "+" : ""}{discharge(station.change_24h_cumecs)}</dd><small>{station.change_source}</small></div>
        <div><dt>Expected peak time</dt><dd>{timestamp(station.expected_peak_at)}</dd><small>GloFAS modeled peak / {discharge(station.expected_peak_cumecs)}</small></div>
      </dl>
      {station.official_forecast_text && <p>FFD forecast: {station.official_forecast_text}{/\d/.test(station.official_forecast_text) ? " thousand cusecs" : ""}</p>}
      <h4>Hydrograph</h4>
      <ForecastChart providers={station.providers} />
      <h4>Upstream stations</h4>
      {station.upstream_station_ids.length ? <div className="river-upstream-stations">{station.upstream_station_ids.map((id) => <button type="button" key={id} onClick={() => onSelect(id)}>{data?.stations.find((item) => item.id === id)?.name ?? id}</button>)}</div> : <p>First monitored station in this corridor</p>}
      {chains.map(([river, ids]) => <div className="river-station-chain" key={river}><strong>{river}</strong><ol>{ids.map((id) => <li key={id}><button type="button" aria-current={id === stationId ? "true" : undefined} onClick={() => onSelect(id)}>{data?.stations.find((item) => item.id === id)?.name ?? id}</button></li>)}</ol></div>)}
      <p>Hydrograph and peak: GloFAS modeled discharge. Flood category: FFD observed status.</p>
    </>}
    <footer><span>Stored {timestamp(data?.cached_at)}<br />Updates every {data?.refresh_interval_minutes ?? 15} min</span><button type="button" onClick={onRefresh} disabled={refreshing} title="Refresh river station data"><RefreshCw size={15} className={refreshing ? "spinning" : ""} />{refreshing ? "Refreshing" : "Refresh"}</button></footer>
  </aside>;
}
