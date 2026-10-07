import { Activity, AlertTriangle, CloudRain, Mountain, Waves } from "lucide-react";
import { useMemo, useState } from "react";

import { LOCATIONS } from "../config";
import type { DashboardData } from "../hooks/useDashboardData";
import type { ModelForecastPoint } from "../types/api";
import { formatDateTime } from "../utils/format";

interface RiskView {
  id: string;
  title: string;
  horizon: string;
  scope: string;
  predicts: string;
  model: string;
  score: number;
  detail: string;
  issuedAt: string | null;
  target: string;
  outputPoints?: string[];
  Icon: typeof Waves;
}

function clamp(value: number) {
  return Math.max(0, Math.min(100, Math.round(value)));
}

function maxNumber(values: Array<number | null | undefined>) {
  const numbers = values.filter((value): value is number => value !== null && value !== undefined && !Number.isNaN(value));
  return numbers.length > 0 ? Math.max(...numbers) : 0;
}

function average(values: Array<number | null | undefined>) {
  const numbers = values.filter((value): value is number => value !== null && value !== undefined && !Number.isNaN(value));
  return numbers.length > 0 ? numbers.reduce((sum, value) => sum + value, 0) / numbers.length : 0;
}

function riskBand(score: number) {
  if (score >= 70) return "high";
  if (score >= 40) return "medium";
  return "low";
}

function formatIssuedAt(value: string | null) {
  if (!value) return "pending live data";
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? value : formatDateTime(value);
}

function formatHorizon(hours: number) {
  if (hours >= 168 && hours % 24 === 0) return `+${Math.round(hours / 24)}d`;
  return `+${hours}h`;
}

function pointsForTarget(points: ModelForecastPoint[], targetId: string | undefined) {
  const selected = targetId ?? points[0]?.target_id;
  return points
    .filter((point) => point.target_id === selected)
    .sort((a, b) => a.horizon_hours - b.horizon_hours);
}

function ForecastIntervalGraph({
  points,
  selectedTarget,
  onTargetChange,
}: {
  points: ModelForecastPoint[];
  selectedTarget: string | undefined;
  onTargetChange: (targetId: string) => void;
}) {
  const targets = Array.from(new Map(points.map((point) => [point.target_id, point.target_name])).entries());
  const series = pointsForTarget(points, selectedTarget);
  if (!series.length) {
    return (
      <div className="forecast-graph-empty">
        <span>No stored forecast series yet</span>
      </div>
    );
  }
  const unit = series[0].value_unit;
  const percentLike = unit.includes("percent");
  const maxValue = percentLike ? 100 : Math.max(...points.map((point) => point.value), 1) * 1.08;
  const minValue = 0;
  const valueRange = Math.max(maxValue - minValue, 1);
  const width = 220;
  const height = 62;
  const path = series
    .map((point, index) => {
      const x = series.length === 1 ? width / 2 : (index / (series.length - 1)) * width;
      const y = height - ((point.value - minValue) / valueRange) * height;
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
  const latest = series[series.length - 1];

  return (
    <div className="forecast-graph">
      <div className="forecast-target-tabs" aria-label="Forecast target selector">
        {targets.map(([targetId, targetName]) => (
          <button
            className={targetId === (selectedTarget ?? series[0].target_id) ? "active" : ""}
            key={targetId}
            onClick={() => onTargetChange(targetId)}
            type="button"
          >
            {targetName}
          </button>
        ))}
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${latest.target_name} forecast interval graph`}>
        <path d={path} />
        {series.map((point, index) => {
          const x = series.length === 1 ? width / 2 : (index / (series.length - 1)) * width;
          const y = height - ((point.value - minValue) / valueRange) * height;
          return <circle cx={x} cy={y} key={`${point.target_id}-${point.horizon_hours}`} r="2.4" />;
        })}
      </svg>
      <div className="forecast-graph-axis">
        {series.map((point, index) => (
          <span className={index % 2 === 0 || index === series.length - 1 ? "" : "muted"} key={point.horizon_hours}>
            {formatHorizon(point.horizon_hours)}
          </span>
        ))}
      </div>
      <div className="forecast-graph-summary">
        <strong>{latest.value.toLocaleString()} {latest.value_unit.replaceAll("_", " ")}</strong>
        <span>{latest.risk_class} at {formatHorizon(latest.horizon_hours)}</span>
      </div>
    </div>
  );
}

function RiverineModelFlow({ score }: { score: number }) {
  return (
    <div className="riverine-model-flow" aria-label="Riverine model flow">
      <div className="riverine-flow-header">
        <span>Baseline inputs</span>
        <strong>XGBoost</strong>
        <b>{score}%</b>
      </div>
      <div className="riverine-feature-groups">
        <span>Q(t), Q-3h, Q-6h, Q-12h, Q-24h</span>
        <span>Rain 3h, 6h, 24h + forecast rain</span>
        <span>Upstream Q, reservoir release, soil moisture</span>
      </div>
      <div className="riverine-station-table">
        <div><span>Station</span><span>Horizon</span><span>Outputs</span></div>
        <div><strong>Trimmu</strong><span>+24h</span><span>Discharge, class</span></div>
        <div><strong>Balloki</strong><span>+48h</span><span>Discharge, class</span></div>
      </div>
    </div>
  );
}

function FlashFloodModelFlow({ score }: { score: number }) {
  return (
    <div className="flash-flood-model-flow" aria-label="Flash-flood model flow">
      <div className="flash-flow-header">
        <span>Guidance model</span>
        <strong>LightGBM</strong>
        <b>{score}%</b>
      </div>
      <div className="flash-feature-grid">
        <span>Rain 15m, 1h, 3h, 6h</span>
        <span>Forecast rain + soil moisture</span>
        <span>Slope, elevation, drainage density</span>
        <span>Land cover, area, stream distance</span>
      </div>
      <div className="flash-target-row">
        <span>Target</span>
        <strong>P(flash flood within next 6h)</strong>
        <b>No risk to Extreme</b>
      </div>
    </div>
  );
}

function UrbanFloodModelFlow({ score }: { score: number }) {
  return (
    <div className="urban-flood-model-flow" aria-label="Urban flooding model flow">
      <div className="urban-flow-header">
        <span>Susceptibility</span>
        <strong>LightGBM/XGBoost</strong>
        <b>{score}%</b>
      </div>
      <div className="urban-feature-grid">
        <span>Rainfall + DEM + slope</span>
        <span>Drainage capacity</span>
        <span>Impervious surface + land use</span>
        <span>Waterlogging reports</span>
      </div>
      <div className="urban-class-row">
        <span>Grid/ward class</span>
        <strong>Low</strong>
        <strong>Moderate</strong>
        <strong>High</strong>
        <strong>Extremely high</strong>
      </div>
      <p>Depth bands require HEC-RAS 2D or another hydraulic model.</p>
    </div>
  );
}

export function FloodRiskMultiView({ data }: { data: DashboardData }) {
  const [selectedTargets, setSelectedTargets] = useState<Record<string, string>>({});
  const views = useMemo<RiskView[]>(() => {
    const highestRisk = (data.summary?.highest_risk_probability ?? data.risk?.flood_probability ?? 0) * 100;
    const maxRain24 = maxNumber(data.locationWeather.map((weather) => weather.forecast_rainfall_next_24h_mm));
    const maxRain6 = maxNumber(data.locationWeather.map((weather) => weather.forecast_rainfall_next_6h_mm));
    const maxRainCurrent = maxNumber(data.locationWeather.map((weather) => weather.rainfall_current_mm));
    const soil = average(data.locationWeather.map((weather) => weather.soil_moisture_percent));
    const maxDischarge = maxNumber(data.locationRivers.map((river) => river.discharge_cumecs));
    const maxForecastDischarge = maxNumber(data.locationRivers.map((river) => river.forecast_discharge_next_24h_cumecs));
    const maxPositiveChange = maxNumber(data.locationRivers.map((river) => Math.max(river.discharge_change_cumecs_per_day ?? 0, 0)));
    const hasRisingRiver = data.locationRivers.some((river) => ["RISING", "WARNING", "DANGER", "FLOOD", "CRITICAL", "ALERT"].includes(river.status.toUpperCase()));
    const driestRainSignal = maxRain24 <= 2 && maxRain6 <= 1;
    const riverIssuedAt = data.locationRivers[0]?.official_recording_time ?? data.river?.official_recording_time ?? data.locationRivers[0]?.timestamp ?? data.river?.timestamp ?? null;
    const weatherIssuedAt = data.locationWeather[0]?.timestamp ?? data.weather?.timestamp ?? null;
    const urbanTargetLabel = "Islamabad / Rawalpindi / Lahore grid cells";

    return [
      {
        id: "riverine",
        title: "Riverine Short-Term",
        horizon: "24-48h",
        scope: "Trimmu and Balloki station forecasts",
        predicts: "Station discharge and flood class",
        model: "XGBoost baseline; TFT comparison later",
        score: clamp(Math.max(highestRisk, hasRisingRiver ? 68 : 24, maxForecastDischarge / 35, maxDischarge / 38)),
        detail: `Max discharge ${Math.round(maxDischarge).toLocaleString()} cumecs; forecast ${Math.round(maxForecastDischarge).toLocaleString()} cumecs.`,
        issuedAt: riverIssuedAt,
        target: "Stations: Trimmu +24h; Balloki +48h",
        Icon: Waves,
      },
      {
        id: "flash",
        title: "Flash Flood",
        horizon: "0-6h",
        scope: "Hill torrents, streams, and urban catchments",
        predicts: "Probability of flash flood in next 6h",
        model: "LightGBM tabular GIS + rainfall baseline",
        score: clamp(maxRainCurrent * 6 + maxRain6 * 2.2 + maxRain24 * 1.1 + soil * 0.25),
        detail: `Rain now ${maxRainCurrent.toFixed(1)} mm; 6h rain ${maxRain6.toFixed(1)} mm; soil moisture avg ${soil.toFixed(0)}%.`,
        issuedAt: weatherIssuedAt,
        target: "Catchments: hill torrents, streams, urban drains",
        Icon: CloudRain,
      },
      {
        id: "urban",
        title: "Urban Flooding",
        horizon: "0-6h",
        scope: "City grid cells / wards",
        predicts: "Urban flood susceptibility class",
        model: "LightGBM/XGBoost susceptibility; HEC-RAS 2D for depth",
        score: clamp(maxRain6 * 2.3 + maxRain24 * 0.7 + soil * 0.18 + (data.reports.length > 0 ? 12 : 0)),
        detail: `Urban rain signal ${maxRain6.toFixed(1)} mm in 6h; ${data.reports.length} citizen waterlogging reports in system.`,
        issuedAt: weatherIssuedAt,
        target: urbanTargetLabel,
        Icon: CloudRain,
      },
      {
        id: "seasonal",
        title: "Seasonal Basin Risk",
        horizon: "Weeks-3mo",
        scope: "National basin summary",
        predicts: "Weeks-ahead basin flood risk",
        model: "LightGBM or TFT",
        score: clamp(highestRisk * 0.35 + soil * 0.38 + maxRain24 * 0.9),
        detail: "Uses basin saturation, seasonal rainfall signal, and current national risk baseline.",
        issuedAt: data.nationalRisk?.metadata.generated_at ?? data.risk?.timestamp ?? null,
        target: "National basin summary",
        Icon: Mountain,
      },
      {
        id: "upstream",
        title: "Upstream / Transboundary",
        horizon: "Hours-days",
        scope: "Downstream river reaches",
        predicts: "Anomalous upstream flow rise",
        model: "Isolation Forest + residual TFT",
        score: clamp((driestRainSignal ? 18 : 6) + maxPositiveChange / 16 + (hasRisingRiver ? 34 : 0)),
        detail: `Positive discharge anomaly ${Math.round(maxPositiveChange).toLocaleString()} cumecs/day while local rain signal is ${driestRainSignal ? "low" : "active"}.`,
        issuedAt: riverIssuedAt,
        target: "Downstream river reaches",
        Icon: Activity,
      },
    ];
  }, [data]);
  const forecastPointsByCase = useMemo(() => {
    return data.modelForecasts.reduce<Record<string, ModelForecastPoint[]>>((groups, point) => {
      groups[point.model_case] = [...(groups[point.model_case] ?? []), point];
      return groups;
    }, {});
  }, [data.modelForecasts]);

  return (
    <section className="flood-multiview flood-risk-page" aria-label="Predictive risk views">
        <div className="multiview-shell">
          <div className="multiview-grid">
          {views.map(({ id, title, horizon, scope, predicts, model, score, detail, issuedAt, target, outputPoints, Icon }) => (
            <article className={`multiview-card risk-${riskBand(score)}`} key={id}>
              <div className="multiview-card-head">
                <Icon size={15} />
                <div><strong>{title}</strong><span>{horizon}</span></div>
                <b>{score}%</b>
              </div>
              <div className="multiview-forecast-meta">
                <span>Issued {formatIssuedAt(issuedAt)}</span>
                <strong>{target}</strong>
              </div>
              <ForecastIntervalGraph
                points={forecastPointsByCase[id] ?? []}
                selectedTarget={selectedTargets[id]}
                onTargetChange={(targetId) => setSelectedTargets((current) => ({ ...current, [id]: targetId }))}
              />
              {id === "riverine" ? (
                <RiverineModelFlow score={score} />
              ) : id === "flash" ? (
                <FlashFloodModelFlow score={score} />
              ) : id === "urban" ? (
                <UrbanFloodModelFlow score={score} />
              ) : (
                <div className="mini-risk-map" aria-hidden="true">
                  <div className="mini-risk-river" />
                  {LOCATIONS.map((location, index) => (
                    <i
                      key={`${id}-${location.id}`}
                      style={{ left: `${34 + index * 13}%`, top: `${58 - index * 11}%` }}
                    />
                  ))}
                  <span style={{ width: `${Math.max(16, score)}%` }} />
                </div>
              )}
              <div className="multiview-scope"><span>Scope</span><strong>{scope}</strong></div>
              <div className="multiview-predicts"><span>Predicts</span><strong>{predicts}</strong></div>
              {outputPoints && (
                <ul className="multiview-outputs">
                  {outputPoints.map((point) => <li key={point}>{point}</li>)}
                </ul>
              )}
              <p>{detail}</p>
              <small><AlertTriangle size={11} /> {model}</small>
            </article>
          ))}
          </div>
        </div>
    </section>
  );
}
