import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

import type { DashboardData } from "../hooks/useDashboardData";
import "../predictive-inputs.css";

type CaseId = "riverine" | "flash" | "urban" | "seasonal" | "upstream";
type Dataset = { name: string; fields: string };
type CaseGuide = {
  id: CaseId;
  title: string;
  datasets: Dataset[];
  engineered: string[];
  method: string;
  output: string;
  future: string[];
};

const guides: CaseGuide[] = [
  {
    id: "riverine", title: "Riverine Short-Term",
    datasets: [
      { name: "Dashboard risk summary", fields: "highest_risk_probability; falls back to the selected location's flood_probability" },
      { name: "River responses for configured locations", fields: "discharge_cumecs, forecast_discharge_next_24h_cumecs, status" },
    ],
    engineered: ["Maximum current and next-24-hour modeled discharge across available locations.", "Whether any river has a rising or warning status."],
    method: "Rule score = maximum of current risk × 100, river-status floor (24 or 68), next-day discharge / 35, and current discharge / 38; clipped to 0–100. No XGBoost model runs for this card.",
    output: "A 0–100 screening score. The Trimmu and Balloki interval graph is a separate example series, not a forecast calculated from these inputs.",
    future: ["Collect hourly station discharge, rainfall forecasts, and verified flood thresholds with timestamps.", "Train and test a simple persistence or regression baseline, then compare the experimental XGBoost discharge model against it on real held-out station data.", "Add upstream release and lagged-flow features only when those histories are reliable."],
  },
  {
    id: "flash", title: "Flash Flood",
    datasets: [
      { name: "Weather responses for configured locations", fields: "rainfall_current_mm, forecast_rainfall_next_6h_mm, forecast_rainfall_next_24h_mm, soil_moisture_percent" },
    ],
    engineered: ["Maximum rainfall values across available locations and mean soil moisture.", "A weighted sum of these four signals, clipped to 0–100."],
    method: "Rule score = 6 × current rain + 2.2 × next-6-hour rain + 1.1 × next-day rain + 0.25 × mean soil moisture; clipped to 0–100. No trained flash-flood model or catchment GIS features run on this page.",
    output: "A 0–100 screening score. Catchment interval curves are example data, not measured flood probabilities.",
    future: ["Assemble short-interval rain gauges, catchment outlines, terrain slope, and dated flash-flood events.", "Start with a threshold or logistic-regression baseline; compare LightGBM only after collecting enough labeled examples."],
  },
  {
    id: "urban", title: "Urban Flooding",
    datasets: [
      { name: "Weather responses for configured locations", fields: "forecast_rainfall_next_6h_mm, forecast_rainfall_next_24h_mm, soil_moisture_percent" },
      { name: "Citizen reports", fields: "Total report count; the current formula does not filter by city or waterlogging type" },
    ],
    engineered: ["Maximum forecast rain, mean soil moisture, and a small indicator when any citizen report exists.", "A weighted sum of these signals, clipped to 0–100."],
    method: "Rule score = 2.3 × next-6-hour rain + 0.7 × next-day rain + 0.18 × mean soil moisture + 12 if any citizen report exists; clipped to 0–100. Grid-level drainage, elevation, and land cover are not used.",
    output: "A 0–100 screening score. The city-grid interval curves are example data, not calculated city forecasts.",
    future: ["Collect geolocated waterlogging reports, rain-gauge history, drainage maps, and city elevation data.", "Test a simple rainfall threshold first; compare a small logistic-regression or tree model once labels and geographic validation are available."],
  },
  {
    id: "seasonal", title: "Seasonal Basin Risk",
    datasets: [
      { name: "Dashboard risk summary", fields: "highest_risk_probability; falls back to the selected location's flood_probability" },
      { name: "Weather responses for configured locations", fields: "soil_moisture_percent, forecast_rainfall_next_24h_mm" },
    ],
    engineered: ["Mean soil moisture and maximum next-24-hour rainfall.", "A weighted sum with the current risk indicator, clipped to 0–100."],
    method: "Rule score = 0.35 × current risk percentage + 0.38 × mean soil moisture + 0.9 × next-day rainfall; clipped to 0–100. No seasonal forecast or trained basin model is used.",
    output: "A current national screening score. The weeks-ahead basin graph is example data and should not be interpreted as a seasonal forecast.",
    future: ["Assemble basin-level historical rainfall, streamflow, soil moisture, and seasonal forecast archives.", "Validate a simple seasonal climatology baseline before trying a tree model; consider a sequence model only if the history supports it."],
  },
  {
    id: "upstream", title: "Upstream / Transboundary",
    datasets: [
      { name: "River responses for configured locations", fields: "discharge_change_cumecs_per_day, status" },
      { name: "Weather responses for configured locations", fields: "forecast_rainfall_next_6h_mm, forecast_rainfall_next_24h_mm" },
    ],
    engineered: ["Maximum positive modeled discharge change and any rising or warning river status.", "A low-local-rain flag when both forecast rain maxima are small."],
    method: "Rule score = 18 if local forecast rain is low (otherwise 6), plus positive discharge change / 16, plus 34 if a river is rising or in warning; clipped to 0–100. No upstream gauge anomaly model or transboundary feed is used.",
    output: "A 0–100 watch score. The downstream interval graph is example data, not a predicted upstream surge.",
    future: ["Collect upstream and downstream gauge histories with travel times and release records.", "Start with change thresholds and travel-time baselines; compare Isolation Forest only after reliable upstream observations exist."],
  },
];

function sourceNames(items: Array<{ source: string }>) {
  const names = [...new Set(items.map((item) => item.source).filter(Boolean))];
  return names.length ? names.join(", ") : "No response loaded";
}

export function PredictiveInputsDialog({ data, onClose }: { data: DashboardData; onClose: () => void }) {
  const [selected, setSelected] = useState<CaseId>("riverine");
  const dialog = useRef<HTMLDivElement>(null);
  const guide = guides.find((item) => item.id === selected)!;
  const examples = data.modelForecasts.filter((point) => point.model_case === selected);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialog.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); onClose(); }
      if (event.key !== "Tab") return;
      const buttons = [...(dialog.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? [])];
      if (event.shiftKey && document.activeElement === buttons[0]) { event.preventDefault(); buttons.at(-1)?.focus(); }
      else if (!event.shiftKey && document.activeElement === buttons.at(-1)) { event.preventDefault(); buttons[0]?.focus(); }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => { document.removeEventListener("keydown", onKeyDown); document.body.style.overflow = oldOverflow; previous?.focus(); };
  }, [onClose]);

  return createPortal(<div className="predictive-inputs-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="predictive-inputs-dialog" role="dialog" aria-modal="true" aria-labelledby="predictive-inputs-title" ref={dialog}>
      <header><div><span className="predictive-inputs-eyebrow">Predictive Risk Views</span><h2 id="predictive-inputs-title">Inputs, method & future scope</h2></div><button type="button" aria-label="Close inputs and model" onClick={onClose}><X size={19} /></button></header>
      <div className="predictive-inputs-body">
        <p className="predictive-inputs-notice">This version uses simple dashboard rules for the five scores. The interval graphs use stored example series. Model experiments in the repository do not generate these displayed series.</p>
        <div className="predictive-inputs-tabs" role="tablist" aria-label="Risk category">
          {guides.map((item) => <button key={item.id} type="button" role="tab" aria-selected={selected === item.id} onClick={() => setSelected(item.id)}>{item.title}</button>)}
        </div>
        <section className="predictive-inputs-content" role="tabpanel" aria-label={`${guide.title} inputs and method`}>
          <div className="predictive-inputs-current">
            <h3>{guide.title} <span>Current version</span></h3>
            <h4>Datasets and fields used</h4>
            <ul>{guide.datasets.map((source) => <li key={source.name}><strong>{source.name}</strong><span>{source.fields}</span></li>)}</ul>
            <p className="predictive-inputs-source">{guide.datasets.some((item) => item.name.startsWith("Weather")) && <>Received weather source: {sourceNames(data.locationWeather)}<br /></>}{guide.datasets.some((item) => item.name.startsWith("River")) && <>Received river source: {sourceNames(data.locationRivers)}<br /></>}</p>
            <h4>Engineered features</h4><ul>{guide.engineered.map((item) => <li key={item}>{item}</li>)}</ul>
            <h4>Model or method used now</h4><p>{guide.method}</p>
            <h4>Output shown</h4><p>{guide.output}</p>
            <p className="predictive-inputs-source">Example graph data: {examples.length ? `${examples.length} stored points; demonstration source ${String(examples[0]?.point_metadata.simulation_source ?? "unknown")}.` : "No series loaded."}</p>
          </div>
          <aside className="predictive-inputs-future"><h3>Future scope</h3><ul>{guide.future.map((item) => <li key={item}>{item}</li>)}</ul></aside>
        </section>
      </div>
    </div>
  </div>, document.body);
}
