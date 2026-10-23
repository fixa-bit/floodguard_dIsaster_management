import { Activity, AlertTriangle, CloudRain, Info, Mountain, Waves } from "lucide-react";
import { useMemo, useRef, useState, type KeyboardEvent } from "react";

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
  detail: string;
  issuedAt: string | null;
  target: string;
  outputPoints?: string[];
  Icon: typeof Waves;
}

function maxNumber(values: Array<number | null | undefined>) {
  const numbers = values.filter((value): value is number => value !== null && value !== undefined && !Number.isNaN(value));
  return numbers.length > 0 ? Math.max(...numbers) : 0;
}

function average(values: Array<number | null | undefined>) {
  const numbers = values.filter((value): value is number => value !== null && value !== undefined && !Number.isNaN(value));
  return numbers.length > 0 ? numbers.reduce((sum, value) => sum + value, 0) / numbers.length : 0;
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

function RiverineModelFlow() {
  return (
    <div className="riverine-model-flow" aria-label="Riverine model flow">
      <div className="riverine-flow-header">
        <span>Current inputs</span>
      </div>
      <div className="riverine-feature-groups">
        <span>Current risk summary</span>
        <span>Current + next-day discharge</span>
        <span>Rising or warning river status</span>
      </div>
      <div className="riverine-station-table">
        <div><span>Example target</span><span>Horizon</span><span>Graph</span></div>
        <div><strong>Chenab — Marala</strong><span>+24h</span><span>Demo series</span></div>
        <div><strong>Ravi — Jassar</strong><span>+48h</span><span>Demo series</span></div>
      </div>
    </div>
  );
}

function FlashFloodModelFlow() {
  return (
    <div className="flash-flood-model-flow" aria-label="Flash-flood model flow">
      <div className="flash-flow-header">
        <span>Current inputs</span>
      </div>
      <div className="flash-feature-grid">
        <span>Current rainfall</span>
        <span>Forecast rain 6h + 24h</span>
        <span>Mean soil moisture</span>
      </div>
    </div>
  );
}

function UrbanFloodModelFlow() {
  return (
    <div className="urban-flood-model-flow" aria-label="Urban flooding model flow">
      <div className="urban-flow-header">
        <span>Current inputs</span>
      </div>
      <div className="urban-feature-grid">
        <span>Forecast rain 6h + 24h</span>
        <span>Mean soil moisture</span>
        <span>Any citizen report</span>
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
    const maxRain24 = maxNumber(data.locationWeather.map((weather) => weather.forecast_rainfall_next_24h_mm));
    const maxRain6 = maxNumber(data.locationWeather.map((weather) => weather.forecast_rainfall_next_6h_mm));
    const maxRainCurrent = maxNumber(data.locationWeather.map((weather) => weather.rainfall_current_mm));
    const soil = average(data.locationWeather.map((weather) => weather.soil_moisture_percent));
    const maxDischarge = maxNumber(data.locationRivers.map((river) => river.discharge_cumecs));
    const maxForecastDischarge = maxNumber(data.locationRivers.map((river) => river.forecast_discharge_next_24h_cumecs));
    const maxPositiveChange = maxNumber(data.locationRivers.map((river) => Math.max(river.discharge_change_cumecs_per_day ?? 0, 0)));
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
        predicts: "Current and next-day discharge summary",
        model: "Dashboard river inputs; graph uses example data",
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
        predicts: "Rainfall and soil moisture summary",
        model: "Dashboard weather inputs; graph uses example data",
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
        predicts: "Forecast rainfall and citizen report summary",
        model: "Dashboard rain and reports; graph uses example data",
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
        predicts: "Current national risk and weather context",
        model: "Dashboard context; weeks-ahead graph is example data",
        detail: "Current dashboard context only; the example graph is not a seasonal forecast.",
        issuedAt: data.nationalRisk?.metadata.generated_at ?? data.risk?.timestamp ?? null,
        target: "National basin summary",
        Icon: Mountain,
      },
      {
        id: "upstream",
        title: "Upstream / Transboundary",
        horizon: "Current signal",
        scope: "Regional discharge-change screening; example downstream graph",
        predicts: "Discharge change and local rainfall context",
        model: "Dashboard flow and rain inputs; graph uses example data",
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
        <div className="predictive-risk-toolbar"><p>Current flood-related inputs and example interval series.</p><button type="button" onClick={() => setShowInputs(true)}><Info size={15} /> Inputs & model</button></div>
        {showInputs && <PredictiveInputsDialog data={data} onClose={() => setShowInputs(false)} />}
        <div className="multiview-shell">
          <div className="multiview-grid">
          {views.map(({ id, title, horizon, scope, predicts, model, detail, issuedAt, target, outputPoints, Icon }) => {
            const isRiverineMonthly = id === "riverine" && riverineMode === "monthly-marala";
            return <article className={`multiview-card${isRiverineMonthly ? " riverine-monthly-card" : ""}`} key={id}>
              <div className="multiview-card-head">
                <Icon size={15} />
                <div><strong>{isRiverineMonthly ? "Marala Monthly River Flow" : title}</strong><span>{isRiverineMonthly ? "Monthly dataset and outlook" : horizon}</span></div>
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
                <RiverineModelFlow />
              ) : id === "flash" ? (
                <FlashFloodModelFlow />
              ) : id === "urban" ? (
                <UrbanFloodModelFlow />
              ) : null}
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
