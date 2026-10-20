import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BookOpen, Crosshair, Layers, LoaderCircle, Mountain, Pause, Play, RotateCcw, Route, Users, Waves } from "lucide-react";
import pilotUrl from "../data/jhang-terrain-prototype/jhang-pilot.geojson?compressed";
import { loadMapAsset } from "./mapAssets";
import { pilotAssetBase, pilotMetricAt, validateJhangPilot, type JhangTerrainPilot, type PilotMetadata } from "./jhangTerrainPrototypeData";
import { approximatePeople } from "./outlookFloodExposureData";
import { ReplayImpactBar } from "./ReplayImpactBar";
import { useJhangTerrainPilotMap } from "./useJhangTerrainPilotMap";
import { useOutlookMotion } from "./useOutlookMotion";
import { useReplayCurrents } from "./useReplayCurrents";
import "../simulation-storm-replay.css";
import "../simulation-terrain-prototype.css";

function SensitivityChart({ data, level }: { data: JhangTerrainPilot; level: number }) {
  const maximum = Math.max(1, data.continuous_metrics.at(-1)?.flood_area_km2 ?? 1);
  const x = (rise: number) => 37 + rise / 3 * 270;
  const y = (area: number) => 112 - area / maximum * 87;
  const selected = pilotMetricAt(data, level);
  return <div className="storm-replay-chart terrain-pilot-chart">
    <div className="storm-replay-section-label"><Waves size={14} /> CONNECTED AREA RESPONSE <small>km²</small></div>
    <svg viewBox="0 0 330 151" role="img" aria-label="Added connected area against assumed relative rise, sampled every 0.05 metres">
      {[0, .5, 1].map(fraction => <g key={fraction}><line x1="37" x2="307" y1={112 - 87 * fraction} y2={112 - 87 * fraction} stroke="#35505c" strokeWidth=".6" /><text x="30" y={115 - 87 * fraction} textAnchor="end">{(maximum * fraction).toFixed(0)}</text></g>)}
      <path d={data.continuous_metrics.map((entry, index) => `${index ? "L" : "M"}${x(entry.rise_m)},${y(entry.flood_area_km2)}`).join(" ")} stroke="#9ce0ce" strokeWidth="2" fill="none" />
      <line x1={x(level)} x2={x(level)} y1="20" y2="112" stroke="#79d4c2" strokeOpacity=".45" strokeDasharray="3 3" />
      {[0, 1.5, 3].map(value => <text key={value} x={x(value)} y="128" textAnchor="middle">{value}</text>)}
      <circle cx={x(level)} cy={y(selected.flood_area_km2)} r="5" fill="#edfff5" stroke="#53cfb9" strokeWidth="2" />
      <text x="174" y="145" textAnchor="middle">Assumed rise above DEM reference (m)</text>
    </svg>
    <p className="terrain-pilot-chart-note">Impact curve sampled every 0.05 m; map stage can be adjusted in 0.01 m steps.</p>
  </div>;
}

export function SimulationJhangTerrainPrototype() {
  const [data, setData] = useState<JhangTerrainPilot | null>(null);
  const [metadata, setMetadata] = useState<PilotMetadata | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [level, setLevel] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [floodplain, setFloodplain] = useState(false);
  const [satellite, setSatellite] = useState(true);
  const [imageryError, setImageryError] = useState(false);
  const [terrain, setTerrain] = useState(true);
  const [population, setPopulation] = useState(false);
  const [paths, setPaths] = useState(false);
  const [currents, setCurrents] = useState(true);
  const [inView, setInView] = useState(true);
  const container = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const { canAnimate, reducedMotion, enabled, setEnabled } = useOutlookMotion(true);
  const stop = useCallback(() => setPlaying(false), []);
  const onImageryError = useCallback(() => { setSatellite(false); setImageryError(true); }, []);
  const { map, ready, error, imageError, spreadReady, spreadError, retry } = useJhangTerrainPilotMap({ container, data, metadata, level, floodplain, satellite, terrain, population, paths, onInteract: stop, onImageryError });
  const available = Boolean(data && metadata && ready && spreadReady && !spreadError && !error);
  const waterData = useMemo(() => data ? {
    supported: true, water: data.stream_corridor,
    river_lines: { type: "FeatureCollection" as const, features: data.waterways.features.filter(item => item.properties?.waterway === "river") },
  } : null, [data]);
  useReplayCurrents({ map, canvas, data: waterData, level: 1, enabled: currents && available, animate: playing && canAnimate && inView });
  useEffect(() => {
    let disposed = false;
    setLoadError(false); setData(null); setMetadata(null);
    Promise.all([loadMapAsset<JhangTerrainPilot>(pilotUrl), loadMapAsset<PilotMetadata>(pilotAssetBase + "metadata.json")]).then(([result, meta]) => {
      validateJhangPilot(result);
      if (meta.population_image_bounds?.length !== 4 || !meta.population_image_bounds.every(Number.isFinite) || !meta.dem_credit || !meta.grid) throw new Error("Invalid terrain metadata");
      if (!disposed) { setData(result); setMetadata(meta); }
    }).catch(() => { if (!disposed) setLoadError(true); });
    return () => { disposed = true; };
  }, [attempt]);
  useEffect(() => {
    if (!stage.current) return;
    const observer = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting && entry.intersectionRatio >= .08), { threshold: .08 });
    observer.observe(stage.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => { if (!canAnimate || !inView || !available) stop(); }, [canAnimate, inView, available, stop]);
  useEffect(() => {
    if (!playing || !canAnimate || !inView || !available) return;
    const timer = window.setInterval(() => setLevel(current => Math.min(3, Math.round((current + .01) * 100) / 100)), 40);
    return () => window.clearInterval(timer);
  }, [playing, canAnimate, inView, available]);
  useEffect(() => { if (level >= 3) stop(); }, [level, stop]);
  useEffect(() => { if (!canAnimate) map?.stop(); }, [canAnimate, map]);
  function seek(value: number) { stop(); setLevel(Math.round(Math.max(0, Math.min(3, value)) * 100) / 100); setFloodplain(true); }
  function frame(close: boolean) {
    stop(); if (!map || !data) return;
    if (close) map.flyTo({ center: [72.262, 31.297], zoom: 12.5, duration: canAnimate ? 1600 : 0 });
    else map.fitBounds([[data.bounds[0], data.bounds[1]], [data.bounds[2], data.bounds[3]]], { padding: 35, duration: canAnimate ? 1000 : 0 });
  }
  const stats = data ? pilotMetricAt(data, level) : undefined, maximum = data?.continuous_metrics.at(-1);
  const areaText = (value: number | undefined) => value === undefined ? "Unavailable" : `${value.toLocaleString("en-US", { maximumFractionDigits: 2 })} km²`;
  return <section className="storm-replay terrain-pilot" aria-labelledby="terrain-pilot-title" data-level={level.toFixed(2)} data-playing={playing} data-motion={canAnimate && inView ? "on" : "off"}>
    <header className="storm-replay-heading"><div><span className="storm-replay-eyebrow"><Mountain size={14} /> JHANG / CHENAB · LOCAL STUDY</span><h2 id="terrain-pilot-title">Where low ground connects.</h2><p>Explore how a small floodplain can connect as an assumed river reference rises. Real elevation shapes each footprint.</p></div><span className="storm-replay-demo"><i /> Terrain-guided prototype</span></header>
    <div className="terrain-pilot-facts"><span>~30 m elevation grid</span><span>{data ? `${data.study_area_km2.toFixed(0)} km\u00b2 study window` : "Small Jhang study window"}</span><span>Continuous 0.01 m stage control</span><strong>Experimental · uncalibrated</strong></div>
    <p className="terrain-pilot-disclosure">Play advances an assumed rise from 0 to 3 m and progressively reveals terrain cells connected to the river. This is a sensitivity display, not a measured river level, water depth, flood arrival simulation or official warning threshold.</p>
    <div className="storm-replay-layout">
      <div className="storm-replay-stage" ref={stage}>
        <div className="storm-replay-map terrain-pilot-map" ref={container} />
        <canvas className="storm-replay-currents" ref={canvas} aria-hidden="true" />
        <div className="storm-replay-map-title"><span>PUNJAB / PAKISTAN</span><strong>Chenab floodplain</strong><small>Jhang · 31.23–31.37°N / 72.18–72.35°E</small></div>
        <div className="storm-replay-map-tools" data-tour-target="jhang-terrain-layers" role="group" aria-label="Terrain prototype layers">
          <button type="button" aria-pressed={satellite} onClick={() => { setImageryError(false); setSatellite(!satellite); }}><Layers size={14} /> Satellite</button>
          <button type="button" aria-pressed={terrain} onClick={() => setTerrain(!terrain)}><Mountain size={14} /> Terrain relief</button>
          <button type="button" aria-pressed={population} onClick={() => setPopulation(!population)}><Users size={14} /> Population</button>
          <button type="button" aria-pressed={floodplain} disabled={!available} onClick={() => setFloodplain(!floodplain)}><Waves size={14} /> Floodplain spread</button>
          <button type="button" aria-pressed={paths} onClick={() => setPaths(!paths)}><Route size={14} /> Connection paths</button>
          <button type="button" aria-pressed={currents} disabled={!available} onClick={() => setCurrents(!currents)}><Waves size={14} /> Water animation</button>
        </div>
        <div className="storm-replay-camera" role="group" aria-label="Terrain prototype camera"><button type="button" disabled={!available} onClick={() => frame(false)}><Crosshair size={13} /> Study area</button><button type="button" disabled={!available} onClick={() => frame(true)}>Explore river bend</button></div>
        <div className="storm-replay-map-status"><span><i /> ASSUMED RELATIVE RISE</span><strong>+{stats?.assumed_rise_m.toFixed(2) ?? "-"}<small> m</small></strong><span>{playing ? "Progressively revealing connected cells" : floodplain ? "Connected floodplain layer on" : "Mapped stream view"}</span></div>
        <div className="storm-replay-map-key terrain-pilot-legend"><span>{floodplain ? <><i /> Connected terrain spread <b className="pilot-reference-key" /> DEM reference extent</> : <><b className="pilot-river-key" /> Mapped Chenab · illustrative 90 m ribbon</>}</span><span><b className="pilot-river-key" /> Chenab centerline <b className="pilot-canal-key" /> Mapped canals · context only</span>{paths && <span>Dashed pale paths: inferred terrain connections, not surveyed streams.</span>}{population && <span>WorldPop 2025 · people/km2: <b className="pilot-density-key" /> 0 to 10,000+</span>}<span>Only one river and two canals are mapped here; smaller stream coverage is incomplete. Surface motion is illustrative, not measured flow. <a href={pilotAssetBase + "NOTICE.txt"} target="_blank" rel="noreferrer">Elevation: Copernicus GLO-30 · credits</a></span></div>
        {(!available || loadError) && <div className="storm-replay-map-loading" role="status">{loadError ? <><span>The local terrain study could not load.</span><button type="button" onClick={() => setAttempt(value => value + 1)}>Retry terrain data</button></> : error || spreadError ? <><span>{error ?? "The continuous terrain thresholds could not load."}</span><button type="button" onClick={retry}>Reload study map</button></> : <><LoaderCircle className="spinning" size={18} /> Preparing terrain study...</>}</div>}
      </div>
      <aside className="storm-replay-inspector" aria-label="Terrain prototype inspector">
        <div className="storm-replay-inspector-header"><span>CONNECTED-FILL SENSITIVITY</span><strong>+{stats?.assumed_rise_m.toFixed(2) ?? "-"} m</strong><small>Incremental footprint above the assumed reference extent</small></div>
        <div className="storm-replay-metrics">
          <ReplayImpactBar kind="population" value={stats?.exposed_population ?? null} maximum={maximum?.exposed_population ?? null} formattedValue={approximatePeople(stats?.exposed_population ?? null)} formattedMaximum={approximatePeople(maximum?.exposed_population ?? null)} scaleLabel="of +3 m" maximumLabel="At +3 m" ariaScaleLabel="of the +3 m example" />
          <p className="terrain-pilot-coverage">{stats?.known_raster_area_fraction != null ? `Known population-raster coverage: ${(stats.known_raster_area_fraction * 100).toFixed(1)}% of this footprint. Remaining area has no population estimate.` : "At zero rise, no incremental footprint is counted."}</p>
          <ReplayImpactBar kind="area" value={stats?.flood_area_km2 ?? null} maximum={maximum?.flood_area_km2 ?? null} formattedValue={areaText(stats?.flood_area_km2)} formattedMaximum={areaText(maximum?.flood_area_km2)} scaleLabel="of +3 m" maximumLabel="At +3 m" ariaScaleLabel="of the +3 m example" />
        </div>
        {data && <SensitivityChart data={data} level={level} />}
        <div className="terrain-pilot-insight"><strong>Why the shape changes</strong><p>Water can enter a low area only through a connected path. Higher terrain blocks the connection until the assumed rise crosses its sill.</p><small>Two mapped canals are shown for context. Their capacities and connections have not been surveyed.</small></div>
      </aside>
    </div>
    <section className="storm-replay-timeline" aria-label="Terrain prototype controls"><div className="storm-replay-playback-actions"><button type="button" className="storm-replay-play" disabled={!available || !canAnimate} aria-pressed={playing} onClick={() => { if (playing) stop(); else { if (level >= 3) setLevel(0); setFloodplain(true); setPlaying(true); } }}>{playing ? <Pause size={16} /> : <Play size={16} />}{playing ? "Pause spread" : "Play spread"}</button><button type="button" aria-label="Reset terrain example" disabled={!available} onClick={() => { stop(); setLevel(0); setFloodplain(false); }}><RotateCcw size={16} /></button></div><div className="storm-replay-scrubber"><label htmlFor="terrain-rise">ASSUMED RELATIVE RISE<output>+{stats?.assumed_rise_m.toFixed(2) ?? "-"} m</output></label><input id="terrain-rise" aria-label="Continuous assumed terrain rise" aria-valuetext={stats ? `Assumed rise ${stats.assumed_rise_m.toFixed(2)} metres` : "Loading"} type="range" min="0" max="3" step="0.01" value={level} disabled={!available} onChange={event => seek(Number(event.target.value))} /><div><button type="button" disabled={!available} onClick={() => seek(0)}>Lowest · +0 m</button><span>Continuous presentation stage · no physical time</span><button type="button" disabled={!available} onClick={() => seek(3)}>Highest · +3 m</button></div></div></section>
    <div className="storm-replay-notices" aria-live="polite">
      {stats?.touches_study_edge && <p className="terrain-pilot-edge">This footprint reaches the study boundary. Area and population are limited to this window.</p>}
      {imageryError && <p>Satellite imagery is unavailable; the local terrain and connected footprints remain usable.</p>}
      {imageError && <p>A context image is unavailable. Local footprint geometry and its saved estimates remain usable.</p>}
      {reducedMotion && <p>Your browser prefers reduced motion. Use the slider to explore static examples.</p>}
      <p>Population is a fixed 2025 estimate, not a count of people present or confirmed affected. Low-stage and high-stage examples are sensitivity inputs, not probabilities.</p>
      <button type="button" className="terrain-pilot-motion" disabled={reducedMotion} aria-pressed={enabled} onClick={() => { stop(); setEnabled(!enabled); }}>Motion {canAnimate ? "on" : "off"}</button>
    </div>
    <details className="storm-replay-method"><summary><BookOpen size={15} /> Inputs &amp; Method<span>Terrain, connections, assumptions, next steps</span></summary><div>
      <h3>Datasets and features used</h3><p><a href="https://registry.opendata.aws/copernicus-dem/" target="_blank" rel="noreferrer">Copernicus GLO-30</a>: a small crop of nominal 30 m surface elevations, resampled to a 30 m UTM 43N grid. It includes vegetation and structures; it is not a surveyed river bed. <a href={pilotAssetBase + "elevation-30m.tif"} download>Download the study elevation grid</a>.</p>
      <p><a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a>: one Chenab river centerline and two canals. Only the river is a source; canals are context. No local natural-water polygons were returned. One canal carries a mapper’s verification note. Local stream/drain coverage is incomplete. <a href={pilotAssetBase + "mapped-waterways.geojson"} download>Inspect the clipped OSM data</a>.</p>
      <p><a href="https://www.worldpop.org/" target="_blank" rel="noreferrer">WorldPop 2025</a>: native approximately 100 m population counts, with exact projected pixel/footprint overlap fractions and a uniform-within-pixel assumption. NoData is excluded. Study-window raster coverage: {data ? `${(data.population_coverage_fraction * 100).toFixed(1)}%` : "loading"}.</p>
      <h3>Engineered inputs and method</h3><p>A lower local DEM statistic (10th percentile within 300 m) is sampled every approximately 60 m along the river and smoothed (17-sample median, then a Gaussian filter). Each cell uses its nearest reference sample to calculate relative elevation. This assumed reference is not a surveyed water surface or river bed. A four-neighbour minimax search finds the smallest assumed rise that connects it to the river. NoData blocks paths; diagonal corner jumps are excluded. Canals are never burned into the DEM.</p>
      <p>The map reads a continuous 0–3 m minimax sill raster and updates in 0.01 m slider/playback increments; area and population summaries are precomputed every 0.05 m and interpolated between samples. The mapped Chenab is drawn separately with a 90 m illustrative centerline ribbon; this is not a measured channel width. Floodplain spread is an optional layer. The connected extent at zero rise is an assumed reference, not observed river water; it is excluded from impact estimates. Connection paths trace this search tree, not hydraulic flow. Sub-metre inputs do not imply sub-metre accuracy.</p>
      <h3>Outputs and current limitations</h3><p>Outputs are incrementally revealed connected terrain cells, area, approximate population overlap and a rise-versus-area chart. Playback animates the assumed stage, not a physical flood arrival. The stream ribbon surface streaks are visual guidance with no measured direction or velocity. The model has no depth, discharge, rainfall-runoff or water-volume balance. No historical flood validation has been performed. Smaller stream/drain coverage, levees, culverts, bathymetry, drainage capacity and gauge datum alignment are missing. Use this as a learning prototype.</p>
      <h3>Future scope</h3><p>Check local drains, embankments and culverts; obtain surveyed channel sections or a suitable bare-earth DEM; add measured inflow hydrographs and roughness. Compare against dated observed flood extents and river gauges before considering a calibrated 2D hydraulic model such as HEC-RAS 2D.</p>
      <p><a href={pilotAssetBase + "metadata.json"} target="_blank" rel="noreferrer">Source manifest and processing assumptions</a> · <a href={pilotAssetBase + "NOTICE.txt"} target="_blank" rel="noreferrer">Data credits and licence notice</a></p>
      {metadata && <p className="terrain-pilot-credit">{metadata.dem_credit}. {metadata.dem_liability_notice}. <a href={metadata.dem_license_url} target="_blank" rel="noreferrer">Copernicus licence</a>. Waterways © OpenStreetMap contributors, ODbL 1.0. Population: WorldPop 2025, CC BY 4.0.</p>}
    </div></details>
  </section>;
}
