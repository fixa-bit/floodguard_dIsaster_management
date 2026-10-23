import { Activity, AlertTriangle, CloudRain, Info, Mountain, Waves } from "lucide-react";
import { useMemo, useRef, useState, type KeyboardEvent } from "react";

import { LOCATIONS } from "../config";
import type { DashboardData } from "../hooks/useDashboardData";
import type { ModelForecastPoint } from "../types/api";
import { formatDateTime } from "../utils/format";
import { PredictiveInputsDialog } from "./PredictiveInputsDialog";
import { TenYearRiskOutlook } from "./TenYearRiskOutlook";
import { MaralaMonthlyTab } from "./MaralaMonthlyTab";
import "../ten-year-risk-outlook.css";

type RiskMode = "near-term" | "ten-year";
type RiverineMode = "short-term" | "monthly-marala";

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
  const targetLabel = (point: ModelForecastPoint) => {
    if (point.model_case === "riverine") {
      if (point.target_id === "trimmu") return "Chenab — Marala";
      if (point.target_id === "balloki") return "Ravi — Jassar";
    }
    return point.target_name;
  };
  const targets = Array.from(new Map(points.map((point) => [point.target_id, targetLabel(point)])).entries());
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
  const rawMax = Math.max(...series.map((point) => point.value), 1);
  const tickStep = 10 ** Math.floor(Math.log10(rawMax)) / 2;
  const maxValue = percentLike ? 100 : Math.ceil(rawMax * 1.1 / tickStep) * tickStep;
  const minValue = 0;
  const valueRange = Math.max(maxValue - minValue, 1);
  const width = 640;
  const height = 270;
  const left = 70, right = 30, top = 35, bottom = 55;
  const maxHorizon = Math.max(...series.map(point => point.horizon_hours), 1);
  const xFor = (hours: number) => left + hours / maxHorizon * (width - left - right);
  const yFor = (value: number) => top + (1 - (value - minValue) / valueRange) * (height - top - bottom);
  const axisLabel = unit === "cumecs" ? "Discharge (m³/s)" : unit.replaceAll("_", " ");
  const path = series
    .map((point, index) => {
      const x = xFor(point.horizon_hours);
      const y = yFor(point.value);
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
  const latest = series[series.length - 1];
  const demonstration = series.some((point) => point.point_metadata.simulation_source === "dummy_model_forecast_v3");

  return (
    <div className="forecast-graph">
      {demonstration && <span className="forecast-example-label">Demonstration data · illustrative values</span>}
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
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${targetLabel(latest)} forecast interval graph`}>
        <text x={left} y="16" className="forecast-axis-title">{axisLabel}</text>
        {[0, 1, 2, 3, 4].map(step => {
          const value = maxValue * step / 4;
          return <g key={step}><line x1={left} x2={width - right} y1={yFor(value)} y2={yFor(value)} className="forecast-grid-line" /><text x={left - 10} y={yFor(value) + 4} textAnchor="end">{value.toLocaleString(undefined, { maximumFractionDigits: 1 })}</text></g>;
        })}
        {[0, 1, 2, 3, 4].map(step => {
          const hours = maxHorizon * step / 4;
          return <text key={step} x={xFor(hours)} y={height - bottom + 23} textAnchor="middle">{formatHorizon(hours)}</text>;
        })}
        <text x={left + (width - left - right) / 2} y={height - 5} textAnchor="middle">Hours after issue time</text>
        <path d={path} />
        {series.map((point) => {
          const x = xFor(point.horizon_hours);
          const y = yFor(point.value);
          return <circle cx={x} cy={y} key={`${point.target_id}-${point.horizon_hours}`} r="3.5"><title>{formatHorizon(point.horizon_hours)}: {point.value.toLocaleString()} {unit === "cumecs" ? "m³/s" : unit.replaceAll("_", " ")}</title></circle>;
        })}
      </svg>
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
      <p className="screening-score-explanation">{score}/100 = {riskBand(score)} screening level. This rule score is separate from the graph; it is not a flood probability.</p>
      <details className="screening-score-details"><summary>How this score is calculated</summary><p>Take the highest of: current risk summary × 100; river-status score (68 if rising or in warning, otherwise 24); next-day discharge ÷ 35; and current discharge ÷ 38. Round and limit to 0–100. Bands: Low 0–39, Medium 40–69, High 70–100. These are screening rules, not calibrated flood thresholds.</p></details>
      <div className="riverine-station-table">
        <div><span>Example target</span><span>Horizon</span><span>Graph</span></div>
        <div><strong>Chenab — Marala</strong><span>+24h</span><span>Demo series</span></div>
        <div><strong>Ravi — Jassar</strong><span>+48h</span><span>Demo series</span></div>
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
  const [riverineMode, setRiverineMode] = useState<RiverineMode>("short-term");
  const [showInputs, setShowInputs] = useState(false);
  function selectMode(nextMode: RiskMode) {
    setShowInputs(false);
    setMode(nextMode);
  }
  function handleModeKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const modes: RiskMode[] = ["near-term", "ten-year"];
    const index = modes.indexOf(mode);
    const nextMode = event.key === "Home" ? modes[0]
      : event.key === "End" ? modes[modes.length - 1]
      : event.key === "ArrowLeft" ? modes[(index + modes.length - 1) % modes.length]
      : event.key === "ArrowRight" ? modes[(index + 1) % modes.length]
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
        scope: "Regional river screening; example graphs for Chenab — Marala and Ravi — Jassar",
        predicts: "River risk screening score",
        model: "Dashboard rule score; graph uses example data",
        score: data.locationRivers.length || data.summary || data.risk ? clamp(Math.max(highestRisk, hasRisingRiver ? 68 : 24, maxForecastDischarge / 35, maxDischarge / 38)) : 0,
        detail: `Max discharge ${Math.round(maxDischarge).toLocaleString()} cumecs; forecast ${Math.round(maxForecastDischarge).toLocaleString()} cumecs.`,
        issuedAt: riverIssuedAt,
        target: "Stations: Chenab — Marala +24h; Ravi — Jassar +48h",
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
            data-tour-target={id === "near-term" ? "risk-near-term" : "risk-ten-year"}
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
          {views.map(({ id, title, horizon, scope, predicts, model, score, detail, issuedAt, target, outputPoints, Icon }) => {
            const isRiverineMonthly = id === "riverine" && riverineMode === "monthly-marala";
            return <article className={`multiview-card risk-${riskBand(score)}${isRiverineMonthly ? " riverine-monthly-card" : ""}`} key={id}>
              <div className="multiview-card-head">
                <Icon size={15} />
                <div><strong>{isRiverineMonthly ? "Marala Monthly River Flow" : title}</strong><span>{isRiverineMonthly ? "Monthly dataset and outlook" : horizon}</span></div>
                {!isRiverineMonthly && <b className="screening-score-badge"><span>Screening score</span>{score}/100</b>}
              </div>
              {id === "riverine" && <div className="riverine-case-tabs" role="tablist" aria-label="Riverine forecast view">
                {([ ["short-term", "Short-term screening"], ["monthly-marala", "Monthly Marala"] ] as const).map(([tab, label]) => (
                  <button type="button" role="tab" id={`riverine-tab-${tab}`} aria-controls={`riverine-panel-${tab}`} aria-selected={riverineMode === tab} tabIndex={riverineMode === tab ? 0 : -1} key={tab} onClick={() => setRiverineMode(tab)}>{label}</button>
                ))}
              </div>}
              {isRiverineMonthly ? <div role="tabpanel" id="riverine-panel-monthly-marala" aria-labelledby="riverine-tab-monthly-marala" className="riverine-case-panel"><MaralaMonthlyTab /></div> : <div role={id === "riverine" ? "tabpanel" : undefined} id={id === "riverine" ? "riverine-panel-short-term" : undefined} aria-labelledby={id === "riverine" ? "riverine-tab-short-term" : undefined} className="riverine-case-panel">
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
              </div>}
            </article>
          })}
          </div>
        </div>
      </div>
      <div role="tabpanel" id="risk-panel-ten-year" aria-labelledby="risk-mode-ten-year" hidden={mode !== "ten-year"} tabIndex={0}>
        <TenYearRiskOutlook active={mode === "ten-year"} />
      </div>
    </section>
  );
}
