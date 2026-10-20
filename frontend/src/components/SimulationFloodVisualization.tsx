import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BookOpen, Box, Compass, Crosshair, Droplets, FlaskConical, MapPinned, Orbit, Pause, Play, RotateCcw, Sparkles, Users } from "lucide-react";
import * as maplibregl from "maplibre-gl";
import type { Map as MapLibreMap, StyleSpecification } from "maplibre-gl";
import type { FeatureCollection, MultiPolygon, Polygon } from "geojson";
import { bbox } from "@turf/bbox";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import districtUrl from "../data/pakistan/pakistan_districts.geojson?compressed";
import { loadMapAsset } from "./mapAssets";
import { TenYearFloodExposure } from "./TenYearFloodExposure";
import { previewAreas, type PreviewAreaId, type PreviewSelection } from "./tenYearPreviewData";
import { useOutlookMotion } from "./useOutlookMotion";
import { approximatePeople, type FloodExposurePreview } from "./outlookFloodExposureData";
import { densityFocus, riverFocus } from "./simulationCinematicData";
import { useSimulationCinematicScene } from "./useSimulationCinematicScene";
import "../ten-year-risk-outlook.css";
import "../simulation-cinematic.css";

maplibregl.setWorkerUrl(maplibreWorkerUrl);
type Boundaries = FeatureCollection<Polygon | MultiPolygon, { district: string | null; id: string; demo_id?: string }>;
const style: StyleSpecification = { version: 8, sources: {}, layers: [{ id: "background", type: "background", paint: { "background-color": "#08191e" } }] };

function focusMap(map: MapLibreMap, boundaries: Boundaries, selection: PreviewAreaId, duration = 0, cinematic = false) {
  const area = previewAreas.find((item) => item.id === selection)!;
  const feature = boundaries.features.find((item) => item.properties.district === area.name);
  const bounds = feature ? bbox(feature) : [area.coordinates[0] - .5, area.coordinates[1] - .5, area.coordinates[0] + .5, area.coordinates[1] + .5];
  map.getContainer().dataset.focus = selection;
  map.fitBounds([[bounds[0], bounds[1]], [bounds[2], bounds[3]]], { padding: cinematic ? { top: 110, bottom: 90, left: 70, right: 70 } : 38, maxZoom: cinematic ? 7.7 : 7, pitch: cinematic ? 56 : 0, bearing: cinematic ? -28 : 0, duration, essential: false });
}

export function SimulationFloodVisualization({ stationName }: { stationName: string }) {
  const [selection, setSelection] = useState<PreviewAreaId>("jhang");
  const [level, setLevel] = useState(2);
  const [playing, setPlaying] = useState(false);
  const [available, setAvailable] = useState(false);
  const [boundaries, setBoundaries] = useState<Boundaries | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [ready, setReady] = useState(false);
  const [cinematic, setCinematic] = useState(true);
  const [orbiting, setOrbiting] = useState(false);
  const [inViewport, setInViewport] = useState(true);
  const [shot, setShot] = useState("overview");
  const [sceneError, setSceneError] = useState<string | null>(null);
  const [exposureData, setExposureData] = useState<FloodExposurePreview | null>(null);
  const [layers, setLayers] = useState({ water: true, population: true });
  const { canAnimate, reducedMotion, enabled, setEnabled } = useOutlookMotion(true);
  const baselineContainer = useRef<HTMLDivElement>(null);
  const spreadContainer = useRef<HTMLDivElement>(null);
  const maps = useRef<MapLibreMap[]>([]);
  const live = useRef({ selection, canAnimate, cinematic });
  live.current = { selection, canAnimate, cinematic };
  const area = previewAreas.find((item) => item.id === selection)!;
  const sceneData = exposureData?.id === selection ? exposureData : null;
  const stopInteraction = useCallback(() => { setPlaying(false); setOrbiting(false); }, []);
  useSimulationCinematicScene({ maps: maps.current, ready, active: cinematic, data: sceneData, level, layers, onInspect: stopInteraction });
  const collection = useMemo<Boundaries | null>(() => boundaries && ({ ...boundaries, features: boundaries.features.map((feature) => ({ ...feature, properties: { ...feature.properties, demo_id: previewAreas.find((item) => item.name === feature.properties.district)?.id ?? "" } })) }), [boundaries]);

  useEffect(() => {
    let disposed = false;
    setError(null);
    loadMapAsset<Boundaries>(districtUrl).then((result) => { if (!disposed) setBoundaries(result); }).catch(() => { if (!disposed) setError("District outlines could not be loaded. Retry to prepare the maps."); });
    return () => { disposed = true; };
  }, [attempt]);

  useEffect(() => {
    if (!collection || !baselineContainer.current || !spreadContainer.current) return;
    setReady(false);
    let disposed = false;
    let synchronizing = false;
    const loaded = new Set<MapLibreMap>();
    const observers: ResizeObserver[] = [];
    try {
      [baselineContainer.current, spreadContainer.current].forEach((container, index) => {
        delete container.dataset.ready;
        const map = new maplibregl.Map({ container, style, center: [72.32, 31.27], zoom: 6, minZoom: 2, maxZoom: 10, attributionControl: false, renderWorldCopies: false, cooperativeGestures: true });
        maps.current.push(map);
        map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
        map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: 'District outlines: <a href="https://github.com/parallax-geo/gis_resources_pakistan">Parallax Geo</a> · Hypothetical spread' }), "bottom-right");
        map.getCanvas().setAttribute("aria-label", `${index === 0 ? "Baseline population" : "Simulated flood spread"} map; arrow keys pan, plus or minus zoom`);
        map.on("movestart", (event) => { container.dataset.moving = "true"; if ("originalEvent" in event && event.originalEvent) stopInteraction(); });
        map.on("moveend", () => { container.dataset.moving = "false"; });
        map.on("move", () => {
          container.dataset.zoom = map.getZoom().toFixed(3);
          container.dataset.center = `${map.getCenter().lng.toFixed(4)},${map.getCenter().lat.toFixed(4)}`;
          container.dataset.pitch = map.getPitch().toFixed(2);
          container.dataset.bearing = map.getBearing().toFixed(2);
          if (index === 1) {
            container.parentElement?.style.setProperty("--scene-heading", `${-map.getBearing()}deg`);
            const heading = container.parentElement?.querySelector("[data-camera-heading]");
            if (heading) heading.textContent = `${Math.round((map.getBearing() + 360) % 360)}°`;
          }
          if (synchronizing || live.current.cinematic) return;
          synchronizing = true;
          try { maps.current.filter((other) => other !== map).forEach((other) => other.jumpTo({ center: map.getCenter(), zoom: map.getZoom(), bearing: map.getBearing(), pitch: map.getPitch() })); }
          finally { synchronizing = false; }
        });
        map.on("load", () => {
          if (disposed) return;
          map.addSource("preview-districts", { type: "geojson", data: collection, tolerance: .5 });
          map.addLayer({ id: "preview-fill", type: "fill", source: "preview-districts", paint: { "fill-color": "#234049", "fill-opacity": .85 } });
          map.addLayer({ id: "preview-outline", type: "line", source: "preview-districts", paint: { "line-color": "#799c9f", "line-width": .65, "line-opacity": .5 } });
          map.addLayer({ id: "preview-selected", type: "line", source: "preview-districts", filter: ["==", ["get", "demo_id"], live.current.selection], paint: { "line-color": "#79f5d7", "line-width": 2 } });
          map.addSource("simulation-pins", { type: "geojson", data: { type: "FeatureCollection", features: previewAreas.map((item) => ({ type: "Feature", properties: { demo_id: item.id }, geometry: { type: "Point", coordinates: [...item.coordinates] } })) } });
          map.addLayer({ id: "simulation-pins", type: "circle", source: "simulation-pins", paint: { "circle-radius": 4, "circle-color": "#e9f9f6", "circle-stroke-width": 1.5, "circle-stroke-color": "#0e353a" } });
          map.on("click", (event) => {
            const hit = map.queryRenderedFeatures(event.point, { layers: ["simulation-pins", "preview-fill"] }).find((item) => item.properties.demo_id);
            if (hit && hit.properties.demo_id !== live.current.selection) { stopInteraction(); setAvailable(false); setSelection(hit.properties.demo_id as PreviewAreaId); }
          });
          focusMap(map, collection, live.current.selection, 0, index === 1 && live.current.cinematic);
          map.once("idle", () => { if (disposed) return; container.dataset.ready = "true"; loaded.add(map); if (loaded.size === 2) setReady(true); });
        });
        map.on("error", () => { if (!disposed) {
          stopInteraction();
          if (live.current.cinematic) { setCinematic(false); setSceneError("The cinematic view could not be rendered. The 2D comparison remains available."); }
          else { setReady(false); setError("The map could not be rendered. Retry maps to reload the visualization."); }
        } });
        const observer = new ResizeObserver(() => { if (!container.clientWidth || !container.clientHeight) return; map.resize(); if (map.getLayer("preview-fill")) focusMap(map, collection, live.current.selection, 0, index === 1 && live.current.cinematic); });
        observer.observe(container);
        observers.push(observer);
      });
    } catch { setError("Interactive maps are unavailable in this browser. Try reloading the maps."); }
    return () => { disposed = true; observers.forEach((observer) => observer.disconnect()); maps.current.forEach((map) => map.remove()); maps.current = []; };
  }, [collection, attempt]);

  useEffect(() => {
    if (!ready || !collection) return;
    maps.current.forEach((map, index) => { map.setFilter("preview-selected", ["==", ["get", "demo_id"], selection]); map.stop(); focusMap(map, collection, selection, canAnimate ? 1100 : 0, cinematic && index === 1); });
  }, [selection, ready, collection, canAnimate, cinematic]);

  useEffect(() => {
    if (!cinematic || !spreadContainer.current) return;
    const observer = new IntersectionObserver(([entry]) => setInViewport(entry.isIntersecting && entry.intersectionRatio >= .08), { threshold: .08 });
    observer.observe(spreadContainer.current);
    return () => observer.disconnect();
  }, [cinematic]);
  useEffect(() => { if (!canAnimate || !ready || !cinematic || !inViewport) setOrbiting(false); }, [canAnimate, ready, cinematic, inViewport]);
  useEffect(() => {
    const map = maps.current[1];
    if (!orbiting || !cinematic || !canAnimate || !ready || !inViewport || !map) return;
    const started = performance.now(), bearing = map.getBearing();
    let frameId = 0, previous = -Infinity;
    const frame = (now: number) => {
      if (now - previous >= 40) { previous = now; map.jumpTo({ bearing: bearing + (now - started) / 1000 * 4.8 }); }
      frameId = requestAnimationFrame(frame);
    };
    frameId = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(frameId);
  }, [orbiting, cinematic, canAnimate, ready, inViewport]);

  useEffect(() => { if (!canAnimate || !available || !ready) setPlaying(false); }, [canAnimate, available, ready]);
  useEffect(() => {
    if (!playing || !canAnimate || !available || !ready) return;
    const timer = window.setInterval(() => setLevel((value) => Math.min(5, value + 1)), 1400);
    return () => window.clearInterval(timer);
  }, [playing, canAnimate, available, ready]);
  useEffect(() => { if (level === 5) setPlaying(false); }, [level]);

  function selectArea(next: PreviewSelection) {
    if (next === "all") return;
    stopInteraction(); setShot("overview");
    if (next !== selection) setAvailable(false);
    setSelection(next);
  }

  function chooseView(next: boolean) {
    stopInteraction(); setShot("overview"); setSceneError(null); setCinematic(next);
    if (next) requestAnimationFrame(() => spreadContainer.current?.scrollIntoView({ block: "center", behavior: canAnimate ? "smooth" : "instant" }));
  }
  function cameraShot(next: "overview" | "river" | "population") {
    stopInteraction(); setShot(next);
    const map = maps.current[1];
    if (!map || !collection || !sceneData) return;
    map.stop();
    if (next === "overview") { focusMap(map, collection, selection, canAnimate ? 1600 : 0, true); return; }
    const center = next === "river" ? riverFocus(sceneData, area.coordinates) : densityFocus(sceneData);
    if (center) map.flyTo({ center, zoom: next === "river" ? 8.25 : 8.6, pitch: 62, bearing: next === "river" ? 22 : -40, duration: canAnimate ? 2100 : 0, essential: false });
  }

  return <section className="simulation-flood-visualization ten-year-outlook" aria-labelledby="simulation-spread-title" data-motion={canAnimate ? "on" : "off"} data-playing={playing} data-scene={cinematic ? "cinematic" : "comparison"} data-orbiting={orbiting}>
    <header className="ten-year-outlook-header"><div><span className="ten-year-outlook-eyebrow"><FlaskConical size={15} aria-hidden="true" /> Simulated flood explorer</span><h2 id="simulation-spread-title">Flood spread &amp; population</h2><p>Compare the maps or explore a cinematic 3D view. Drag the level slider or play the spread from lowest to highest.</p></div><button type="button" className="outlook-quiet-button" aria-pressed={canAnimate} disabled={reducedMotion} onClick={() => { stopInteraction(); setEnabled(!enabled); }}><Sparkles size={15} aria-hidden="true" /> Motion {canAnimate ? "on" : "off"}</button></header>
    <div className="simulation-spread-context"><label>Preview district<select aria-label="Simulation preview district" value={selection} onChange={(event) => selectArea(event.target.value as PreviewAreaId)}>{previewAreas.map((item) => <option value={item.id} key={item.id}>{item.name} · {item.province}</option>)}</select></label><p>Monitoring station: <strong>{stationName}</strong>. The preview district is selected separately and does not represent this station’s catchment.</p></div>
    <section className="simulation-spread-playback" aria-label="Flood spread playback"><div><span className="outlook-motion-eyebrow">SPREAD EXPLORER</span><h3>See the example flood expand.</h3><p>{area.name} · levels 0–5 · hypothetical river spread</p></div><div className="simulation-spread-play-buttons"><button type="button" className="outlook-play-button" aria-pressed={playing} disabled={!canAnimate || !available || !ready} onClick={() => { if (playing) { setPlaying(false); return; } if (level === 5) setLevel(0); setPlaying(true); }}>{playing ? <Pause size={16} aria-hidden="true" /> : <Play size={16} aria-hidden="true" />}{playing ? "Pause spread" : "Play spread"}</button><button type="button" className="outlook-restart-button" aria-label="Reset spread to level zero" disabled={!available || !ready} onClick={() => { setPlaying(false); setLevel(0); }}><RotateCcw size={16} aria-hidden="true" /></button></div><div className="simulation-spread-level" aria-live={playing ? "off" : "polite"}><strong>{level}<small>/5</small></strong><span>EXAMPLE LEVEL</span></div></section>
    {reducedMotion && <p className="simulation-control-hint">Your browser prefers reduced motion. Use the slider or scenario buttons to explore static flood levels.</p>}
    <section className="outlook-comparison outlook-panel" aria-labelledby="simulation-comparison-title">
      <header className="outlook-panel-heading"><div><h3 id="simulation-comparison-title"><MapPinned size={18} aria-hidden="true" /> {cinematic ? "Cinematic region explorer" : "Baseline versus simulated spread"}</h3><p>{cinematic ? "A spatial illustration of population density and example water spread." : "Pan or zoom either map. Both views stay synchronized."}</p></div><button type="button" className="outlook-quiet-button" onClick={() => { stopInteraction(); setShot("overview"); if (collection) maps.current.forEach((map, index) => { map.stop(); focusMap(map, collection, selection, canAnimate ? 900 : 0, cinematic && index === 1); }); }}><Crosshair size={15} aria-hidden="true" /> Reset view</button></header>
      <TenYearFloodExposure maps={maps.current} ready={ready} selection={selection} onSelectionChange={selectArea} onInteract={stopInteraction} context="simulation" initialLayers level={level} onLevelChange={setLevel} onAvailabilityChange={setAvailable} onDataChange={setExposureData} onLayerVisibilityChange={setLayers} cinematic={cinematic}>
        <div className="simulation-scene-viewbar"><div><span>MAP PRESENTATION</span><strong>{cinematic ? "A different perspective." : "Choose your perspective."}</strong></div><div role="group" aria-label="Map presentation"><button type="button" aria-pressed={cinematic} onClick={() => chooseView(true)}><Box size={15} aria-hidden="true" /> Cinematic 3D</button><button type="button" aria-pressed={!cinematic} onClick={() => chooseView(false)}><MapPinned size={15} aria-hidden="true" /> 2D comparison</button></div></div>
        {sceneError && <p className="simulation-scene-message" role="status">{sceneError}</p>}
        {cinematic && <div className="simulation-cinematic-controls"><div className="simulation-camera-shots" role="group" aria-label="Camera presets"><button type="button" disabled={!ready || !sceneData} aria-pressed={shot === "overview" && !orbiting} onClick={() => cameraShot("overview")}><Compass size={14} aria-hidden="true" /> Region overview</button><button type="button" disabled={!ready || !sceneData?.supported} aria-pressed={shot === "river" && !orbiting} onClick={() => cameraShot("river")}><Droplets size={14} aria-hidden="true" /> Fly to river</button><button type="button" disabled={!ready || !sceneData || !layers.population} aria-pressed={shot === "population" && !orbiting} onClick={() => cameraShot("population")}><Users size={14} aria-hidden="true" /> Population focus</button></div><button type="button" className="simulation-orbit-button" disabled={!canAnimate || !ready || !sceneData} aria-pressed={orbiting} onClick={() => { if (orbiting) { setOrbiting(false); return; } setShot("overview"); const map = maps.current[1]; if (map && collection) { map.stop(); focusMap(map, collection, selection, 0, true); } setOrbiting(true); }}>{orbiting ? <Pause size={15} aria-hidden="true" /> : <Orbit size={15} aria-hidden="true" />}{orbiting ? "Pause camera" : "Orbit region"}</button></div>}
        <div className="outlook-map-pair">{[{ label: "Baseline population", ref: baselineContainer }, { label: "Simulated flood spread", ref: spreadContainer }].map((pane, index) => <section className="outlook-map-pane" aria-label={cinematic && index === 1 ? "Cinematic region map" : `${pane.label} map`} key={pane.label}><header><strong>{cinematic && index === 1 ? "Region studio · 3D perspective" : pane.label}</strong><span className="outlook-example-tag">{index === 0 ? "WorldPop 2025" : "Simulated · hypothetical"}</span></header><div className="simulation-map-stage"><div className="outlook-map-canvas" ref={pane.ref} />{cinematic && index === 1 && <div className="simulation-cinematic-hud"><div className="simulation-cinematic-location"><span>REGION STUDIO / PAKISTAN</span><strong>{area.name}</strong><small>{orbiting ? "ORBIT CAMERA" : shot === "river" ? "RIVER CLOSE-UP" : shot === "population" ? "POPULATION FOCUS" : "REGION OVERVIEW"}</small></div><div className="simulation-cinematic-compass" aria-label="Camera compass"><i /><span>N</span><small data-camera-heading>332°</small></div><div className="simulation-cinematic-readouts"><div><span>EXAMPLE LEVEL</span><strong>{level}<small>/5</small></strong></div><div><span>PEOPLE IN FOOTPRINT</span><strong>{layers.water ? approximatePeople(sceneData?.levels[level].exposed_population ?? null) : "Layer off"}</strong></div><div><span>DISPLAY SCALE</span><strong>2 km<small> population grid</small></strong></div></div><span className="simulation-cinematic-corner" aria-hidden="true" /></div>}</div><p className="outlook-map-readout"><span>{area.name}</span><strong>{index === 0 ? "2025 population context" : `Example level ${level} / 5`}</strong></p></section>)}</div>
        {cinematic && <div className="simulation-cinematic-key"><span><i /> Blue columns: cells intersecting the footprint</span><p>Stylized column height = population density. The platform and water thickness are visual effects, not terrain, buildings, or measured flood depth.</p></div>}
        {!ready && !error && <p className="outlook-map-message" role="status">Preparing simulation maps…</p>}
        {error && <div className="outlook-map-message" role="status"><p>{error}</p><button type="button" className="outlook-quiet-button" onClick={() => { setPlaying(false); setAvailable(false); setAttempt((value) => value + 1); }}>Retry maps</button></div>}
      </TenYearFloodExposure>
    </section>
    <details className="simulation-spread-method outlook-method outlook-panel"><summary><span><BookOpen size={18} aria-hidden="true" /> Inputs &amp; Method</span><span>Sources, assumptions &amp; future scope</span></summary><div className="outlook-method-body"><section><h3>Inputs and method</h3><p>Real display district outlines, derived OpenStreetMap river references, and modeled WorldPop 2025 population counts. Native population pixels are summed to a 2 km equal-area display grid. No future population growth is assumed.</p><p>Level 0 is empty. Levels 1–5 use arbitrary river buffers of 250, 500, 1,000, 2,000, and 4,000 metres, clipped to the selected district. These are example spread widths, not water heights, discharge values, official warning levels, or physical worst-case bounds.</p><p>Approximate exposed people = sum of each cell’s known population × the fraction of its clipped area inside the footprint. Population is assumed uniform within each cell. NoData is excluded. The maps, area totals, population summary, and level comparison bars use the same selected level. Badin has population data but no usable river alignment, so spread and exposure remain unavailable.</p></section><section><h3>Cinematic presentation</h3><p>Cinematic 3D uses the same district, flood level, population counts, and exposure estimates as the 2D comparison. Higher inset columns represent greater population density; blue columns are cells intersecting the example footprint. Their height, the raised platform, and water thickness are exaggerated visual scales, not terrain, buildings, or measured water depth.</p><p>The river close-up follows the existing river reference, while population focus targets the highest-density display cell. Camera orbit changes only the view. Population popups retain the original fractional-area exposure estimate.</p></section><section><h3>Limitations and future scope</h3><p>There is no calibrated connection between monitoring readings, warning/danger thresholds, and these example footprints. The preview creates no monitoring alerts or incidents. Use the separate monitoring form to submit an explicit simulated threshold test.</p><p>Future work requires terrain, levees, drainage, validated historical extents, and a hydraulic model before connecting station discharge or gauge height to inundation. Native-resolution exposure checks and independently sourced population projections can follow. The preview does not train a prediction model.</p></section></div></details>
  </section>;
}
