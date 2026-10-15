import { Activity, AlertTriangle, CloudRain, Info, Mountain, Waves } from "lucide-react";
import { useMemo, useRef, useState, type KeyboardEvent } from "react";

import { LOCATIONS } from "../config";
import type { DashboardData } from "../hooks/useDashboardData";
import type { ModelForecastPoint } from "../types/api";
import { formatDateTime } from "../utils/format";
import { PredictiveInputsDialog } from "./PredictiveInputsDialog";
import { TenYearRiskOutlook } from "./TenYearRiskOutlook";
import "../ten-year-risk-outlook.css";

type RiskMode = "near-term" | "ten-year";

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
  const demonstration = series.some((point) => point.point_metadata.simulation_source === "dummy_model_forecast_v3");

  return (
    <div className="forecast-graph">
      {demonstration && <span className="forecast-example-label">Example series</span>}
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
        <span>Current screening inputs</span>
        <strong>Rule score</strong>
        <b>{score}/100</b>
      </div>
      <div className="riverine-feature-groups">
        <span>Current risk summary</span>
        <span>Current + next-day discharge</span>
        <span>Rising or warning river status</span>
      </div>
      <div className="riverine-station-table">
        <div><span>Example target</span><span>Horizon</span><span>Graph</span></div>
        <div><strong>Trimmu</strong><span>+24h</span><span>Demo series</span></div>
        <div><strong>Balloki</strong><span>+48h</span><span>Demo series</span></div>
      </div>
    </div>
  );
}

function FlashFloodModelFlow({ score }: { score: number }) {
  return (
    <div className="flash-flood-model-flow" aria-label="Flash-flood model flow">
      <div className="flash-flow-header">
        <span>Current screening inputs</span>
        <strong>Rule score</strong>
        <b>{score}/100</b>
      </div>
      <div className="flash-feature-grid">
        <span>Current rainfall</span>
        <span>Forecast rain 6h + 24h</span>
        <span>Mean soil moisture</span>
        <span>Weighted screening rule</span>
      </div>
      <div className="flash-target-row">
        <span>Target</span>
        <strong>Screening score</strong>
        <b>0–100</b>
      </div>
    </div>
  );
}

function UrbanFloodModelFlow({ score }: { score: number }) {
  return (
    <div className="urban-flood-model-flow" aria-label="Urban flooding model flow">
      <div className="urban-flow-header">
        <span>Current screening inputs</span>
        <strong>Rule score</strong>
        <b>{score}/100</b>
      </div>
      <div className="urban-feature-grid">
        <span>Forecast rain 6h + 24h</span>
        <span>Mean soil moisture</span>
        <span>Any citizen report</span>
        <span>Weighted screening rule</span>
      </div>
      <div className="urban-class-row">
        <span>Score bands</span>
        <strong>Low</strong>
        <strong>Medium</strong>
        <strong>High</strong>
      </div>
      <p>Example grid curves are for illustration.</p>
    </div>
  );
}

export function FloodRiskMultiView({ data }: { data: DashboardData }) {
  const [mode, setMode] = useState<RiskMode>("near-term");
  const modeTabs = useRef<HTMLDivElement>(null);
  const [selectedTargets, setSelectedTargets] = useState<Record<string, string>>({});
  const [showInputs, setShowInputs] = useState(false);
  function selectMode(nextMode: RiskMode) {
    setShowInputs(false);
    setMode(nextMode);
  }
  function handleModeKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const nextMode = event.key === "Home" ? "near-term"
      : event.key === "End" ? "ten-year"
      : ["ArrowLeft", "ArrowRight"].includes(event.key) ? (mode === "near-term" ? "ten-year" : "near-term")
      : null;
    if (!nextMode) return;
    event.preventDefault();
    selectMode(nextMode);
    modeTabs.current?.querySelector<HTMLButtonElement>(`#risk-mode-${nextMode}`)?.focus();
  }
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
    const driestRainSignal = data.locationWeather.length > 0 && maxRain24 <= 2 && maxRain6 <= 1;
    const riverIssuedAt = data.locationRivers[0]?.official_recording_time ?? data.river?.official_recording_time ?? data.locationRivers[0]?.timestamp ?? data.river?.timestamp ?? null;
    const weatherIssuedAt = data.locationWeather[0]?.timestamp ?? data.weather?.timestamp ?? null;
    const urbanTargetLabel = "Islamabad / Rawalpindi / Lahore grid cells";

    return [
      {
        id: "riverine",
        title: "Riverine Short-Term",
        horizon: "Current signal",
        scope: "Regional river screening; example graphs for Trimmu and Balloki",
        predicts: "River risk screening score",
        model: "Dashboard rule score; graph uses example data",
        score: data.locationRivers.length || data.summary || data.risk ? clamp(Math.max(highestRisk, hasRisingRiver ? 68 : 24, maxForecastDischarge / 35, maxDischarge / 38)) : 0,
        detail: `Max discharge ${Math.round(maxDischarge).toLocaleString()} cumecs; forecast ${Math.round(maxForecastDischarge).toLocaleString()} cumecs.`,
        issuedAt: riverIssuedAt,
        target: "Stations: Trimmu +24h; Balloki +48h",
        Icon: Waves,
      },
      {
        id: "flash",
        title: "Flash Flood",
        horizon: "Current signal",
        scope: "Regional rainfall screening; example catchment graphs",
        predicts: "Flash-flood screening score",
        model: "Dashboard rainfall rule; graph uses example data",
        score: data.locationWeather.length ? clamp(maxRainCurrent * 6 + maxRain6 * 2.2 + maxRain24 * 1.1 + soil * 0.25) : 0,
        detail: `Rain now ${maxRainCurrent.toFixed(1)} mm; 6h rain ${maxRain6.toFixed(1)} mm; soil moisture avg ${soil.toFixed(0)}%.`,
        issuedAt: weatherIssuedAt,
        target: "Catchments: hill torrents, streams, urban drains",
        Icon: CloudRain,
      },
      {
        id: "urban",
        title: "Urban Flooding",
        horizon: "Current signal",
        scope: "Regional urban screening; example city grids",
        predicts: "Urban flood screening score",
        model: "Dashboard rain and reports rule; graph uses example data",
        score: data.locationWeather.length || data.reports.length ? clamp(maxRain6 * 2.3 + maxRain24 * 0.7 + soil * 0.18 + (data.reports.length > 0 ? 12 : 0)) : 0,
        detail: `Forecast rain ${maxRain6.toFixed(1)} mm in 6h; ${data.reports.length} citizen reports in system.`,
        issuedAt: weatherIssuedAt,
        target: urbanTargetLabel,
        Icon: CloudRain,
      },
      {
        id: "seasonal",
        title: "Seasonal Basin Risk",
        horizon: "Current signal",
        scope: "National screening; example basin graph",
        predicts: "Current national screening score",
        model: "Dashboard rule score; weeks-ahead graph is example data",
        score: data.summary || data.risk || data.locationWeather.length ? clamp(highestRisk * 0.35 + soil * 0.38 + maxRain24 * 0.9) : 0,
        detail: "Uses current risk, soil moisture, and next-day forecast rain; no seasonal data in score.",
        issuedAt: data.nationalRisk?.metadata.generated_at ?? data.risk?.timestamp ?? null,
        target: "National basin summary",
        Icon: Mountain,
      },
      {
        id: "upstream",
        title: "Upstream / Transboundary",
        horizon: "Current signal",
        scope: "Regional discharge-change screening; example downstream graph",
        predicts: "Flow-change watch score",
        model: "Dashboard anomaly rule; graph uses example data",
        score: data.locationRivers.length ? clamp((driestRainSignal ? 18 : 6) + maxPositiveChange / 16 + (hasRisingRiver ? 34 : 0)) : 0,
        detail: `Positive modeled discharge change ${Math.round(maxPositiveChange).toLocaleString()} cumecs/day while local forecast rain signal is ${driestRainSignal ? "low" : "active"}.`,
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
      <div className="predictive-risk-modes" role="tablist" aria-label="Prediction horizon" ref={modeTabs}>
        {([ ["near-term", "Near-Term Screening"], ["ten-year", "10-Year Outlook"] ] as const).map(([id, label]) => (
          <button
            type="button"
            role="tab"
            id={`risk-mode-${id}`}
            aria-controls={`risk-panel-${id}`}
            aria-selected={mode === id}
            tabIndex={mode === id ? 0 : -1}
            key={id}
            onClick={() => selectMode(id)}
            onKeyDown={handleModeKeyDown}
          >{label}</button>
        ))}
      </div>
      <div role="tabpanel" id="risk-panel-near-term" aria-labelledby="risk-mode-near-term" hidden={mode !== "near-term"} tabIndex={0}>
        <div className="predictive-risk-toolbar"><p>Early-stage screening scores and example interval series.</p><button type="button" onClick={() => setShowInputs(true)}><Info size={15} /> Inputs & model</button></div>
        {showInputs && <PredictiveInputsDialog data={data} onClose={() => setShowInputs(false)} />}
        <div className="multiview-shell">
          <div className="multiview-grid">
          {views.map(({ id, title, horizon, scope, predicts, model, score, detail, issuedAt, target, outputPoints, Icon }) => (
            <article className={`multiview-card risk-${riskBand(score)}`} key={id}>
              <div className="multiview-card-head">
                <Icon size={15} />
                <div><strong>{title}</strong><span>{horizon}</span></div>
                <b>{score}/100</b>
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
              <div className="multiview-predicts"><span>Shows</span><strong>{predicts}</strong></div>
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
      </div>
      <div role="tabpanel" id="risk-panel-ten-year" aria-labelledby="risk-mode-ten-year" hidden={mode !== "ten-year"} tabIndex={0}>
        <TenYearRiskOutlook active={mode === "ten-year"} />
      </div>
    </section>
  );
}
