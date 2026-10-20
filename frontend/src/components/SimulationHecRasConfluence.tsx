import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import type { ImageSource, Map as MapLibreMap, StyleSpecification } from "maplibre-gl";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { Pause, Play, RotateCcw } from "lucide-react";
import "../simulation-hec-ras.css";

maplibregl.setWorkerUrl(maplibreWorkerUrl);

type Frame = { hour: number; image: string; wet_area_km2: number; max_depth_m: number };
type Scenario = { id: string; name: string; branch_cfs: number; rain_in_per_hr: number; result_sha256: string; frames: Frame[] };
type Inlet = { label: string; lonlat: [number, number]; color: string };
type Result = {
  study: string; source_url: string; solver: string; status: string;
  bounds_lonlat: [[number, number], [number, number], [number, number], [number, number]];
  terrain_resolution_ft: number; cell_count: number; minimum_shown_depth_m: number;
  main_flow_min_cfs: number; main_flow_max_cfs: number; display_end_hours: number;
  inlets: Inlet[]; scenarios: Scenario[];
};

const base = `${import.meta.env.BASE_URL}hec-ras-2d/`;
const style: StyleSpecification = {
  version: 8,
  sources: { imagery: { type: "raster", tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"], tileSize: 256,
    attribution: "Imagery © Esri, Maxar, Earthstar Geographics, and the GIS User Community" } },
  layers: [{ id: "imagery", type: "raster", source: "imagery", paint: { "raster-opacity": 0.9 } }],
};
const number = (value: number, digits = 2) => value.toLocaleString("en-GB", { maximumFractionDigits: digits });

export function SimulationHecRasConfluence() {
  const [data, setData] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [scenarioIndex, setScenarioIndex] = useState(1);
  const [frameIndex, setFrameIndex] = useState(10);
  const [playing, setPlaying] = useState(false);
  const [details, setDetails] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(false);
  const mapContainer = useRef<HTMLDivElement>(null);
  const map = useRef<MapLibreMap | null>(null);
  const [mapLoaded, setMapLoaded] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setError("");
    fetch(`${base}escondida-results.json`, { signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error(`HEC-RAS replay returned HTTP ${response.status}`);
      const result = await response.json() as Result;
      if (result.status !== "computed" || result.scenarios?.length !== 3 || result.bounds_lonlat?.length !== 4 ||
          result.scenarios.some(scenario => scenario.frames?.length !== 25 || !scenario.result_sha256 ||
            scenario.frames.some(frame => !frame.image || !Number.isFinite(frame.max_depth_m)))) {
        throw new Error("HEC-RAS computed replay files are incomplete");
      }
      setData(result);
    }).catch(cause => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "HEC-RAS replay unavailable"); });
    return () => controller.abort();
  }, [attempt]);

  useEffect(() => {
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => { setReducedMotion(motion.matches); if (motion.matches) setPlaying(false); };
    update(); motion.addEventListener("change", update);
    return () => motion.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    const pause = () => { if (document.hidden) setPlaying(false); };
    document.addEventListener("visibilitychange", pause);
    return () => document.removeEventListener("visibilitychange", pause);
  }, []);

  const scenario = data?.scenarios[scenarioIndex];
  const frame = scenario?.frames[frameIndex];
  useEffect(() => {
    if (!data || !mapContainer.current) return;
    const container = mapContainer.current;
    const coordinates = data.bounds_lonlat;
    const instance = new maplibregl.Map({ container, style, center: [
      (coordinates[0][0] + coordinates[2][0]) / 2, (coordinates[0][1] + coordinates[2][1]) / 2], zoom: 14,
      attributionControl: false, maxPitch: 60 });
    map.current = instance;
    setMapLoaded(false);
    instance.addControl(new maplibregl.NavigationControl(), "top-right");
    instance.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
    instance.on("load", () => {
      instance.addSource("depth", { type: "image", url: `${base}${data.scenarios[1].frames[10].image}`, coordinates });
      instance.addLayer({ id: "depth", type: "raster", source: "depth", paint: { "raster-opacity": 0.82, "raster-resampling": "linear" } });
      data.inlets.forEach(inlet => new maplibregl.Marker({ color: inlet.color, scale: 0.8 })
        .setLngLat(inlet.lonlat).setPopup(new maplibregl.Popup({ offset: 15 }).setText(inlet.label)).addTo(instance));
      instance.fitBounds([coordinates[3], coordinates[1]], { padding: 26, duration: 0 });
      setMapLoaded(true);
    });
    const observer = new ResizeObserver(() => {
      instance.resize();
      instance.fitBounds([coordinates[3], coordinates[1]], { padding: 26, duration: 0 });
    });
    observer.observe(container);
    return () => { observer.disconnect(); instance.remove(); map.current = null; };
  }, [data]);
  useEffect(() => {
    if (!frame || !mapLoaded) return;
    (map.current?.getSource("depth") as ImageSource | undefined)?.updateImage({ url: `${base}${frame.image}` });
  }, [frame, mapLoaded]);
  useEffect(() => {
    if (!playing || !scenario || reducedMotion) return;
    const timer = window.setInterval(() => setFrameIndex(value => {
      if (value >= scenario.frames.length - 1) { setPlaying(false); return value; }
      return value + 1;
    }), 700);
    return () => window.clearInterval(timer);
  }, [playing, scenario, reducedMotion]);

  if (error) return <section className="hec-replay" role="status"><p>{error}</p><button type="button" onClick={() => setAttempt(value => value + 1)}>Retry HEC-RAS replay</button></section>;
  if (!data || !scenario || !frame) return <p role="status" className="terrain-pilot-loading">Loading HEC-RAS 2D replay…</p>;

  return <section className="hec-replay" aria-label="HEC-RAS 2D confluence demonstration" data-frame={frameIndex} data-scenario={scenario.id}>
    <header className="hec-heading"><div><span>HEC-RAS 2D · USACE SAMPLE</span><h2>River and tributary flood simulation</h2><p>Escondida confluence, New Mexico · computed depth over satellite imagery</p></div>
      <button type="button" aria-expanded={details} onClick={() => setDetails(value => !value)}>{details ? "Hide details" : "View details"}</button></header>
    <p className="hec-replay-notice">Uncalibrated demonstration case, not a Pakistan flood forecast. Markers show the two distinct upstream flow boundaries.</p>
    <div className="hec-map-shell"><div ref={mapContainer} className="hec-map" aria-label={`HEC-RAS computed depth map at ${number(frame.hour, 0)} hours with main river, ${scenario.branch_cfs} cfs branch inflow, and ${scenario.rain_in_per_hr} in/hr rain`} />
      <div className="hec-map-badge"><strong>{number(frame.hour, 0)} h</strong><span>Model time</span></div>
      <div className="hec-depth-legend"><span>Water depth · m</span><i /><div><span>0.1</span><span>0.5</span><span>1.0</span><span>1.5+</span></div></div>
    </div>
    <div className="hec-controls">
      <div className="hec-plan-control"><label htmlFor="hec-scenario">Flow and rain scenario</label><input id="hec-scenario" aria-label="HEC-RAS flow and rain scenario" type="range" min="0" max="2" step="1" value={scenarioIndex} onChange={event => { setPlaying(false); setFrameIndex(10); setScenarioIndex(Number(event.target.value)); }} /><output>{scenario.name}</output><div><span>Main river</span><span>+ branch</span><span>+ rain</span></div></div>
      <div className="hec-time-control"><div className="hec-play-buttons"><button type="button" disabled={reducedMotion} onClick={() => { if (frameIndex === scenario.frames.length - 1) setFrameIndex(0); setPlaying(value => !value); }}>{playing ? <Pause size={15} /> : <Play size={15} />}{playing ? "Pause HEC-RAS replay" : "Play HEC-RAS replay"}</button><button type="button" aria-label="Reset HEC-RAS replay" onClick={() => { setPlaying(false); setFrameIndex(0); }}><RotateCcw size={15} /></button></div>
        <label htmlFor="hec-time">Scenario time</label><input id="hec-time" aria-label="HEC-RAS scenario time" type="range" min="0" max={scenario.frames.length - 1} step="1" value={frameIndex} onChange={event => { setPlaying(false); setFrameIndex(Number(event.target.value)); }} /><output>{number(frame.hour, 0)} / {number(data.display_end_hours, 0)} h</output></div>
    </div>
    <p className="hec-data-line">Main inflow {number(data.main_flow_min_cfs, 0)}–{number(data.main_flow_max_cfs, 0)} cfs · branch {number(scenario.branch_cfs, 0)} cfs · rain {number(scenario.rain_in_per_hr, 2)} in/hr</p>
    <p className="hec-data-line">Computed depth ≥{number(data.minimum_shown_depth_m, 1)} m · wet area {number(frame.wet_area_km2)} km² · maximum depth {number(frame.max_depth_m)} m · {number(data.terrain_resolution_ft, 0)} ft terrain grid</p>
    {reducedMotion && <p className="hec-data-line">Reduced motion is enabled; use the time slider to inspect frames.</p>}
    {details && <div className="hec-details"><p>Saved results from the <a href={data.source_url} target="_blank" rel="noreferrer">USACE HEC-RAS Escondida example</a>. The main-river boundary uses the sample's 300–2,800 cfs inflow hydrograph. The second boundary represents a separate branch; its 0 or 50 cfs flow and the 0 or 0.02 in/hr rain-on-mesh inputs are hypothetical sensitivity settings. Each selectable case is a separately completed HEC-RAS solve, not a depth map altered in the browser.</p>
      <p>The native solver uses {number(data.cell_count, 0)} 2D cells; HEC-RAS maps their water surface against the 5 ft terrain raster. The finer terrain grid makes the shoreline less blocky but does not add hydraulic detail beyond the solver mesh. Precipitation falls directly on the modeled mesh, with no separate catchment runoff or infiltration calibration. Depths are in US survey feet in the model and converted to metres for this display.</p>
      <p>Solver: {data.solver}. The sample has no validated Pakistan terrain, upstream observations, or rainfall forecast. Use the results as a visual demonstration only.</p>
      <a href={`${base}escondida-results.json`} target="_blank" rel="noreferrer">View replay metadata</a>
    </div>}
  </section>;
}
