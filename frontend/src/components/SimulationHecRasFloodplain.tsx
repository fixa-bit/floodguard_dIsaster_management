import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import type { ImageSource, Map as MapLibreMap, StyleSpecification } from "maplibre-gl";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { Pause, Play, RotateCcw } from "lucide-react";
import "../simulation-hec-ras.css";

maplibregl.setWorkerUrl(maplibreWorkerUrl);

type Corners = [[number, number], [number, number], [number, number], [number, number]];
type Frame = { hour: number; image: string; wet_area_km2: number; max_depth_m: number };
type Replay = {
  study: string; source_url: string; status: string; solver: string; result_sha256: string;
  bounds_lonlat: Corners; focus_bounds_lonlat: Corners; mobile_focus_bounds_lonlat: Corners;
  cell_count: number; terrain_resolution_ft: number; map_resolution_ft: number;
  minimum_shown_depth_m: number; main_flow_min_cfs: number; main_flow_max_cfs: number;
  focus_wet_fraction_at_peak: number; depth_legend_labels: string[]; frames: Frame[];
};
const base = `${import.meta.env.BASE_URL}hec-ras-2d/`;
const style: StyleSpecification = {
  version: 8,
  sources: { imagery: { type: "raster", tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"], tileSize: 256,
    attribution: "Imagery © Esri, Maxar, Earthstar Geographics, and the GIS User Community" } },
  layers: [{ id: "imagery", type: "raster", source: "imagery", paint: { "raster-opacity": 0.9 } }],
};
const number = (value: number, digits = 2) => value.toLocaleString("en-GB", { maximumFractionDigits: digits });

export function SimulationHecRasFloodplain() {
  const [data, setData] = useState<Replay | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [frameIndex, setFrameIndex] = useState(20);
  const [fullArea, setFullArea] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [details, setDetails] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<MapLibreMap | null>(null);
  const [mapLoaded, setMapLoaded] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${base}muncie-results.json`, { signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error(`HEC-RAS floodplain replay returned HTTP ${response.status}`);
      const result = await response.json() as Replay;
      if (result.status !== "computed" || result.frames?.length !== 25 || !result.result_sha256 ||
          result.bounds_lonlat?.length !== 4 || result.focus_bounds_lonlat?.length !== 4 ||
          result.mobile_focus_bounds_lonlat?.length !== 4 || result.focus_wet_fraction_at_peak < 0.6 ||
          result.frames.some(frame => !frame.image || !Number.isFinite(frame.max_depth_m))) {
        throw new Error("HEC-RAS floodplain frames are incomplete");
      }
      setData(result);
    }).catch(cause => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "HEC-RAS floodplain unavailable"); });
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
  useEffect(() => {
    if (!data || !container.current) return;
    const node = container.current;
    const instance = new maplibregl.Map({ container: node, style, center: [
      (data.bounds_lonlat[0][0] + data.bounds_lonlat[2][0]) / 2,
      (data.bounds_lonlat[0][1] + data.bounds_lonlat[2][1]) / 2], zoom: 13,
      attributionControl: false, maxPitch: 60 });
    map.current = instance;
    setMapLoaded(false);
    instance.addControl(new maplibregl.NavigationControl(), "top-right");
    instance.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
    instance.on("load", () => {
      instance.addSource("depth", { type: "image", url: `${base}${data.frames[20].image}`, coordinates: data.bounds_lonlat });
      instance.addLayer({ id: "depth", type: "raster", source: "depth", paint: { "raster-opacity": 0.79, "raster-resampling": "linear" } });
      setMapLoaded(true);
    });
    return () => { instance.remove(); map.current = null; };
  }, [data]);
  useEffect(() => {
    const instance = map.current;
    const node = container.current;
    if (!instance || !node || !data || !mapLoaded) return;
    const fit = () => {
      instance.resize();
      const bounds = fullArea ? data.bounds_lonlat : node.clientWidth <= 560 ? data.mobile_focus_bounds_lonlat : data.focus_bounds_lonlat;
      instance.fitBounds([bounds[3], bounds[1]], { padding: 20, duration: 0 });
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(node);
    return () => observer.disconnect();
  }, [data, mapLoaded, fullArea]);
  const frame = data?.frames[frameIndex];
  useEffect(() => {
    if (!frame || !mapLoaded) return;
    (map.current?.getSource("depth") as ImageSource | undefined)?.updateImage({ url: `${base}${frame.image}` });
  }, [frame, mapLoaded]);
  useEffect(() => {
    if (!playing || reducedMotion) return;
    const timer = window.setInterval(() => setFrameIndex(value => {
      if (value >= 24) { setPlaying(false); return value; }
      return value + 1;
    }), 700);
    return () => window.clearInterval(timer);
  }, [playing, reducedMotion]);

  if (error) return <section className="hec-replay" role="status"><p>{error}</p><button type="button" onClick={() => setAttempt(value => value + 1)}>Retry HEC-RAS replay</button></section>;
  if (!data || !frame) return <p role="status" className="terrain-pilot-loading">Loading HEC-RAS floodplain replay…</p>;

  return <section className="hec-replay" aria-label="HEC-RAS 2D floodplain demonstration" data-frame={frameIndex} data-model="muncie">
    <header className="hec-heading"><div><span>HEC-RAS 2D · USACE SAMPLE</span><h2>Muncie floodplain simulation</h2><p>Indiana, USA · computed inundation over satellite imagery</p></div>
      <button type="button" aria-expanded={details} onClick={() => setDetails(value => !value)}>{details ? "Hide details" : "View details"}</button></header>
    <p className="hec-replay-notice">Zoomed to the modeled floodplain, where water covers about {number(data.focus_wet_fraction_at_peak * 100, 0)}% of the close-up at peak. Demonstration data, not a Pakistan forecast.</p>
    <div className="hec-map-shell"><div ref={container} className="hec-map" aria-label={`HEC-RAS computed Muncie flood depth at model hour ${frame.hour}`} />
      <div className="hec-map-badge"><strong>{frame.hour} h</strong><span>Model time</span></div>
      <button type="button" className="hec-extent-button" onClick={() => setFullArea(value => !value)}>{fullArea ? "Focus floodplain" : "Show full model"}</button>
      <div className="hec-depth-legend"><span>Water depth · m</span><i /><div>{data.depth_legend_labels.map(label => <span key={label}>{label}</span>)}</div></div>
    </div>
    <div className="hec-controls hec-controls-single"><div className="hec-time-control"><div className="hec-play-buttons"><button type="button" disabled={reducedMotion} onClick={() => { if (frameIndex === 24) setFrameIndex(0); setPlaying(value => !value); }}>{playing ? <Pause size={15} /> : <Play size={15} />}{playing ? "Pause HEC-RAS replay" : "Play HEC-RAS replay"}</button><button type="button" aria-label="Reset HEC-RAS replay" onClick={() => { setPlaying(false); setFrameIndex(0); }}><RotateCcw size={15} /></button></div>
      <label htmlFor="hec-flood-time">Floodplain scenario time</label><input id="hec-flood-time" aria-label="HEC-RAS floodplain scenario time" type="range" min="0" max="24" step="1" value={frameIndex} onChange={event => { setPlaying(false); setFrameIndex(Number(event.target.value)); }} /><output>{frame.hour} / 24 h</output></div></div>
    <p className="hec-data-line">Upstream inflow {number(data.main_flow_min_cfs, 0)}–{number(data.main_flow_max_cfs, 0)} cfs · computed wet area {number(frame.wet_area_km2)} km² · maximum depth {number(frame.max_depth_m)} m</p>
    {reducedMotion && <p className="hec-data-line">Reduced motion is enabled; use the time slider to inspect frames.</p>}
    {details && <div className="hec-details"><p>The <a href={data.source_url} target="_blank" rel="noreferrer">official USACE Muncie example</a> has a 7,257-cell 2D mesh and a 1,000–20,000 cfs upstream flow hydrograph. This replay uses a separately completed HEC-RAS implicit diffusion-wave solve. No depths were painted outside its computed result.</p>
      <p>The close-up is a camera crop of the same georeferenced result; use “Show full model” to see the complete 2D area. The terrain source is 5 ft and the saved map grid is 10 ft. These display dimensions do not change the hydraulic mesh. Depths below 0.1 m are hidden. The sample is uncalibrated and is not a Jhang or Pakistan flood forecast.</p>
      <a href={`${base}muncie-results.json`} target="_blank" rel="noreferrer">View replay metadata</a>
    </div>}
  </section>;
}
