// Station details panel opened when a station is clicked: the panel as it was on 23 Oct
// (plain side panel, no tickets). The monitoring tour keeps its own console: RiverStationInspector.
import { CloudRain, RefreshCw, X } from "lucide-react";
import { lazy, Suspense, useEffect, useLayoutEffect, useRef, useState } from "react";

import type { RiverMonitoringResponse } from "../types/api";
import { ForecastChart } from "./SourceFloodForecastTab";
import { formatFlow, type FlowUnit } from "./waterQuantities";
import { RiverDataSource } from "./RiverDataSource";
import { stationWaterLevel } from "./stationInfo";
import "../station-details-classic.css";
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

/** Floats the card over the map's right side: below the top stats bar, above the legend and ticker. */
function useCardPlacement() {
  const panelRef = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    const panel = panelRef.current;
    const host = panel?.offsetParent as HTMLElement | null;
    if (!panel || !host) return;
    const find = (selector: string) => document.querySelector<HTMLElement>(selector);
    const place = () => {
      // Narrow screens and the River Monitoring table show the panel in the page flow.
      if (getComputedStyle(panel).position !== "absolute") { panel.style.removeProperty("top"); panel.style.removeProperty("bottom"); return; }
      const box = host.getBoundingClientRect();
      // Screen boxes include the page zoom (the portal zooms <html> on some widths); CSS values do not.
      const zoom = host.offsetWidth > 0 ? box.width / host.offsetWidth : 1;
      const right = box.right - 16 * zoom, left = right - panel.offsetWidth * zoom;
      const crosses = (rect: DOMRect | undefined): rect is DOMRect => Boolean(rect && rect.width > 0 && rect.right > left && rect.left < right);
      const deck = find(".command-stats-deck")?.getBoundingClientRect();
      // An opened stats tab can grow the bar a lot; the card never gives up more than 40% of the height to it.
      const top = crosses(deck) ? Math.min(deck.bottom - box.top + 10 * zoom, box.height * 0.4) : 12 * zoom;
      const below = [find(".hourly-analytics-ticker")?.getBoundingClientRect(), find(".map-legend")?.getBoundingClientRect()]
        .filter((rect): rect is DOMRect => crosses(rect) && rect.top > box.top + box.height / 2);
      const bottom = below.length ? box.bottom - Math.min(...below.map((rect) => rect.top)) + 10 * zoom : 12 * zoom;
      panel.style.top = `${Math.round(Math.max(12, top / zoom))}px`;
      panel.style.bottom = `${Math.round(Math.max(12, bottom / zoom))}px`;
    };
    place();
    const observer = new ResizeObserver(place);
    for (const element of [host, find(".command-stats-deck"), find(".map-legend"), find(".hourly-analytics-ticker")]) if (element) observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return panelRef;
}

export function StationDetailsPanel({ stationId, data, error, refreshing, onRefresh, onClose, onSelect, flowUnit = "cumecs" }: {
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
  const panelRef = useCardPlacement();
  const station = data?.stations.find((item) => item.id === stationId);
  const level = stationWaterLevel(station);
  const chains = Object.entries(data?.chains ?? {}).filter(([, ids]) => ids.includes(stationId));
  const rainfallForecast = (station?.rainfall ?? []).filter((point) => point.phase === "forecast");
  const maxRain = typeof station?.stats.max_forecast_rain_mm === "number" ? station.stats.max_forecast_rain_mm : null;
  const rainProbability = typeof station?.stats.max_rain_probability_percent === "number" ? station.stats.max_rain_probability_percent : null;
  return <><aside ref={panelRef} className="river-station-inspector station-details-classic" aria-label="River station details" hidden={forecastOpen}>
    <header><div><span>River monitoring</span><h3>{station?.name ?? stationId.replaceAll("_", " ")}</h3></div><button type="button" title="Close station details" aria-label="Close station details" onClick={onClose}><X size={18} /></button></header>
    <div className="station-details-tabs" role="tablist" aria-label="Station views">
      <button type="button" role="tab" id="station-details-tab" aria-selected="true" aria-controls="station-details-panel">Station details</button>
      <button type="button" role="tab" aria-selected="false" disabled={!station} onClick={() => setForecastOpen(true)}>Discharge forecast</button>
    </div>
    <div id="station-details-panel" role="tabpanel" aria-labelledby="station-details-tab">
    {error && <p role="status">{error}</p>}
    {data?.refresh_error && <p role="status">{data.refresh_error}</p>}
    {!station ? <p>{refreshing ? "Fetching station readings" : "Station data is unavailable"}</p> : <>
      <div className="river-station-category"><span>{station.river} River</span><div><small>Flood category</small><strong>{station.flood_category}</strong><RiverDataSource source="FFD observed status" station={station} /></div></div>
      <dl className="river-station-stats">
        <div><dt>Current discharge</dt><dd>{discharge(station.current_discharge_cumecs)}</dd><RiverDataSource source={station.current_source} station={station} /><small>{timestamp(station.observed_at ?? station.providers[0]?.series.filter((point) => point.phase === "past").slice(-1)[0]?.time)}</small></div>
        <div><dt>Water level</dt><dd>{level.value}</dd><RiverDataSource source={level.source} station={station} />{level.recordedAt && <small>{timestamp(level.recordedAt)}</small>}</div>
        <div><dt>Forecast discharge</dt><dd>{discharge(station.forecast_discharge_cumecs)}</dd><RiverDataSource source="GloFAS modeled" station={station} /><small>{timestamp(station.forecast_valid_at)}</small></div>
        <div><dt>24h change</dt><dd>{station.change_24h_cumecs != null && station.change_24h_cumecs > 0 ? "+" : ""}{discharge(station.change_24h_cumecs)}</dd><RiverDataSource source={station.change_source} station={station} /></div>
        <div><dt>Expected peak time</dt><dd>{timestamp(station.expected_peak_at)}</dd><RiverDataSource source="GloFAS modeled peak" station={station} /><small>{discharge(station.expected_peak_cumecs)}</small></div>
      </dl>
      {station.official_forecast_text && <div><p>FFD forecast: {station.official_forecast_text}{/\d/.test(station.official_forecast_text) ? " thousand cusecs" : ""}</p><RiverDataSource source="FFD official forecast" station={station} /></div>}
      <h4>Hydrograph</h4>
      <ForecastChart providers={station.providers} />
      <RiverDataSource source="GloFAS via Open-Meteo" station={station} />
      <h4 className="river-rainfall-heading"><CloudRain size={15} />Rainfall context</h4>
      <dl className="river-station-stats river-rainfall-summary">
        <div><dt>Max forecast rain</dt><dd>{numberLabel(maxRain)} mm</dd><RiverDataSource source="Open-Meteo model precipitation" station={station} /></div>
        <div><dt>Max rain probability</dt><dd>{numberLabel(rainProbability, 0)}%</dd><RiverDataSource source="Open-Meteo model precipitation" station={station} /></div>
      </dl>
      {rainfallForecast.length ? <div className="source-rain-strip river-rain-strip">
        {rainfallForecast.map((point) => (
          <div key={point.date}>
            <span>{compactDate(point.date)}</span>
            <strong>{numberLabel(point.precipitation_mm)} mm</strong>
            <small>{numberLabel(point.probability_percent, 0)}%</small>
          </div>
        ))}
      </div> : <p>Rainfall context unavailable from the current weather feed.</p>}
      <h4>Upstream stations</h4>
      {station.upstream_station_ids.length ? <div className="river-upstream-stations">{station.upstream_station_ids.map((id) => <button type="button" key={id} onClick={() => onSelect(id)}>{data?.stations.find((item) => item.id === id)?.name ?? id}</button>)}</div> : <p>First monitored station in this corridor</p>}
      {chains.map(([river, ids]) => <div className="river-station-chain" key={river}><strong>{river}</strong><ol>{ids.map((id) => <li key={id}><button type="button" aria-current={id === stationId ? "true" : undefined} onClick={() => onSelect(id)}>{data?.stations.find((item) => item.id === id)?.name ?? id}</button></li>)}</ol></div>)}
      <p>Hydrograph and peak: GloFAS modeled discharge. Flood category: FFD observed status.</p>
    </>}
    </div><footer><span>Stored {timestamp(data?.cached_at)}<br />Updates every {data?.refresh_interval_minutes ?? 15} min</span><button type="button" onClick={onRefresh} disabled={refreshing} title="Refresh river station data"><RefreshCw size={15} className={refreshing ? "spinning" : ""} />{refreshing ? "Refreshing" : "Refresh"}</button></footer>
  </aside>{forecastOpen && station && <Suspense fallback={<p role="status">Loading station forecast...</p>}><StationForecastWindow key={station.id} station={station} intervalMinutes={data?.refresh_interval_minutes ?? 15} flowUnit={flowUnit} onDetails={() => setForecastOpen(false)} onClose={onClose} /></Suspense>}</>;
}
