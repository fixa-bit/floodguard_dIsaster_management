import { Info, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

export type ModelKind = "AI" | "Climate AI" | "Physics-based" | "Hybrid physics + AI" | "Statistical" | "Baseline";
export interface ModelInfo { name: string; kind: ModelKind; technique: string; intro: string[] }

/** One entry per model shown in the Riverine Forecast tab. Intros are written for non-specialists. */
export const MODEL_INFO: Record<string, ModelInfo> = {
  gauge: {
    name: "Gauge model", kind: "Statistical", technique: "Ridge regression and XGBoost on gauge readings",
    intro: [
      "Learns from Marala’s daily 06:00 FFD inflow and outflow readings (2024–2026).",
      "From the latest readings and how fast they are changing, it estimates inflow 1, 3 and 7 days ahead.",
      "Five candidate models are ranked by their error on 2025 data; all five are shown as a range.",
      "On 2026 readings it beat “no change” by about 10% at 7 days, matched it at 1 day and was worse at 3 days.",
      "It reruns automatically whenever FFD posts a new reading.",
    ],
  },
  glofas: {
    name: "GloFAS", kind: "Physics-based", technique: "Copernicus Global Flood Awareness System (LISFLOOD)",
    intro: [
      "The European Union’s global flood forecasting system, run by Copernicus every day.",
      "A physics-based river model (LISFLOOD) routes forecast rain and snowmelt through every river on a ~5 km grid.",
      "We read the grid cell nearest Marala through the Open-Meteo flood service, out to 30 days.",
      "It is not tuned to the Marala gauge: over 2024–2026 it showed about 42% less water than was measured.",
      "Best used for the direction of change, not exact numbers.",
    ],
  },
  tft_seasonal: {
    name: "Temporal Fusion Transformer", kind: "AI", technique: "Deep learning, 180-day daily forecast",
    intro: [
      "A deep-learning network built for long, multi-step forecasts, with attention layers that show what it relies on.",
      "It reads a year of catchment rain, snow, temperature and measured flow, then predicts each of the next 180 days.",
      "It first learned from 36 years of simulated GloFAS flow, then was fine-tuned on measured Marala inflow (2016–2021).",
      "Three copies trained from different random starts are averaged; the 10–90% range is calibrated so about 8 in 10 days fall inside.",
      "On 2024–2026 it matched, but did not beat, a normal-year guess.",
    ],
  },
  ridge: {
    name: "Seasonal-average model", kind: "Statistical", technique: "Ridge regression",
    intro: [
      "A regularised linear regression that predicts the average flow over the next 90 or 180 days.",
      "It starts from the normal flow for the month and learns an up or down correction from recent flow, rain, snow and temperature.",
      "Trained on measured Marala flow 2016–2023.",
      "Tested one year at a time on 2020–2024, it beat the normal-season average by 7–8%.",
      "Simple models like this are hard to beat when the measured record is short.",
    ],
  },
  tft_climate: {
    name: "TFT + 8 climate models", kind: "Climate AI", technique: "Temporal Fusion Transformer driven by CMIP6 climate models",
    intro: [
      "The same Temporal Fusion Transformer, trained in a mode that needs only rain and temperature, so it can run on climate-model output.",
      "Rain and temperature from 8 CMIP6 global climate models (NASA NEX-GDDP) are bias-corrected to match observed catchment weather.",
      "The network is run for 1986–2014 and 2026–2040 under a medium (SSP2-4.5) and a high (SSP5-8.5) emission scenario.",
      "Changes are measured against each climate model’s own past run, which cancels most of its bias.",
      "Assumes upstream dams and water use stay as in the past; glacier change is not modelled separately.",
    ],
  },
  peak_model: {
    name: "Flood-peak model", kind: "Statistical", technique: "Censored log-normal regression",
    intro: [
      "Links the heaviest 3-day monsoon rainfall over the catchment to that year’s highest flood peak.",
      "Fitted on 1980–2016 Pakistan Meteorological Department flood records; years with no listed flood count as below 200,000 cusecs.",
      "It gives the chance of reaching each official FFD flood class rather than one number.",
      "Its flood odds were about 30% more accurate than the historical base rate, and the 2025 flood fell inside its range.",
      "Run on every simulated year of the 8 climate models, it gives flood odds for 2026–2040.",
    ],
  },
  cmip6: {
    name: "8 CMIP6 climate models", kind: "Physics-based", technique: "NASA NEX-GDDP-CMIP6 downscaled global climate models",
    intro: [
      "Global climate models simulate the atmosphere and oceans from the laws of physics; CMIP6 is the set used by the IPCC.",
      "NASA’s NEX-GDDP dataset downscales 8 of them (ACCESS-CM2, CNRM-CM6-1, EC-Earth3, GFDL-ESM4, MIROC6, MPI-ESM1-2-HR, MRI-ESM2-0, NorESM2-MM) to about 25 km.",
      "Their catchment rain and temperature are bias-corrected to match observed ERA5-Land weather for 1985–2014.",
      "Using 8 models shows the spread of possible futures rather than one guess.",
    ],
  },
  normal: {
    name: "Normal range", kind: "Baseline", technique: "Observed climatology, 2016–2025",
    intro: [
      "Not a model: the flow Marala usually carries on the same dates.",
      "For each calendar day it takes measured inflow within ±15 days in 2016–2025.",
      "The band is the 10th to 90th percentile; the dashed line is the median.",
      "It is the yardstick for ‘above normal’ and ‘below normal’ throughout this page.",
    ],
  },

  // ---- short-range models replayed on 2022–2024 floods
  persistence: {
    name: "Persistence", kind: "Baseline", technique: "Tomorrow equals today",
    intro: [
      "The simplest possible forecast: flow stays at the last measured value.",
      "It needs no training and is the first yardstick every model must beat.",
      "It is hard to beat one or two days ahead but cannot see a flood coming.",
      "Shown so the trained models can be judged against it.",
    ],
  },
  climatology: {
    name: "Climatology", kind: "Baseline", technique: "Average flow for the date",
    intro: [
      "Predicts the average flow seen on the same calendar date in the training years (2016–2020).",
      "It knows the season but nothing about this year’s weather or river state.",
      "A useful yardstick at long lead times, where weather is hard to foresee.",
      "A trained model that cannot beat it adds no information.",
    ],
  },
  gradient_boosting: {
    name: "Gradient boosting", kind: "Statistical", technique: "Gradient-boosted decision trees",
    intro: [
      "A machine-learning method that combines hundreds of small decision trees, each correcting the last.",
      "It uses recent flow plus catchment rain, temperature and snow as features, one model per lead day.",
      "Fast, transparent about which inputs matter, and a strong classic baseline.",
      "Trained on 2016–2020, chosen on 2021, tested on 2022–2024.",
    ],
  },
  lstm: {
    name: "Original LSTM", kind: "AI", technique: "Hindcast-forecast LSTM neural network",
    intro: [
      "An LSTM is a neural network with memory, widely used in hydrology because it can track snow and soil water over months.",
      "A ‘hindcast’ LSTM reads the past 365 days of weather and snow; a ‘forecast’ LSTM then steps through the next 10 days of weather.",
      "It predicts flow for each day with an uncertainty range.",
      "This was the project’s first deep-learning model for Marala and the reference for later variants.",
    ],
  },
  lstm_two_input: {
    name: "Two-input LSTM", kind: "AI", technique: "Hindcast-forecast LSTM trained from scratch",
    intro: [
      "The same hindcast-forecast LSTM design, trained only on Marala data.",
      "It is the matched ‘from scratch’ partner of the 8-basin pretrained LSTM, so the benefit of pretraining can be measured.",
      "Inputs are past and future catchment weather and snow.",
      "Trained on 2016–2020, chosen on 2021, tested on 2022–2024.",
    ],
  },
  lstm_past_flow: {
    name: "Past-flow + weather LSTM", kind: "AI", technique: "LSTM with measured flow history",
    intro: [
      "An LSTM that also sees the measured river flow up to the forecast day, not just weather.",
      "Knowing where the river is today makes the first few days much more accurate.",
      "It has the best overall fit of the 10-day models but is cautious about flagging floods.",
      "Trained on 2016–2020, chosen on 2021, tested on 2022–2024.",
    ],
  },
  lstm_boost_ensemble: {
    name: "LSTM + boosting ensemble", kind: "AI", technique: "Average of an LSTM and gradient boosting",
    intro: [
      "Blends the deep-learning LSTM with the gradient-boosting model.",
      "Averaging different kinds of model usually cancels part of each one’s errors.",
      "It is steadier than either model alone in normal flows.",
      "Trained and tested on the same years as its two members.",
    ],
  },
  multibasin_lstm: {
    name: "8-basin pretrained LSTM", kind: "AI", technique: "Transfer learning from 8 snow-fed US rivers",
    intro: [
      "An LSTM first trained on eight snow-fed river basins in the United States (CAMELS-US data).",
      "It is then fine-tuned on Marala, so it starts with general knowledge of snowmelt rivers.",
      "Transfer learning like this helps when the local record is short.",
      "It caught 77% of high-flow days 10 days ahead in the replay, with more false alarms.",
    ],
  },
  global_lstm: {
    name: "Global pretrained LSTM", kind: "AI", technique: "Published global LSTM fine-tuned on Marala",
    intro: [
      "A published research LSTM pretrained on about 6,400 river basins worldwide (Caravan dataset).",
      "Its original weights were loaded and fine-tuned on Marala data for 10-day forecasting.",
      "It brings knowledge of many climates and river types to a short local record.",
      "Among the most accurate 10-day models overall in the replay.",
    ],
  },
  seq2seq_15: {
    name: "Seq2seq LSTM (15-day)", kind: "AI", technique: "Encoder-decoder LSTM",
    intro: [
      "An encoder LSTM summarises 365 days of past weather and snow; a decoder LSTM then writes out all 15 forecast days in one go.",
      "Predicting the whole horizon at once avoids errors piling up day by day.",
      "Trained from scratch on Marala data with five uncertainty levels per day.",
      "It caught about 80% of high-flow days 10 days ahead, the best of the 10–15 day models.",
    ],
  },
  seq2seq_15_ft: {
    name: "Seq2seq LSTM fine-tuned (15-day)", kind: "AI", technique: "Encoder-decoder LSTM with transfer learning",
    intro: [
      "The same 15-day encoder-decoder design, started from the 8-basin pretrained weights and then fine-tuned on Marala.",
      "It outputs all 15 days and an uncertainty range in one pass.",
      "Its flood detection matches the scratch version, with slightly better accuracy on high-flow days.",
      "Trained on 2016–2020, chosen on 2021, tested on 2022–2024.",
    ],
  },
  seq2seq_30: {
    name: "Seq2seq LSTM ensemble (30-day)", kind: "AI", technique: "Encoder-decoder LSTM, extended to 30 days",
    intro: [
      "The fine-tuned 15-day encoder-decoder extended to forecast 30 days.",
      "Several trained copies are averaged to make the result steadier.",
      "Longer leads lean more on season and snowpack than on recent weather.",
      "Trained on 2016–2020, chosen on 2021, tested on 2022–2024.",
    ],
  },
  hf_lstm_30: {
    name: "Weather-only LSTM (30-day)", kind: "AI", technique: "Hindcast-forecast LSTM, 30-day",
    intro: [
      "A hindcast-forecast LSTM that predicts 30 days using only weather and snow, no measured flow.",
      "Because it never sees gauge data as input, it still works when readings are missing.",
      "It is the starting point for the other 30-day LSTM variants.",
      "Trained on 2016–2020, chosen on 2021, tested on 2022–2024.",
    ],
  },
  hf_lstm_pastq_30: {
    name: "Past-flow LSTM (30-day)", kind: "AI", technique: "Hindcast-forecast LSTM with measured flow, 30-day",
    intro: [
      "The 30-day weather LSTM with measured flow up to the forecast day added as an input.",
      "Flow history mostly helps the first week; by 30 days the gain is small.",
      "Otherwise identical to the weather-only version so the effect can be measured.",
      "Trained on 2016–2020, chosen on 2021, tested on 2022–2024.",
    ],
  },
  clim_residual_30: {
    name: "Climatology-residual LSTM ensemble", kind: "AI", technique: "LSTM that corrects the normal seasonal flow",
    intro: [
      "Starts from the river’s usual flow for that time of year, then learns how much to raise or lower it.",
      "The correction comes from recent weather, snow and river conditions.",
      "Three copies with different random starts are averaged.",
      "It is the most accurate 30-day model in normal flows, but cautious on floods.",
    ],
  },
  catchment_lstm_30: {
    name: "Catchment-mean LSTM", kind: "AI", technique: "LSTM on catchment-average weather",
    intro: [
      "An LSTM that uses weather averaged over the whole Chenab catchment above Marala.",
      "It is the matched control for the elevation-band model, using the same data source.",
      "One of the strongest all-round models at 10 and 30 days.",
      "Trained on 2016–2020, chosen on 2021, tested on 2022–2024.",
    ],
  },
  elevation_lstm_30: {
    name: "Elevation-band LSTM", kind: "AI", technique: "Spatially distributed LSTM",
    intro: [
      "Splits the catchment into four height bands, because snow at high altitude behaves very differently from rain in the valleys.",
      "Each band has its own LSTM; their outputs are combined by area into one flow forecast.",
      "It tests whether keeping spatial detail beats a simple catchment average.",
      "In this pilot it did not beat the catchment-mean control.",
    ],
  },
  nhits_30: {
    name: "N-HiTS", kind: "AI", technique: "Neural hierarchical interpolation for time series",
    intro: [
      "A modern deep-learning forecaster (Nixtla NeuralForecast) built for long horizons.",
      "It breaks the flow signal into slow and fast patterns and forecasts each at its own resolution.",
      "It reads a year of measured flow plus weather and predicts the whole horizon directly.",
      "Strong in the first days, weaker on floods further ahead.",
    ],
  },
  nbeatsx_30: {
    name: "N-BEATSx", kind: "AI", technique: "Neural basis expansion with external inputs",
    intro: [
      "A deep-learning forecaster that splits flow into trend and seasonal building blocks.",
      "The ‘x’ version also takes weather as an outside input.",
      "Like N-HiTS, it predicts the whole horizon from a year of history.",
      "Included to compare general-purpose forecasters with hydrology-specific models.",
    ],
  },
  hbv: {
    name: "Calibrated HBV", kind: "Physics-based", technique: "HBV conceptual hydrological model",
    intro: [
      "A classic physics-based model, used by many national hydrological services since the 1970s.",
      "Water-balance equations track snow, soil moisture, groundwater and river routing day by day.",
      "Its physical parameters are tuned so simulated flow matches measured Marala flow (2016–2020).",
      "Fully explainable, but on its own it misses many flood peaks.",
    ],
  },
  delta_hbv: {
    name: "Differentiable HBV (δHBV)", kind: "Hybrid physics + AI", technique: "HBV equations with LSTM-learned parameters",
    intro: [
      "Keeps the HBV water-balance equations, so water is conserved, but lets a neural network set their parameters.",
      "The LSTM adjusts the physics day by day from the weather it sees.",
      "This ‘differentiable modelling’ approach is a current research frontier in hydrology.",
      "Second only to the HBV + LSTM correction on the 30-day flood score in the replay.",
    ],
  },
  hbv_lstm: {
    name: "HBV + LSTM correction", kind: "Hybrid physics + AI", technique: "Physics model with neural-network error correction",
    intro: [
      "Runs the calibrated HBV physics model, then an LSTM learns and corrects its typical errors.",
      "Physics provides the basic water balance; AI fixes what the equations miss.",
      "It catches the most high-flow days of any model at 10 and 30 days ahead, at the cost of more false alarms.",
      "Trained on 2016–2020, chosen on 2021, tested on 2022–2024.",
    ],
  },
  hbv_lightgbm: {
    name: "HBV + LightGBM correction", kind: "Hybrid physics + AI", technique: "Physics model with gradient-boosting correction",
    intro: [
      "The same HBV physics model, corrected by LightGBM, a fast gradient-boosted tree method, instead of an LSTM.",
      "Tree methods are quick to train and show which inputs drive the correction.",
      "Compared with the LSTM correction, it is steadier but catches fewer floods.",
      "Trained on 2016–2020, chosen on 2021, tested on 2022–2024.",
    ],
  },
  snow_bucket_lstm: {
    name: "Snow-bucket + LSTM", kind: "Hybrid physics + AI", technique: "Differentiable snow/soil buckets feeding an LSTM",
    intro: [
      "A small physical model of snow, soil and groundwater ‘buckets’ feeds six physical signals into an LSTM.",
      "The buckets conserve water; the LSTM turns their state into a flow forecast.",
      "It tests whether adding simple physics helps a neural network in a snow-fed river.",
      "Here it did slightly worse than the plain LSTM overall.",
    ],
  },
};

const KIND_CLASS: Record<ModelKind, string> = {
  AI: "ai", "Climate AI": "ai", "Physics-based": "physics", "Hybrid physics + AI": "hybrid", Statistical: "stat", Baseline: "stat",
};

/** Clickable model name. Opens a short plain-language introduction. */
export function ModelTag({ id, compact }: { id: string; compact?: boolean }) {
  const info = MODEL_INFO[id];
  const [open, setOpen] = useState(false);
  const [alignRight, setAlignRight] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  const popId = useId();
  useEffect(() => {
    if (!open) return;
    const onDown = (event: PointerEvent) => { if (!ref.current?.contains(event.target as Node)) setOpen(false); };
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("pointerdown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);
  if (!info) return null;
  return <span className="ro-mtag-wrap" ref={ref}>
    <button type="button" className={`ro-mtag ${KIND_CLASS[info.kind]}${compact ? " compact" : ""}`} aria-expanded={open} aria-controls={popId} onClick={() => { const r = ref.current?.getBoundingClientRect(); setAlignRight(Boolean(r && r.left + r.width / 2 > document.documentElement.clientWidth / 2)); setOpen((v) => !v); }}>
      <span className="kind">{info.kind}</span>
      <span className="name">{info.name}</span>
      <Info size={12} aria-hidden />
    </button>
    {open && <span className={`ro-mpop${alignRight ? " right" : ""}`} id={popId} role="dialog" aria-label={`About ${info.name}`}>
      <span className="ro-mpop-head">
        <span className={`kind ${KIND_CLASS[info.kind]}`}>{info.kind}</span>
        <button type="button" onClick={() => setOpen(false)} aria-label="Close"><X size={14} /></button>
      </span>
      <strong>{info.name}</strong>
      <em>{info.technique}</em>
      {info.intro.map((line) => <span key={line} className="line">{line}</span>)}
    </span>}
  </span>;
}

export function ModelTags({ ids, label = "Built with" }: { ids: string[]; label?: string }) {
  return <div className="ro-mtags"><span className="ro-mtags-label">{label}</span>{ids.map((id) => <ModelTag key={id} id={id} />)}</div>;
}
