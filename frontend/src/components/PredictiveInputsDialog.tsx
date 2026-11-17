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
      { name: "FFD Marala bulletins (models/marala_station_forecast)", fields: "Measured inflow and outflow at 06:00 PKT, 322 days from 2024-07-18 to 2026-10-15, each with source URL and SHA-256" },
    ],
    engineered: ["Log inflow and its 1-, 2-, 3- and 7-day lags and changes", "3- and 7-day mean, spread and maximum; outflow/inflow ratio; season sine and cosine"],
    method: "Marala station gauge forecast v1. Per lead, candidates (persistence, trends, training median, ridge, XGBoost) were fitted on 2024, chosen on 2025 and tested once on 2026. The +1 d and +7 d models are ridge regressions on log change; the +3 d choice is the training median, which lost to persistence on the 2026 test.",
    output: "Real model output: inflow at Marala 1, 3 and 7 days after the latest reading the model was run on, with ±1 held-out RMSE, plus the full 2026 held-out comparison. Research only, not deployment eligible.",
    future: ["Re-run the saved model on each new FFD bulletin so the forecast stays current.", "Add observed upstream Akhnur flow, reservoir releases and archived rainfall forecasts as inputs.", "Collect more year-round seasons before claiming rare-flood skill; compare the imported 10- to 30-day LSTM models on the same measured target."],
  },
  {
    id: "flash", title: "Flash Flood",
    datasets: [
      { name: "Weather responses for configured locations", fields: "rainfall_current_mm, forecast_rainfall_next_6h_mm, forecast_rainfall_next_24h_mm, soil_moisture_percent" },
    ],
    engineered: ["Maximum current and forecast rainfall, and mean soil moisture across available locations."],
    method: "Summarizes rainfall and soil moisture from dashboard responses. A trained LightGBM 20 km grid model (imported flood_model, next-24 h report-onset chance) exists in the project but is not connected to live inputs.",
    output: "Rainfall and soil moisture summary. The graph is dummy output, not a model result.",
    future: ["Build a daily IMERG rainfall and ERA5-Land grid feed matching the LightGBM inputs, then show its daily top-5% cells on the map.", "Use archived rainfall forecasts to measure how much of its test skill (PR-AUC 0.062 vs 0.035) survives real forecast error."],
  },
  {
    id: "urban", title: "Urban Flooding",
    datasets: [
      { name: "Weather responses for configured locations", fields: "forecast_rainfall_next_6h_mm, forecast_rainfall_next_24h_mm, soil_moisture_percent" },
      { name: "Citizen reports", fields: "Total report count; the current formula does not filter by city or waterlogging type" },
    ],
    engineered: ["Maximum next-6-hour forecast rainfall and total citizen report count."],
    method: "Summarizes forecast rainfall and citizen reports. Grid-level drainage, elevation, and land cover are not used.",
    output: "Forecast rainfall and report count. City-grid interval curves are example data, not calculated city forecasts.",
    future: ["Collect geolocated waterlogging reports, rain-gauge history, drainage maps, and city elevation data.", "Test a simple rainfall threshold first; compare a small logistic-regression or tree model once labels and geographic validation are available."],
  },
  {
    id: "seasonal", title: "Seasonal Basin Risk",
    datasets: [
      { name: "Dashboard risk summary", fields: "highest_risk_probability; falls back to the selected location's flood_probability" },
      { name: "Weather responses for configured locations", fields: "soil_moisture_percent, forecast_rainfall_next_24h_mm" },
    ],
    engineered: ["No seasonal features are calculated in this view."],
    method: "Displays current dashboard context alongside an example basin graph. No seasonal forecast or trained basin model is used.",
    output: "An example weeks-ahead basin graph, which should not be interpreted as a seasonal forecast.",
    future: ["Assemble basin-level historical rainfall, streamflow, soil moisture, and seasonal forecast archives.", "Validate a simple seasonal climatology baseline before trying a tree model; consider a sequence model only if the history supports it."],
  },
  {
    id: "upstream", title: "Upstream / Transboundary",
    datasets: [
      { name: "River responses for configured locations", fields: "discharge_change_cumecs_per_day, status" },
      { name: "Weather responses for configured locations", fields: "forecast_rainfall_next_6h_mm, forecast_rainfall_next_24h_mm" },
    ],
    engineered: ["Maximum positive modeled discharge change and a low-local-rain flag from forecast rainfall."],
    method: "Summarizes modeled discharge changes alongside local forecast rain. No upstream gauge anomaly model or transboundary feed is used.",
    output: "Discharge change and rainfall context. The downstream interval graph is example data, not a predicted upstream surge.",
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
        <p className="predictive-inputs-notice">Only the Riverine view shows real model output (Marala station gauge forecast). All other graphs are dummy output; their current-input summaries are live dashboard data.</p>
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
            <p className="predictive-inputs-source">{selected === "riverine" ? "Graph data: saved outputs of models/marala_station_forecast (latest sealed run)." : `Dummy graph data: ${examples.length ? `${examples.length} stored points from ${String(examples[0]?.point_metadata.simulation_source ?? "unknown")}.` : "no series loaded."}`}</p>
          </div>
          <aside className="predictive-inputs-future"><h3>Future scope</h3><ul>{guide.future.map((item) => <li key={item}>{item}</li>)}</ul></aside>
        </section>
      </div>
    </div>
  </div>, document.body);
}
