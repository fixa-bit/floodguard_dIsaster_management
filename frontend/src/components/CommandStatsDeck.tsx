import { BarChart3, ChevronDown, CloudRain, DatabaseZap, Droplets, RadioTower, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";

import { LOCATIONS } from "../config";
import type { DashboardData } from "../hooks/useDashboardData";
import type { DistrictRiskFeature, RiverResponse, Severity, WaterIntelligenceFeature, WeatherResponse } from "../types/api";
import { StatusBadge } from "./StatusBadge";

type DeckPanel = "risk" | "rivers" | "weather" | "operations" | "system";

interface Metric {
  label: string;
  value: string;
  accent?: "green" | "amber" | "red" | "blue";
}

const panelConfig: Array<{ id: DeckPanel; label: string; Icon: typeof BarChart3 }> = [
  { id: "risk", label: "National Risk", Icon: BarChart3 },
  { id: "rivers", label: "Rivers", Icon: Droplets },
  { id: "weather", label: "Rainfall", Icon: CloudRain },
  { id: "operations", label: "Operations", Icon: RadioTower },
  { id: "system", label: "System", Icon: DatabaseZap },
];

const severityOrder: Severity[] = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];

function formatNumber(value: number | null | undefined, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${Math.round(value)}%`;
}

function formatTime(value: string | null | undefined) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function maxNumber(values: Array<number | null | undefined>) {
  const numbers = values.filter((value): value is number => value !== null && value !== undefined && !Number.isNaN(value));
  return numbers.length > 0 ? Math.max(...numbers) : null;
}

function newestTime(values: Array<string | null | undefined>) {
  const timestamps = values
    .map((value) => value ? new Date(value) : null)
    .filter((date): date is Date => date !== null && !Number.isNaN(date.getTime()))
    .sort((a, b) => b.getTime() - a.getTime());
  return timestamps[0]?.toISOString() ?? null;
}

function keyedByLocation<T extends { location_id: string }>(items: T[]) {
  return new Map(items.map((item) => [item.location_id, item]));
}

function metricClass(metric: Metric) {
  return `command-stat-card ${metric.accent ? `command-stat-${metric.accent}` : ""}`;
}

function CommandMetrics({ metrics }: { metrics: Metric[] }) {
  return (
    <div className="command-stat-metrics">
      {metrics.map((metric) => (
        <div className={metricClass(metric)} key={metric.label}>
          <span>{metric.label}</span>
          <strong>{metric.value}</strong>
        </div>
      ))}
    </div>
  );
}

function severityCounts(features: DistrictRiskFeature[]) {
  return features.reduce<Record<Severity, number>>((counts, feature) => {
    counts[feature.properties.severity] += 1;
    return counts;
  }, { LOW: 0, MEDIUM: 0, HIGH: 0, CRITICAL: 0 });
}

function topRiskDistricts(features: DistrictRiskFeature[]) {
  return [...features]
    .sort((a, b) => b.properties.risk_probability - a.properties.risk_probability)
    .slice(0, 5);
}

function topWaterStations(features: WaterIntelligenceFeature[]) {
  return features
    .filter((feature) => feature.properties.data_class !== "gis_feature")
    .slice(0, 6);
}

export function CommandStatsDeck({ data, onRefresh }: { data: DashboardData; onRefresh?: () => Promise<unknown> | void }) {
  const [activePanel, setActivePanel] = useState<DeckPanel | null>(null);
  const districts = data.nationalRisk?.features ?? [];
  const locationWeather = data.locationWeather.length > 0 ? data.locationWeather : (data.weather ? [data.weather] : []);
  const locationRivers = data.locationRivers.length > 0 ? data.locationRivers : (data.river ? [data.river] : []);
  const weatherByLocation = useMemo(() => keyedByLocation<WeatherResponse>(locationWeather), [locationWeather]);
  const riversByLocation = useMemo(() => keyedByLocation<RiverResponse>(locationRivers), [locationRivers]);
  const counts = useMemo(() => severityCounts(districts), [districts]);
  const topDistricts = useMemo(() => topRiskDistricts(districts), [districts]);
  const topStations = useMemo(() => topWaterStations(data.waterIntelligence?.features ?? []), [data.waterIntelligence]);
  const highestRisk = data.summary?.highest_risk_probability ?? data.risk?.flood_probability ?? null;
  const maxDischarge = maxNumber(locationRivers.map((river) => river.discharge_cumecs));
  const maxForecastDischarge = maxNumber(locationRivers.map((river) => river.forecast_discharge_next_24h_cumecs));
  const maxRain24h = maxNumber(locationWeather.map((weather) => weather.rainfall_last_24h_mm));
  const maxForecastRain24h = maxNumber(locationWeather.map((weather) => weather.forecast_rainfall_next_24h_mm));
  const weatherUpdatedAt = newestTime(locationWeather.map((weather) => weather.timestamp));
  const riversUpdatedAt = newestTime(locationRivers.map((river) => river.timestamp));

  const riskMetrics: Metric[] = [
    { label: "Highest risk", value: formatPercent(highestRisk), accent: highestRisk && highestRisk >= 70 ? "red" : "green" },
    { label: "Districts monitored", value: formatNumber(data.nationalRisk?.metadata.returned_feature_count ?? districts.length, 0) },
    { label: "High/Critical", value: formatNumber(counts.HIGH + counts.CRITICAL, 0), accent: counts.CRITICAL > 0 ? "red" : "amber" },
    { label: "Observed", value: formatTime(data.nationalRisk?.metadata.observed_at) },
  ];

  const riverMetrics: Metric[] = [
    { label: "Cities reporting", value: `${locationRivers.length}/${LOCATIONS.length}`, accent: "green" },
    { label: "Max discharge", value: `${formatNumber(maxDischarge, 0)} cumecs`, accent: "blue" },
    { label: "Max 24h forecast", value: `${formatNumber(maxForecastDischarge, 0)} cumecs` },
    { label: "Updated", value: formatTime(riversUpdatedAt) },
  ];

  const weatherMetrics: Metric[] = [
    { label: "Cities reporting", value: `${locationWeather.length}/${LOCATIONS.length}`, accent: "green" },
    { label: "Max rain 24h", value: `${formatNumber(maxRain24h)} mm`, accent: "blue" },
    { label: "Max forecast 24h", value: `${formatNumber(maxForecastRain24h)} mm`, accent: "amber" },
    { label: "Updated", value: formatTime(weatherUpdatedAt) },
  ];

  const operationsMetrics: Metric[] = [
    { label: "Active incidents", value: formatNumber(data.summary?.active_incidents ?? data.incidents.length, 0), accent: "amber" },
    { label: "Critical incidents", value: formatNumber(data.summary?.critical_incidents, 0), accent: "red" },
    { label: "Confirmed floods", value: formatNumber(data.summary?.confirmed_floods, 0), accent: "blue" },
    { label: "Pending reports", value: formatNumber(data.summary?.pending_citizen_reports ?? data.reports.length, 0) },
  ];

  const systemMetrics: Metric[] = [
    { label: "Data mode", value: data.system?.data_mode ?? data.nationalRisk?.metadata.data_mode ?? "-" },
    { label: "Monitoring", value: `${formatNumber(data.risk?.monitoring_interval_minutes ?? data.system?.monitoring_interval_minutes, 0)} min` },
    { label: "Risk engine", value: data.risk?.model_type ?? "-" },
    { label: "Water feed", value: data.waterIntelligence?.metadata.forecast_provider ?? "-" },
  ];

  const activeMetrics =
    activePanel === "risk" ? riskMetrics :
    activePanel === "rivers" ? riverMetrics :
    activePanel === "weather" ? weatherMetrics :
    activePanel === "operations" ? operationsMetrics :
    systemMetrics;

  return (
    <section className="command-stats-deck" aria-label="Command statistics">
      <div className="command-stats-tabs">
        {panelConfig.map(({ id, label, Icon }) => (
          <button aria-expanded={activePanel === id} className={activePanel === id ? "active" : ""} key={id} onClick={() => setActivePanel(activePanel === id ? null : id)} type="button">
            <Icon size={16} />
            <span>{label}</span>
            <ChevronDown size={14} />
          </button>
        ))}
      </div>

      <div className="command-stats-snapshot">
        <div><span>National risk</span><strong>{formatPercent(highestRisk)}</strong></div>
        <div><span>Max river discharge</span><strong>{formatNumber(maxDischarge, 0)} cumecs</strong></div>
        <div><span>Max rain forecast</span><strong>{formatNumber(maxForecastRain24h)} mm</strong></div>
        <div><span>Active incidents</span><strong>{formatNumber(data.summary?.active_incidents ?? data.incidents.length, 0)}</strong></div>
        <div><span>Mode</span><strong>{data.system?.data_mode ?? "-"}</strong></div>
      </div>

      {activePanel === "risk" && (
        <div className="command-stats-panel">
          <CommandMetrics metrics={activeMetrics} />
          <div className="command-panel-grid">
            <div className="command-severity-strip">
              {severityOrder.map((severity) => (
                <div className={`severity-chip severity-${severity.toLowerCase()}`} key={severity}>
                  <span>{severity}</span>
                  <strong>{counts[severity]}</strong>
                </div>
              ))}
            </div>
            <div className="command-table-wrap">
              <table className="data-table command-data-table">
                <thead><tr><th>District</th><th>Severity</th><th>Risk</th><th>Rain 24h</th><th>Forecast</th></tr></thead>
                <tbody>
                  {topDistricts.map((feature) => (
                    <tr key={feature.id}>
                      <td><strong>{feature.properties.district_name}</strong><small>{feature.properties.risk_basis}</small></td>
                      <td><StatusBadge value={feature.properties.severity} subtle /></td>
                      <td>{formatPercent(feature.properties.risk_probability)}</td>
                      <td>{formatNumber(feature.properties.rainfall_24h_mm)} mm</td>
                      <td>{formatNumber(feature.properties.forecast_rainfall_24h_mm)} mm</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {activePanel === "rivers" && (
        <div className="command-stats-panel">
          <div className="command-panel-head">
            <div><strong>River Water Telemetry</strong><span>Official FFD observations are used where available; GloFAS remains fallback/forecast context.</span></div>
            {onRefresh && <button className="command-panel-refresh" onClick={() => void onRefresh()} type="button"><RefreshCw size={13} /> Refresh</button>}
          </div>
          <CommandMetrics metrics={activeMetrics} />
          <div className="command-panel-grid command-panel-grid-wide">
            <div className="command-table-wrap">
              <table className="data-table command-data-table command-location-table">
                <thead><tr><th>River</th><th>Reach / station</th><th>Source</th><th>Fetched time</th><th>Observed level</th><th>Discharge</th><th>24h forecast</th><th>Mean</th><th>Median</th><th>Min / max</th><th>P25 / P75</th><th>Daily change</th><th>Status</th></tr></thead>
                <tbody>
                  {LOCATIONS.map((location) => {
                    const river = riversByLocation.get(location.id);
                    const level = river?.observed_level_value != null
                      ? `${formatNumber(river.observed_level_value, 2)} ${river.observed_level_unit ?? ""}`.trim()
                      : river?.river_level_m != null
                        ? `${formatNumber(river.river_level_m, 2)} m`
                        : "-";
                    return (
                      <tr key={location.id}>
                        <td><strong>{river?.river_name ?? location.river}</strong><small>{location.region}</small></td>
                        <td>{river ? <><strong>{river.station_name}</strong><small>{river.location_name}</small></> : location.name}</td>
                        <td>{river?.source ?? "-"}</td>
                        <td>{river?.official_recording_time ?? formatTime(river?.timestamp)}</td>
                        <td>{level}</td>
                        <td>{formatNumber(river?.discharge_cumecs, 0)} cumecs</td>
                        <td>{formatNumber(river?.forecast_discharge_next_24h_cumecs, 0)} cumecs</td>
                        <td>{formatNumber(river?.discharge_mean_cumecs, 0)} cumecs</td>
                        <td>{formatNumber(river?.discharge_median_cumecs, 0)} cumecs</td>
                        <td>{formatNumber(river?.discharge_min_cumecs, 0)} / {formatNumber(river?.discharge_max_cumecs, 0)}</td>
                        <td>{formatNumber(river?.discharge_p25_cumecs, 0)} / {formatNumber(river?.discharge_p75_cumecs, 0)}</td>
                        <td>{formatNumber(river?.discharge_change_cumecs_per_day, 0)} cumecs/day</td>
                        <td>{river?.status ? <StatusBadge value={river.status} subtle /> : "-"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="command-table-wrap">
              <table className="data-table command-data-table">
                <thead><tr><th>Water feature</th><th>System</th><th>Class</th><th>Status</th><th>Forecast</th></tr></thead>
                <tbody>
                  {topStations.slice(0, 4).map((feature) => (
                    <tr key={feature.id}>
                      <td><strong>{feature.properties.name}</strong><small>{feature.properties.feature_kind}</small></td>
                      <td>{feature.properties.water_system}</td>
                      <td>{feature.properties.data_class.replaceAll("_", " ")}</td>
                      <td>{feature.properties.telemetry_status}</td>
                      <td>{formatNumber(feature.properties.forecast_discharge_cumecs, 0)}</td>
                    </tr>
                  ))}
                  {topStations.length === 0 && <tr><td colSpan={5}>No station telemetry available.</td></tr>}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {activePanel === "weather" && (
        <div className="command-stats-panel">
          <div className="command-panel-head">
            <div><strong>Rainfall Telemetry</strong><span>Live Open-Meteo values can be 0 mm when monitored cities are currently dry.</span></div>
            {onRefresh && <button className="command-panel-refresh" onClick={() => void onRefresh()} type="button"><RefreshCw size={13} /> Refresh</button>}
          </div>
          <CommandMetrics metrics={activeMetrics} />
          <div className="command-table-wrap">
            <table className="data-table command-data-table command-location-table">
              <thead><tr><th>City</th><th>Source</th><th>Updated</th><th>Current</th><th>1h</th><th>6h</th><th>24h</th><th>Forecast 6h</th><th>Forecast 24h</th><th>Temp</th><th>Humidity</th><th>Soil</th></tr></thead>
              <tbody>
                {LOCATIONS.map((location) => {
                  const weather = weatherByLocation.get(location.id);
                  return (
                    <tr key={location.id}>
                      <td><strong>{location.name}</strong><small>{location.region} - {location.river}</small></td>
                      <td>{weather?.source ?? "-"}</td>
                      <td>{formatTime(weather?.timestamp)}</td>
                      <td>{formatNumber(weather?.rainfall_current_mm)} mm</td>
                      <td>{formatNumber(weather?.rainfall_last_1h_mm)} mm</td>
                      <td>{formatNumber(weather?.rainfall_last_6h_mm)} mm</td>
                      <td>{formatNumber(weather?.rainfall_last_24h_mm)} mm</td>
                      <td>{formatNumber(weather?.forecast_rainfall_next_6h_mm)} mm</td>
                      <td>{formatNumber(weather?.forecast_rainfall_next_24h_mm)} mm</td>
                      <td>{formatNumber(weather?.temperature_c)} C</td>
                      <td>{formatNumber(weather?.humidity_percent, 0)}%</td>
                      <td>{formatNumber(weather?.soil_moisture_percent, 0)}%</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {activePanel === "operations" && (
        <div className="command-stats-panel">
          <CommandMetrics metrics={activeMetrics} />
          <div className="command-table-wrap">
            <table className="data-table command-data-table">
              <thead><tr><th>Latest operational item</th><th>Location</th><th>Status</th><th>Confidence</th><th>Updated</th></tr></thead>
              <tbody>
                {data.incidents.slice(0, 4).map((incident) => (
                  <tr key={`incident-${incident.id}`}>
                    <td><strong>{incident.type}</strong><small>{incident.description}</small></td>
                    <td>{incident.location_id}</td>
                    <td><StatusBadge value={incident.status} subtle /></td>
                    <td>{formatPercent(incident.confidence)}</td>
                    <td>{formatTime(incident.updated_at)}</td>
                  </tr>
                ))}
                {data.reports.slice(0, 2).map((report) => (
                  <tr key={`report-${report.id}`}>
                    <td><strong>Citizen report</strong><small>{report.description}</small></td>
                    <td>{report.location_id}</td>
                    <td><StatusBadge value={report.verification_status} subtle /></td>
                    <td>-</td>
                    <td>{formatTime(report.timestamp)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {activePanel === "system" && (
        <div className="command-stats-panel">
          <CommandMetrics metrics={activeMetrics} />
          <div className="command-system-grid">
            <div><span>Backend</span><strong>{data.system?.backend_status ?? "-"}</strong></div>
            <div><span>Scenario</span><strong>{data.system?.active_scenario ?? data.risk?.scenario ?? "-"}</strong></div>
            <div><span>Boundary source</span><strong>{data.nationalRisk?.metadata.boundary_source ?? "-"}</strong></div>
            <div><span>Water features</span><strong>{formatNumber(data.waterIntelligence?.metadata.water_feature_count, 0)}</strong></div>
            <div><span>Observed stations</span><strong>{formatNumber(data.waterIntelligence?.metadata.observed_station_count, 0)}</strong></div>
            <div><span>Model points</span><strong>{formatNumber(data.waterIntelligence?.metadata.model_forecast_count, 0)}</strong></div>
          </div>
        </div>
      )}
    </section>
  );
}
