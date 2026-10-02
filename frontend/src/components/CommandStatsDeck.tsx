import { Activity, BarChart3, ChevronDown, CloudRain, DatabaseZap, Droplets, RadioTower } from "lucide-react";
import { useMemo, useState } from "react";

import type { DashboardData } from "../hooks/useDashboardData";
import type { DistrictRiskFeature, Severity, WaterIntelligenceFeature } from "../types/api";
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

export function CommandStatsDeck({ data }: { data: DashboardData }) {
  const [activePanel, setActivePanel] = useState<DeckPanel | null>(null);
  const districts = data.nationalRisk?.features ?? [];
  const counts = useMemo(() => severityCounts(districts), [districts]);
  const topDistricts = useMemo(() => topRiskDistricts(districts), [districts]);
  const topStations = useMemo(() => topWaterStations(data.waterIntelligence?.features ?? []), [data.waterIntelligence]);
  const highestRisk = data.summary?.highest_risk_probability ?? data.risk?.flood_probability ?? null;

  const riskMetrics: Metric[] = [
    { label: "Highest risk", value: formatPercent(highestRisk), accent: highestRisk && highestRisk >= 70 ? "red" : "green" },
    { label: "Districts monitored", value: formatNumber(data.nationalRisk?.metadata.returned_feature_count ?? districts.length, 0) },
    { label: "High/Critical", value: formatNumber(counts.HIGH + counts.CRITICAL, 0), accent: counts.CRITICAL > 0 ? "red" : "amber" },
    { label: "Observed", value: formatTime(data.nationalRisk?.metadata.observed_at) },
  ];

  const riverMetrics: Metric[] = [
    { label: "River station", value: data.river?.station_name ?? "-" },
    { label: "River level", value: `${formatNumber(data.river?.river_level_m)} m` },
    { label: "Discharge", value: `${formatNumber(data.river?.discharge_cumecs, 0)} cumecs`, accent: "blue" },
    { label: "24h forecast", value: `${formatNumber(data.river?.forecast_discharge_next_24h_cumecs, 0)} cumecs` },
  ];

  const weatherMetrics: Metric[] = [
    { label: "Rain 24h", value: `${formatNumber(data.weather?.rainfall_last_24h_mm)} mm`, accent: "blue" },
    { label: "Forecast 24h", value: `${formatNumber(data.weather?.forecast_rainfall_next_24h_mm)} mm`, accent: "amber" },
    { label: "Soil moisture", value: `${formatNumber(data.weather?.soil_moisture_percent, 0)}%` },
    { label: "Humidity", value: `${formatNumber(data.weather?.humidity_percent, 0)}%` },
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
        <div><span>River discharge</span><strong>{formatNumber(data.river?.discharge_cumecs, 0)} cumecs</strong></div>
        <div><span>Rain forecast</span><strong>{formatNumber(data.weather?.forecast_rainfall_next_24h_mm)} mm</strong></div>
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
          <CommandMetrics metrics={activeMetrics} />
          <div className="command-panel-grid">
            <div className="command-river-levels">
              <div><span>Normal</span><strong>{formatNumber(data.river?.normal_level_m)} m</strong></div>
              <div><span>Warning</span><strong>{formatNumber(data.river?.warning_level_m)} m</strong></div>
              <div><span>Danger</span><strong>{formatNumber(data.river?.danger_level_m)} m</strong></div>
              <div><span>Rate of rise</span><strong>{formatNumber(data.river?.rate_of_rise_m_per_hour)} m/hr</strong></div>
            </div>
            <div className="command-table-wrap">
              <table className="data-table command-data-table">
                <thead><tr><th>Station / Feature</th><th>System</th><th>Class</th><th>Status</th><th>Forecast</th></tr></thead>
                <tbody>
                  {topStations.map((feature) => (
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
          <CommandMetrics metrics={activeMetrics} />
          <div className="command-panel-grid command-panel-grid-compact">
            <div className="command-weather-stack">
              <div><span>Current rain</span><strong>{formatNumber(data.weather?.rainfall_current_mm)} mm</strong></div>
              <div><span>Last 1h</span><strong>{formatNumber(data.weather?.rainfall_last_1h_mm)} mm</strong></div>
              <div><span>Last 6h</span><strong>{formatNumber(data.weather?.rainfall_last_6h_mm)} mm</strong></div>
              <div><span>Forecast 6h</span><strong>{formatNumber(data.weather?.forecast_rainfall_next_6h_mm)} mm</strong></div>
            </div>
            <div className="command-weather-focus">
              <Activity size={20} />
              <span>{data.weather?.location_name ?? "Selected area"}</span>
              <strong>{formatNumber(data.weather?.temperature_c)} C</strong>
              <small>Temperature with {formatNumber(data.weather?.humidity_percent, 0)}% humidity</small>
            </div>
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
