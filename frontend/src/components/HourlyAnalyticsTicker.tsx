import { BrainCircuit, Clock3, CloudRain, RadioTower, ShieldAlert, Waves } from "lucide-react";
import { useMemo } from "react";

import type { DashboardData } from "../hooks/useDashboardData";

function formatNumber(value: number | null | undefined, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${Math.round(value)}%`;
}

function latestTimestamp(values: Array<string | null | undefined>) {
  const timestamps = values
    .map((value) => value ? new Date(value) : null)
    .filter((value): value is Date => value !== null && !Number.isNaN(value.getTime()))
    .sort((a, b) => b.getTime() - a.getTime());
  return timestamps[0] ?? new Date();
}

export function HourlyAnalyticsTicker({ data }: { data: DashboardData }) {
  const analytics = useMemo(() => {
    const highestRisk = data.summary?.highest_risk_probability ?? data.risk?.flood_probability ?? null;
    const maxForecastRain = Math.max(0, ...data.locationWeather.map((weather) => weather.forecast_rainfall_next_24h_mm ?? 0));
    const wettestCity = data.locationWeather
      .slice()
      .sort((a, b) => (b.forecast_rainfall_next_24h_mm ?? 0) - (a.forecast_rainfall_next_24h_mm ?? 0))[0];
    const topRiver = data.locationRivers
      .slice()
      .sort((a, b) => (b.discharge_cumecs ?? 0) - (a.discharge_cumecs ?? 0))[0];
    const floodLikeRivers = data.locationRivers.filter((river) => ["RISING", "WARNING", "DANGER", "FLOOD", "CRITICAL", "ALERT"].includes(river.status.toUpperCase()));
    const openImportantReports = data.reports.filter((report) => report.report_status !== "CLOSED" && report.is_important).length;
    const pendingReports = data.summary?.pending_citizen_reports ?? data.reports.filter((report) => report.verification_status === "PENDING").length;
    const activeIncidents = data.summary?.active_incidents ?? data.incidents.length;
    const generatedAt = latestTimestamp([
      ...data.locationWeather.map((weather) => weather.timestamp),
      ...data.locationRivers.map((river) => river.timestamp),
      data.risk?.timestamp,
    ]);

    const messages = [
      `National flood risk ${formatPercent(highestRisk)} with monitoring mode ${data.system?.monitoring_mode ?? data.summary?.monitoring_mode ?? "pending"}`,
      topRiver ? `${topRiver.river_name} ${formatNumber(topRiver.discharge_cumecs)} cumecs at ${topRiver.station_name}; 24h forecast ${formatNumber(topRiver.forecast_discharge_next_24h_cumecs)} cumecs` : "River telemetry is loading",
      floodLikeRivers.length > 0 ? `${floodLikeRivers.length} river reach requires accelerated 3-minute monitoring` : "All monitored river reaches are in normal modeled status",
      wettestCity ? `Rain outlook: max 24h forecast ${formatNumber(maxForecastRain, 1)} mm near ${wettestCity.location_name}` : "Rainfall telemetry is loading",
      `${activeIncidents} active incidents, ${pendingReports} pending citizen reports, ${openImportantReports} important open reports`,
      `Predictive briefing model v0 using live weather, GloFAS discharge, incidents, and citizen reports; ready for future LLM/model replacement`,
    ];

    return {
      generatedAt,
      status: floodLikeRivers.length > 0 || (highestRisk ?? 0) >= 70 ? "heightened" : "normal",
      messages,
    };
  }, [data]);

  const timeLabel = analytics.generatedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const trackItems = [...analytics.messages, ...analytics.messages];

  return (
    <aside className={`hourly-analytics-ticker ticker-${analytics.status}`} aria-label="Hourly predictive analytics briefing">
      <div className="ticker-lockup">
        <BrainCircuit size={18} />
        <div><strong>Hourly AI Analytics</strong><span><Clock3 size={11} /> {timeLabel}</span></div>
      </div>
      <div className="ticker-marquee" aria-live="polite">
        <div className="ticker-track">
          {trackItems.map((item, index) => (
            <span className="ticker-item" key={`${item}-${index}`}>
              {index % 3 === 0 ? <ShieldAlert size={14} /> : index % 3 === 1 ? <Waves size={14} /> : index % 3 === 2 ? <CloudRain size={14} /> : <RadioTower size={14} />}
              {item}
            </span>
          ))}
        </div>
      </div>
    </aside>
  );
}
