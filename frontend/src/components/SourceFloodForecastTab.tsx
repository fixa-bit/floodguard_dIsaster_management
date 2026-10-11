import { Activity, BarChart3, CloudRain, MapPin, RefreshCw, Waves } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { api, ApiError } from "../services/api";
import type { HydroSeriesPoint, ProviderForecast, UpstreamForecastResponse, UpstreamStationForecast } from "../types/api";
import { StatusBadge } from "./StatusBadge";
import { chartTime } from "./stationForecastData";
export { chartTime } from "./stationForecastData";

function formatNumber(value: number | null | undefined, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function formatCompactDate(value: string | null | undefined) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function statNumber(value: number | string | null | undefined) {
  return typeof value === "number" ? value : null;
}

function formatStoredTime(value: string | null | undefined) {
  if (!value) return "-";
  return `${new Intl.DateTimeFormat("en-PK", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Karachi" }).format(new Date(value))} PKT`;
}

function errorMessage(error: unknown) {
  if (error instanceof ApiError) return error.message;
  return "Upstream forecast providers are temporarily unavailable.";
}

export function chartPath(points: HydroSeriesPoint[], startTime: number, endTime: number, maxValue: number, width: number, height: number) {
  let connected = false;
  return points.map((point) => {
    const time = chartTime(point.time);
    if (point.value === null || !Number.isFinite(point.value) || !Number.isFinite(time)) {
      connected = false;
      return "";
    }
    const x = ((time - startTime) / Math.max(endTime - startTime, 1)) * width;
    const y = height - (point.value / maxValue) * height;
    const command = `${connected ? "L" : "M"} ${x.toFixed(1)} ${y.toFixed(1)}`;
    connected = true;
    return command;
  }).join(" ");
}

function modelColor(provider: string) {
  return provider === "GloFAS" ? "#50f5d0" : "#ffc857";
}

export function ForecastChart({ providers }: { providers: ProviderForecast[] }) {
  const width = 760;
  const height = 210;
  const chartProviders = providers.map((provider) => ({
    ...provider,
    series: [...provider.series].sort((a, b) => chartTime(a.time) - chartTime(b.time)),
  })).filter((provider) => provider.series.some((point) => point.value !== null && Number.isFinite(point.value) && Number.isFinite(chartTime(point.time))));
  const allValues = chartProviders.flatMap((provider) => provider.series.map((point) => point.value).filter((value): value is number => value !== null));
  const maxValue = Math.max(...allValues, 0) || 1;
  const axisDigits = maxValue < 1 ? Math.min(8, Math.ceil(-Math.log10(maxValue)) + 2) : maxValue < 10 ? 2 : 1;
  const times = chartProviders.flatMap((provider) => provider.series.filter((point) => point.value !== null && Number.isFinite(chartTime(point.time))).map((point) => chartTime(point.time)));
  const startTime = Math.min(...times);
  const endTime = Math.max(...times);
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  const dateFormatter = new Intl.DateTimeFormat("en", { month: "short", day: "numeric", timeZone: "UTC" });

  if (chartProviders.length === 0) {
    return <div className="source-chart-empty">Forecast graph is unavailable from both providers.</div>;
  }

  return (
    <div className="source-chart-wrap">
      <div className="source-chart-legend" aria-label="Forecast providers">
        {providers.map((provider) => <span key={provider.provider}><i style={{ background: modelColor(provider.provider) }} />{provider.provider}{!chartProviders.some((item) => item.provider === provider.provider) && " (unavailable)"}</span>)}
      </div>
      <div className="source-chart-axis-title">River discharge (m3/s)</div>
      <div className="source-chart-area">
        <div className="source-chart-axis" aria-label="River discharge scale">
          {ticks.map((tick) => <span key={tick} style={{ top: `${tick * 100}%` }}>{formatNumber(maxValue * (1 - tick), axisDigits)}</span>)}
        </div>
        <div className="source-chart-plot">
      <svg className="source-forecast-chart" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="River discharge in cubic metres per second by date in UTC">
        <title>River discharge (m3/s) against date (UTC)</title>
        {ticks.map((tick) => (
          <line className="source-chart-grid" x1="0" x2={width} y1={height * tick} y2={height * tick} key={tick} />
        ))}
        {ticks.map((tick) => <line className="source-chart-grid" x1={width * tick} x2={width * tick} y1="0" y2={height} key={`date-${tick}`} />)}
        {chartProviders.map((provider) => (
          <path
            d={chartPath(provider.series, startTime, endTime, maxValue, width, height)}
            fill="none"
            key={provider.provider}
            stroke={modelColor(provider.provider)}
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="3"
            vectorEffect="non-scaling-stroke"
          />
        ))}
      </svg>
          <div className="source-chart-dates">
            {ticks.map((tick) => <span key={tick} style={{ left: `${tick * 100}%` }}>{dateFormatter.format(startTime + tick * (endTime - startTime))}</span>)}
          </div>
          <div className="source-chart-axis-title source-chart-date-title">Date (UTC)</div>
        </div>
      </div>
    </div>
  );
}

function TrendStrip({ provider }: { provider: ProviderForecast }) {
  const points = provider.retrospective.filter((point) => point.value !== null).slice(-14);
  const max = Math.max(...points.map((point) => point.value ?? 0), 1);
  return (
    <div className="source-trend-row">
      <div><strong>{provider.provider}</strong><span>{provider.recent_trend_cumecs !== null ? `${provider.recent_trend_cumecs >= 0 ? "+" : ""}${formatNumber(provider.recent_trend_cumecs)} cumecs recent trend` : "Recent trend unavailable"}</span></div>
      <div className="source-trend-bars">
        {points.length > 0 ? points.map((point) => (
          <span
            key={`${provider.provider}-${point.time}`}
            style={{ height: `${Math.max(((point.value ?? 0) / max) * 100, 5)}%` }}
            title={`${formatCompactDate(point.time)}: ${formatNumber(point.value)} cumecs`}
          />
        )) : <em>No retrospective series</em>}
      </div>
    </div>
  );
}

function ProviderStatCard({ provider }: { provider: ProviderForecast }) {
  return (
    <div className="source-provider-card">
      <div><strong>{provider.provider}</strong><StatusBadge value={provider.status.toUpperCase()} subtle /></div>
      <span>{provider.source}</span>
      <dl>
        <div><dt>Current</dt><dd>{formatNumber(provider.current_cumecs)} cumecs</dd></div>
        <div><dt>Peak forecast</dt><dd>{formatNumber(provider.peak_forecast_cumecs)} cumecs</dd></div>
        <div><dt>Peak time</dt><dd>{formatCompactDate(provider.peak_forecast_time)}</dd></div>
        {provider.river_id && <div><dt>River ID</dt><dd>{provider.river_id}</dd></div>}
      </dl>
      {provider.note && <p>{provider.note}</p>}
    </div>
  );
}

function SourceFloodContent({ station }: { station: UpstreamStationForecast }) {
  const rainfallForecast = station.rainfall.filter((point) => point.phase === "forecast");
  const maxRain = station.stats.max_forecast_rain_mm;
  const rainProbability = station.stats.max_rain_probability_percent;

  return (
    <>
      <div className="source-flood-types">
        {station.flood_types.map((item) => (
          <div className={`source-flood-type severity-${item.severity.toLowerCase()}`} key={item.type}>
            <div><strong>{item.type}</strong><StatusBadge value={item.severity} subtle /></div>
            <b>{item.probability}%</b>
            <span>{item.lead_time}</span>
            <p>{item.basis}</p>
          </div>
        ))}
      </div>

      <div className="source-expanded-grid">
        <div className="source-graph-panel">
          <div className="source-section-head"><BarChart3 size={16} /><strong>GloFAS and GEOGloWS in parallel</strong></div>
          <ForecastChart providers={station.providers} />
        </div>

        <div className="source-stats-panel">
          <div className="source-section-head"><Activity size={16} /><strong>Important stats</strong></div>
          <div className="source-stat-grid">
            <div><span>Mean current flow</span><strong>{formatNumber(statNumber(station.stats.current_mean_cumecs))} cumecs</strong></div>
            <div><span>Highest model peak</span><strong>{formatNumber(statNumber(station.stats.highest_provider_peak_cumecs))} cumecs</strong></div>
            <div><span>Peak/current ratio</span><strong>{formatNumber(statNumber(station.stats.peak_to_current_ratio), 2)}x</strong></div>
            <div><span>Max forecast rain</span><strong>{formatNumber(typeof maxRain === "number" ? maxRain : null)} mm</strong></div>
            <div><span>Max rain probability</span><strong>{formatNumber(typeof rainProbability === "number" ? rainProbability : null, 0)}%</strong></div>
            <div><span>Fastest model rise</span><strong>{formatNumber(statNumber(station.stats.geoglows_max_step_rise_cumecs))} cumecs</strong></div>
          </div>
        </div>
      </div>

      <div className="source-provider-grid">
        {station.providers.map((provider) => <ProviderStatCard provider={provider} key={provider.provider} />)}
      </div>

      <div className="source-lower-grid">
        <div>
          <div className="source-section-head"><Waves size={16} /><strong>Past trend</strong></div>
          <div className="source-trend-stack">
            {station.providers.map((provider) => <TrendStrip provider={provider} key={provider.provider} />)}
          </div>
        </div>
        <div>
          <div className="source-section-head"><CloudRain size={16} /><strong>Rainfall context</strong></div>
          <div className="source-rain-strip">
            {rainfallForecast.map((point) => (
              <div key={point.date}>
                <span>{formatCompactDate(point.date)}</span>
                <strong>{formatNumber(point.precipitation_mm)} mm</strong>
                <small>{formatNumber(point.probability_percent, 0)}%</small>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="source-facts">
        <div><MapPin size={16} /><strong>{station.river} / {station.basin}</strong><span>{station.latitude.toFixed(2)}, {station.longitude.toFixed(2)}</span></div>
        <p>{station.source_focus}</p>
        {station.facts.map((fact) => <span key={fact}>{fact}</span>)}
      </div>
    </>
  );
}

export function SourceFloodForecastTab() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [data, setData] = useState<UpstreamForecastResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [requestingRefresh, setRequestingRefresh] = useState(false);
  const mounted = useRef(false);
  const refreshing = requestingRefresh || data?.refreshing;
  const pollMs = data?.refreshing || !data?.stations.length ? 5000 : 60000;

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const selectedStation = useMemo(() => {
    if (!data?.stations.length) return null;
    return data.stations.find((station) => station.id === selectedId) ?? data.stations[0];
  }, [data, selectedId]);

  useEffect(() => {
    let active = true;
    const load = () => api.upstreamForecasts()
      .then((response) => {
        if (!active) return;
        setData(response);
        setSelectedId((current) => current ?? response.stations[0]?.id ?? null);
        setError(null);
      })
      .catch((reason) => {
        if (!active) return;
        setError(errorMessage(reason));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    void load();
    const timer = window.setInterval(() => { void load(); }, pollMs);
    return () => { active = false; window.clearInterval(timer); };
  }, [pollMs]);

  async function refreshForecasts() {
    setRequestingRefresh(true);
    try {
      const response = await api.refreshUpstreamForecasts();
      if (mounted.current) { setData(response); setError(null); }
    } catch (reason) {
      if (mounted.current) setError(errorMessage(reason));
    } finally {
      if (mounted.current) setRequestingRefresh(false);
    }
  }

  return (
    <section className="source-forecast-tab is-expanded source-forecast-page" aria-label="Upstream station forecasts">
      <div className="source-cache-toolbar">
        <div aria-live="polite">
          <strong>{data?.cached_at ? `Stored ${formatStoredTime(data.cached_at)}` : "Preparing first forecast"}</strong>
          <span>{refreshing ? "Fetching latest forecasts" : data?.next_refresh_at ? `Next update ${formatStoredTime(data.next_refresh_at)}` : "Waiting for stored forecasts"}</span>
          <span>Automatic updates every {data?.refresh_interval_minutes ?? 60} minutes</span>
        </div>
        <button type="button" onClick={() => void refreshForecasts()} disabled={Boolean(refreshing) || loading} title="Fetch the latest upstream forecasts" className="source-refresh-button">
          <RefreshCw size={16} className={refreshing ? "spinning" : ""} />{refreshing ? "Refreshing" : "Refresh"}
        </button>
      </div>
      <div className="source-station-selector">
        {data?.stations.map((station) => (
          <button className={selectedStation?.id === station.id ? "active" : ""} key={station.id} onClick={() => setSelectedId(station.id)} type="button">
            <strong>{station.name}</strong>
            <span>{station.river}</span>
          </button>
        ))}
        {(loading || (!selectedStation && refreshing)) && <div className="source-loading"><RefreshCw className="spinning" size={16} /> Loading stored forecasts</div>}
      </div>

      {(error || data?.refresh_error) && <div className="source-error" role="status">{error || data?.refresh_error}</div>}

      {selectedStation && (
        <div className="source-tab-body expanded">
          <div className="source-station-summary">
            <div><strong>{selectedStation.name}</strong><span>{selectedStation.why_selected}</span></div>
            <span>Updated {formatStoredTime(data?.cached_at ?? data?.generated_at)}</span>
          </div>
          <SourceFloodContent station={selectedStation} />
          <div className="source-notes">
            {data?.notes.map((note) => <span key={note}>{note}</span>)}
          </div>
        </div>
      )}
    </section>
  );
}
