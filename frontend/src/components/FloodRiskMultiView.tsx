import { Activity, AlertTriangle, CloudRain, Cpu, Info, Mountain, Waves } from "lucide-react";
import { useMemo, useRef, useState, type KeyboardEvent } from "react";

import type { DashboardData } from "../hooks/useDashboardData";
import type { ModelForecastPoint } from "../types/api";
import { formatDateTime } from "../utils/format";
import { PredictiveInputsDialog } from "./PredictiveInputsDialog";
import { TenYearRiskOutlook } from "./TenYearRiskOutlook";
import { MaralaMonthlyTab } from "./MaralaMonthlyTab";
import { MaralaStationForecast } from "./MaralaStationForecast";
import "../ten-year-risk-outlook.css";
import "../near-term-screening.css";

type RiskMode = "near-term" | "ten-year";
type RiverineMode = "daily-gauge" | "monthly-marala";
type ModelStatus = "model" | "trained" | "none";

interface DummyView {
  id: "flash" | "urban" | "seasonal" | "upstream";
  title: string;
  issuedAt: string | null;
  target: string;
  inputs: string;
  Icon: typeof Waves;
}

interface RegisterRow {
  id: string;
  title: string;
  status: ModelStatus;
  statusLabel: string;
  model: string;
  evidence: string;
  graph: string;
}

const REGISTER: RegisterRow[] = [
  {
    id: "riverine", title: "Riverine short-term", status: "model", statusLabel: "Model output",
    model: "Marala station gauge forecast — ridge regression / baseline chosen per lead",
    evidence: "2026 held-out season: +7 d 9.5% lower error than persistence; +1 d tie; +3 d worse",
    graph: "Real model output",
  },
  {
    id: "flash", title: "Flash flood", status: "trained", statusLabel: "Trained · not connected",
    model: "LightGBM, 20 km grid, next-24 h report-onset chance (imported flood_model)",
    evidence: "Test 2022 – Jan 2026: PR-AUC 0.062 vs 0.035 climatology; needs a daily grid input feed",
    graph: "Dummy output",
  },
  {
    id: "urban", title: "Urban flooding", status: "none", statusLabel: "No model",
    model: "No trained urban model or artifact in the project",
    evidence: "—",
    graph: "Dummy output",
  },
  {
    id: "seasonal", title: "Seasonal basin", status: "none", statusLabel: "No near-term model",
    model: "Real Marala monthly outlook exists — see Riverine › Monthly Marala",
    evidence: "Monthly model has its own validation in that tab",
    graph: "Dummy output",
  },
  {
    id: "upstream", title: "Upstream / transboundary", status: "none", statusLabel: "No project model",
    model: "External GloFAS forecasts only — on the Upstream Source Flood Watch page",
    evidence: "—",
    graph: "Dummy output",
  },
];

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

function ModelRegister({ onOpenMonthly }: { onOpenMonthly: () => void }) {
  return (
    <section className="near-term-register" aria-label="Which near-term views use a real model">
      <header>
        <h3>Model register</h3>
        <p>Only one near-term view is backed by a trained model with saved output. Every other graph is dummy output and is marked as such.</p>
      </header>
      <div className="register-table-wrap">
        <table className="register-table">
          <thead><tr><th scope="col">View</th><th scope="col">Status</th><th scope="col">Model in project</th><th scope="col">Validation evidence</th><th scope="col">Graph shows</th></tr></thead>
          <tbody>
            {REGISTER.map((row) => (
              <tr key={row.id} className={`register-${row.status}`}>
                <th scope="row">{row.title}</th>
                <td><span className={`register-pill pill-${row.status}`}>{row.statusLabel}</span></td>
                <td>{row.id === "seasonal" ? <>Real Marala monthly outlook exists — <button type="button" className="register-link" onClick={onOpenMonthly}>open Riverine › Monthly Marala</button></> : row.model}</td>
                <td>{row.evidence}</td>
                <td className={row.status === "model" ? "graph-real" : "graph-dummy"}>{row.graph}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function DummyForecastGraph({
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
        <span>No dummy series loaded</span>
      </div>
    );
  }
  const unit = series[0].value_unit;
  const percentLike = unit.includes("percent");
  const rawMax = Math.max(...series.map((point) => point.value), 1);
  const tickStep = 10 ** Math.floor(Math.log10(rawMax)) / 2;
  const maxValue = percentLike ? 100 : Math.ceil(rawMax * 1.1 / tickStep) * tickStep;
  const width = 640;
  const height = 270;
  const left = 70, right = 30, top = 35, bottom = 55;
  const maxHorizon = Math.max(...series.map(point => point.horizon_hours), 1);
  const xFor = (hours: number) => left + hours / maxHorizon * (width - left - right);
  const yFor = (value: number) => top + (1 - value / Math.max(maxValue, 1)) * (height - top - bottom);
  const unitLabel = unit === "cumecs" ? "m³/s" : unit.replaceAll("_", " ");
  const axisLabel = unit === "cumecs" ? "Discharge (m³/s)" : unitLabel;
  const path = series.map((point, index) => `${index === 0 ? "M" : "L"} ${xFor(point.horizon_hours).toFixed(2)} ${yFor(point.value).toFixed(2)}`).join(" ");
  const latest = series[series.length - 1];

  return (
    <div className="forecast-graph dummy-graph">
      <div className="dummy-banner" role="note"><AlertTriangle size={12} /> Dummy output — not produced by any model. Shape and values are placeholders.</div>
      {targets.length > 1 && <div className="forecast-target-tabs" aria-label="Dummy series selector">
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
      </div>}
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Dummy output graph for ${latest.target_name}; not a forecast`}>
        <defs>
          <pattern id="dummy-hatch" width="10" height="10" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="10" className="dummy-hatch-line" />
          </pattern>
        </defs>
        <rect x={left} y={top} width={width - left - right} height={height - top - bottom} fill="url(#dummy-hatch)" />
        <text className="dummy-watermark" x={left + (width - left - right) / 2} y={top + (height - top - bottom) / 2} textAnchor="middle" dominantBaseline="middle" transform={`rotate(-12 ${left + (width - left - right) / 2} ${top + (height - top - bottom) / 2})`}>DUMMY OUTPUT</text>
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
        <path className="dummy-line" d={path} />
        {series.map((point) => (
          <circle className="dummy-dot" cx={xFor(point.horizon_hours)} cy={yFor(point.value)} key={`${point.target_id}-${point.horizon_hours}`} r="3.5">
            <title>Dummy {formatHorizon(point.horizon_hours)}: {point.value.toLocaleString()} {unitLabel} — placeholder, not a forecast</title>
          </circle>
        ))}
      </svg>
    </div>
  );
}

function FlashFloodModelFacts() {
  return (
    <div className="trained-model-facts" aria-label="Trained flash-flood model in the project">
      <strong><Cpu size={13} /> Trained model in the project — not yet connected</strong>
      <p>LightGBM ranks every 20 km cell in Pakistan by the chance a flash-flood report starts there in the next 24 h. Labels are Groundsource news reports, so treat it as a ranking, not a probability of flooding.</p>
      <dl>
        <div><dt>PR-AUC (test)</dt><dd>0.062 <small>vs 0.035 climatology</small></dd></div>
        <div><dt>Daily top 5% of cells</dt><dd>40% <small>of onsets caught</small></dd></div>
        <div><dt>Chenab districts</dt><dd>0.070 <small>vs 0.048</small></dd></div>
      </dl>
      <p className="trained-model-gap">To connect: a daily IMERG rain + ERA5-Land grid feed for its inputs. Until then the graph above is dummy output.</p>
    </div>
  );
}

export function FloodRiskMultiView({ data }: { data: DashboardData }) {
  const [mode, setMode] = useState<RiskMode>("near-term");
  const modeTabs = useRef<HTMLDivElement>(null);
  const riverineCard = useRef<HTMLElement>(null);
  const [selectedTargets, setSelectedTargets] = useState<Record<string, string>>({});
  const [riverineMode, setRiverineMode] = useState<RiverineMode>("daily-gauge");
  const [showInputs, setShowInputs] = useState(false);
  function selectMode(nextMode: RiskMode) {
    setShowInputs(false);
    setMode(nextMode);
  }
  function openMonthly() {
    setRiverineMode("monthly-marala");
    riverineCard.current?.scrollIntoView({ behavior: "smooth", block: "start" });
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
  const dummyViews = useMemo<DummyView[]>(() => {
    const maxRain24 = maxNumber(data.locationWeather.map((weather) => weather.forecast_rainfall_next_24h_mm));
    const maxRain6 = maxNumber(data.locationWeather.map((weather) => weather.forecast_rainfall_next_6h_mm));
    const maxRainCurrent = maxNumber(data.locationWeather.map((weather) => weather.rainfall_current_mm));
    const soil = average(data.locationWeather.map((weather) => weather.soil_moisture_percent));
    const maxPositiveChange = maxNumber(data.locationRivers.map((river) => Math.max(river.discharge_change_cumecs_per_day ?? 0, 0)));
    const driestRainSignal = data.locationWeather.length > 0 && maxRain24 <= 2 && maxRain6 <= 1;
    const riverIssuedAt = data.locationRivers[0]?.official_recording_time ?? data.river?.official_recording_time ?? data.locationRivers[0]?.timestamp ?? data.river?.timestamp ?? null;
    const weatherIssuedAt = data.locationWeather[0]?.timestamp ?? data.weather?.timestamp ?? null;
    return [
      {
        id: "flash", title: "Flash Flood", issuedAt: weatherIssuedAt,
        target: "Dummy targets: hill torrents, Rawalpindi and Islamabad streams",
        inputs: `Rain now ${maxRainCurrent.toFixed(1)} mm; next 6 h ${maxRain6.toFixed(1)} mm; mean soil moisture ${soil.toFixed(0)}%.`,
        Icon: CloudRain,
      },
      {
        id: "urban", title: "Urban Flooding", issuedAt: weatherIssuedAt,
        target: "Dummy targets: Islamabad / Rawalpindi / Lahore grid cells",
        inputs: `Forecast rain ${maxRain6.toFixed(1)} mm in 6 h; ${data.reports.length} citizen reports in the system.`,
        Icon: CloudRain,
      },
      {
        id: "seasonal", title: "Seasonal Basin Risk", issuedAt: data.nationalRisk?.metadata.generated_at ?? data.risk?.timestamp ?? null,
        target: "Dummy target: national basin summary",
        inputs: "No near-term seasonal model. The real monthly Marala model is under Riverine › Monthly Marala.",
        Icon: Mountain,
      },
      {
        id: "upstream", title: "Upstream / Transboundary", issuedAt: riverIssuedAt,
        target: "Dummy target: downstream river reaches",
        inputs: `Largest rise in modeled discharge ${Math.round(maxPositiveChange).toLocaleString()} m³/s per day; local forecast rain is ${driestRainSignal ? "low" : "active"}.`,
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
        <div className="predictive-risk-toolbar"><p>Riverine shows real model output. Every other graph is dummy output, marked on the graph.</p><button type="button" onClick={() => setShowInputs(true)}><Info size={15} /> Inputs & model</button></div>
        {showInputs && <PredictiveInputsDialog data={data} onClose={() => setShowInputs(false)} />}
        <ModelRegister onOpenMonthly={openMonthly} />
        <div className="multiview-shell">
          <div className="multiview-grid">
            <article className={`multiview-card near-term-real-card${riverineMode === "monthly-marala" ? " riverine-monthly-card" : ""}`} ref={riverineCard}>
              <div className="multiview-card-head">
                <Waves size={15} />
                <div>
                  <strong>{riverineMode === "monthly-marala" ? "Marala Monthly River Flow" : "Riverine Short-Term · Chenab at Marala"}</strong>
                  <span>{riverineMode === "monthly-marala" ? "Monthly dataset and outlook" : "Measured inflow forecast, 1 · 3 · 7 days ahead"}</span>
                </div>
                <span className="card-status pill-model">Model output · research only</span>
              </div>
              <div className="riverine-case-tabs" role="tablist" aria-label="Riverine forecast view">
                {([ ["daily-gauge", "Daily gauge forecast"], ["monthly-marala", "Monthly Marala"] ] as const).map(([tab, label]) => (
                  <button type="button" role="tab" id={`riverine-tab-${tab}`} aria-controls={`riverine-panel-${tab}`} aria-selected={riverineMode === tab} tabIndex={riverineMode === tab ? 0 : -1} key={tab} onClick={() => setRiverineMode(tab)}>{label}</button>
                ))}
              </div>
              <div role="tabpanel" id={`riverine-panel-${riverineMode}`} aria-labelledby={`riverine-tab-${riverineMode}`} className="riverine-case-panel">
                {riverineMode === "monthly-marala" ? <MaralaMonthlyTab /> : <MaralaStationForecast />}
              </div>
            </article>

            <div className="near-term-dummy-heading">
              <AlertTriangle size={14} />
              <div><strong>Dummy-output views</strong><span>No project model produces these graphs yet. The “current inputs” lines below each graph are live dashboard data.</span></div>
            </div>

            {dummyViews.map(({ id, title, issuedAt, target, inputs, Icon }) => (
              <article className="multiview-card near-term-dummy-card" key={id}>
                <div className="multiview-card-head">
                  <Icon size={15} />
                  <div><strong>{title}</strong><span>{target}</span></div>
                  <span className={`card-status ${id === "flash" ? "pill-trained" : "pill-none"}`}>{id === "flash" ? "Trained · not connected" : "No model"}</span>
                </div>
                <DummyForecastGraph
                  points={forecastPointsByCase[id] ?? []}
                  selectedTarget={selectedTargets[id]}
                  onTargetChange={(targetId) => setSelectedTargets((current) => ({ ...current, [id]: targetId }))}
                />
                {id === "flash" && <FlashFloodModelFacts />}
                <div className="dummy-current-inputs">
                  <span>Current inputs (live) · {formatIssuedAt(issuedAt)}</span>
                  <p>{inputs}</p>
                  {id === "seasonal" && <button type="button" className="register-link" onClick={openMonthly}>Open the Monthly Marala model</button>}
                </div>
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
