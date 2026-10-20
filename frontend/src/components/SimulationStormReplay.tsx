import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Activity, BookOpen, Crosshair, Eye, Film, Layers, LoaderCircle, MapPinned, MousePointer2, Pause, Play, RotateCcw, ScanLine, Waves, X } from "lucide-react";
import { loadMapAsset } from "./mapAssets";
import { approximatePeople, exposureAssetUrl, type FloodExposurePreview } from "./outlookFloodExposureData";
import { previewAreas, type PreviewAreaId } from "./tenYearPreviewData";
import { useOutlookMotion } from "./useOutlookMotion";
import { useReplayCurrents } from "./useReplayCurrents";
import { ReplayImpactBar } from "./ReplayImpactBar";
import { replayTerrainBase, useReplayTerrain } from "./useReplayTerrain";
import { frameReplay, useStormReplayMap } from "./useStormReplayMap";
import { inspectReplayLine, REPLAY_MINUTES, REPLAY_PEAK_MINUTE, replayClock, replayLevel, replayScenarios, waterPolygons, type Coordinate, type ReplayScenario } from "./stormReplayData";
import "../simulation-storm-replay.css";

function FootprintChart({ data, scenario, minute, onSeek }: { data: FloodExposurePreview; scenario: ReplayScenario; minute: number; onSeek: (minute: number) => void }) {
  const gradient = useId();
  const maximum = data.levels[5].flood_area_km2 || 1;
  const x = (time: number) => 36 + time / REPLAY_MINUTES * 292;
  const y = (time: number, selection = scenario) => 121 - (data.levels[replayLevel(time, selection)].flood_area_km2 ?? 0) / maximum * 94;
  const path = (selection: ReplayScenario) => Array.from({ length: 361 }, (_, time) => `${time ? "L" : "M"}${x(time).toFixed(2)},${y(time, selection).toFixed(2)}`).join(" ");
  return <div className="storm-replay-chart">
    <div className="storm-replay-section-label"><Activity size={13} /><span>EXAMPLE FLOOD FOOTPRINT</span><small>km²</small></div>
    <svg viewBox="0 0 350 155" role="img" aria-label={`Hypothetical flood footprint over six example hours; cursor at ${replayClock(minute)}`}>
      <defs><linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1"><stop stopColor="#59bbff" stopOpacity=".3" /><stop offset="1" stopColor="#59bbff" stopOpacity=".01" /></linearGradient></defs>
      {[0, .5, 1].map((fraction) => <g key={fraction}><line x1="36" x2="328" y1={121 - fraction * 94} y2={121 - fraction * 94} stroke="#27414e" strokeWidth=".6" /><text x="30" y={124 - fraction * 94} textAnchor="end">{(maximum * fraction).toFixed(0)}</text></g>)}
      <path d={`${path(scenario)} L328,121 L36,121 Z`} fill={`url(#${gradient})`} />
      {replayScenarios.filter((item) => item.id !== scenario).map((item) => <path key={item.id} d={path(item.id)} fill="none" stroke={item.id === "lower" ? "#78cbb6" : "#57798f"} strokeDasharray="3 4" strokeWidth="1" opacity=".7" />)}
      <path d={path(scenario)} fill="none" stroke="#8cd7ff" strokeWidth="1.8" />
      <line x1={x(minute)} x2={x(minute)} y1="20" y2="124" stroke="#d6f3ff" strokeWidth="1" opacity=".7" />
      <circle cx={x(minute)} cy={y(minute)} r="3.5" fill="#dff6ff" stroke="#318cc8" strokeWidth="2" />
      {[0, 120, 240, 360].map((time) => <text key={time} x={x(time)} y="143" textAnchor="middle">{replayClock(time)}</text>)}
    </svg>
    <div className="storm-replay-chart-caption"><span><i /> Selected example <i className="storm-chart-comparison" /> Other examples</span><button type="button" onClick={() => onSeek(REPLAY_PEAK_MINUTE)}>Jump to peak</button></div>
  </div>;
}

export function SimulationStormReplay() {
  const [selection, setSelection] = useState<PreviewAreaId>("jhang");
  const [loaded, setLoaded] = useState<FloodExposurePreview | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [scenario, setScenario] = useState<ReplayScenario>("higher");
  const [minute, setMinute] = useState(120);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [satellite, setSatellite] = useState(true);
  const [satelliteError, setSatelliteError] = useState(false);
  const [population, setPopulation] = useState(false);
  const [currents, setCurrents] = useState(true);
  const [terrain, setTerrain] = useState(true);
  const [drawing, setDrawing] = useState(false);
  const [points, setPoints] = useState<Coordinate[]>([]);
  const [inView, setInView] = useState(true);
  const container = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const root = useRef<HTMLElement>(null);
  const data = loaded?.id === selection ? loaded : null;
  const area = previewAreas.find((item) => item.id === selection)!;
  const level = data?.supported ? replayLevel(minute, scenario) : 0;
  const stats = data?.supported ? data.levels[level] : null;
  const peak = replayScenarios.find((item) => item.id === scenario)!.peak;
  const polygons = useMemo(() => waterPolygons(data, level), [data, level]);
  const inspection = useMemo(() => data?.supported ? inspectReplayLine(points, polygons) : null, [points, polygons, data]);
  const { canAnimate, reducedMotion, enabled, setEnabled } = useOutlookMotion(true);
  const stop = useCallback(() => setPlaying(false), []);
  const onPoint = useCallback((point: Coordinate) => {
    stop(); setPoints((current) => [...current.slice(0, 1), point]);
  }, [stop]);
  const imageryFailed = useCallback(() => { setSatellite(false); setSatelliteError(true); }, []);
  const { map, ready, error: mapError, retry: retryMap } = useStormReplayMap({ container, data, level, satellite, population, drawing, points, canAnimate, onPoint, onInteract: stop, onSatelliteError: imageryFailed });
  const available = Boolean(ready && data?.supported && !mapError);
  const terrainContext = useReplayTerrain(map, ready, selection, terrain);
  useReplayCurrents({ map, canvas, data, level, enabled: currents && available, animate: playing && canAnimate && inView });

  useEffect(() => {
    let disposed = false;
    setLoadError(false);
    loadMapAsset<FloodExposurePreview>(exposureAssetUrl(selection)).then((result) => { if (!disposed) setLoaded(result); }).catch(() => { if (!disposed) setLoadError(true); });
    return () => { disposed = true; };
  }, [selection, attempt]);
  useEffect(() => {
    if (!stage.current) return;
    const observer = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting && entry.intersectionRatio >= .08), { threshold: .08 });
    observer.observe(stage.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => { if (!canAnimate || !inView || !available || drawing) setPlaying(false); }, [canAnimate, inView, available, drawing]);
  useEffect(() => {
    if (!playing || !canAnimate || !inView || !available) return;
    let previous = performance.now();
    const timer = window.setInterval(() => {
      const now = performance.now(), delta = Math.min(250, now - previous); previous = now;
      setMinute((current) => Math.min(REPLAY_MINUTES, current + delta / 1000 * 9 * speed));
    }, 100);
    return () => window.clearInterval(timer);
  }, [playing, canAnimate, inView, available, speed]);
  useEffect(() => { if (minute >= REPLAY_MINUTES) setPlaying(false); }, [minute]);
  useEffect(() => { if (points.length === 2) setDrawing(false); }, [points]);

  function seek(time: number) { stop(); setMinute(time); }
  function changeArea(id: PreviewAreaId) { stop(); setDrawing(false); setPoints([]); setSelection(id); setMinute(120); }
  function camera(close: boolean) { stop(); if (map && data) frameReplay(map, data, close, canAnimate); }
  const phase = minute === 0 ? "Before the example event" : minute >= REPLAY_MINUTES ? "Replay complete" : minute === REPLAY_PEAK_MINUTE ? "Peak example spread" : minute < REPLAY_PEAK_MINUTE ? "Rising spread" : "Receding spread";

  return <section className="storm-replay" aria-labelledby="storm-replay-title" ref={root} data-playing={playing} data-motion={canAnimate && inView ? "on" : "off"} data-level={level} data-area={data?.id ?? ""} data-minute={minute.toFixed(2)} data-exposed-people={stats?.exposed_population ?? ""} onKeyDown={(event) => { if (event.key === "Escape") { setDrawing(false); if (points.length < 2) setPoints([]); } }}>
    <header className="storm-replay-heading"><div><span className="storm-replay-eyebrow"><Film size={14} /> FLOODGUARD · EVENT STUDIO</span><h2 id="storm-replay-title">Watch the water move.</h2><p>A six-hour hypothetical event, from rising water to retreat. Explore the landscape, then inspect a line across it.</p></div><span className="storm-replay-demo"><i /> Hypothetical replay</span></header>
    <div className="storm-replay-toolbar"><label>Study district<select aria-label="Storm replay district" value={selection} onChange={(event) => changeArea(event.target.value as PreviewAreaId)}>{previewAreas.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.province}</option>)}</select></label><div className="storm-replay-scenarios" role="group" aria-label="Storm replay scenario">{replayScenarios.map((item) => <button key={item.id} type="button" aria-pressed={scenario === item.id} onClick={() => { stop(); setScenario(item.id); }}>{item.label}<small>Peak level {item.peak}</small></button>)}</div><button type="button" className="storm-replay-motion" aria-pressed={canAnimate} disabled={reducedMotion} onClick={() => { stop(); setEnabled(!enabled); }}><Eye size={14} /> Motion {canAnimate ? "on" : "off"}</button></div>
    <div className="storm-replay-layout">
      <div className="storm-replay-stage" ref={stage} data-drawing={drawing}>
        <div className="storm-replay-map" ref={container} />
        <canvas className="storm-replay-currents" ref={canvas} aria-hidden="true" />
        <div className="storm-replay-map-title"><span>{area.province.toUpperCase()} / PAKISTAN</span><strong>{area.name}</strong><small>{satellite ? "Satellite context" : "District context"} · illustrative water</small></div>
        <div className="storm-replay-map-tools" data-tour-target="district-replay-layers" role="group" aria-label="Replay map layers"><button type="button" aria-pressed={satellite} onClick={() => { setSatelliteError(false); setSatellite(!satellite); }}><Layers size={14} /> Satellite</button><button type="button" aria-pressed={population} onClick={() => setPopulation(!population)}><MapPinned size={14} /> Population</button><button type="button" aria-pressed={currents} disabled={!available} onClick={() => setCurrents(!currents)}><Waves size={14} /> Currents</button><button type="button" aria-pressed={Boolean(terrain && terrainContext.data)} disabled={!terrainContext.data} title={selection === "jhang" ? "Real elevation hillshade; display lighting is exaggerated" : "Real terrain has been prepared for Jhang only"} onClick={() => setTerrain(!terrain)}><Layers size={14} /> Terrain</button></div>
        <div className="storm-replay-camera" role="group" aria-label="Replay camera"><button type="button" disabled={!ready || !data} onClick={() => camera(false)}><Crosshair size={13} /> Whole district</button><button type="button" disabled={!available} onClick={() => camera(true)}><MousePointer2 size={13} /> River close-up</button></div>
        <div className="storm-replay-map-status"><span className={playing ? "storm-is-playing" : ""}><i />{playing ? "PLAYING" : "PAUSED"}</span><strong>{replayClock(minute)}<small> / 06:00</small></strong><span>Example elapsed time</span></div>
        <div className="storm-replay-map-key"><span><i /> Hypothetical water extent</span><span>Currents are illustrative; direction and speed are unmeasured.</span>{terrain && terrainContext.data && !terrainContext.error && <a href={terrainContext.data.source_url} target="_blank" rel="noreferrer">Terrain: Mapzen / USGS · ~{terrainContext.data.sample_spacing_m_approx} m</a>}</div>
        {(drawing || points.length === 2) && <div className="storm-replay-drawing-hint" role="status">{drawing ? points.length ? "Choose point B on the map · Esc to cancel" : "Choose point A on the map · Esc to cancel" : "Line A–B · see the spatial overlap in the inspector"}</div>}
        {(!ready || !data || mapError) && <div className="storm-replay-map-loading" role="status">{mapError ? <><span>{mapError}</span><button type="button" onClick={retryMap}>Reload map</button></> : loadError ? <><span>District data could not be loaded.</span><button type="button" onClick={() => setAttempt((value) => value + 1)}>Retry district data</button></> : <><LoaderCircle size={18} className="spinning" /> Preparing the replay map…</>}</div>}
      </div>
      <aside className="storm-replay-inspector" aria-label="Storm replay inspector">
        <div className="storm-replay-inspector-header"><span>EVENT INSPECTOR</span><strong>{phase}</strong><small>Constructed six-hour sequence · no observed storm</small></div>
        <div className="storm-replay-metrics">
          <div className="storm-replay-level-metric"><div><span>EXAMPLE SPREAD LEVEL</span><p>Ordinal level · no depth unit</p></div><strong>{data?.supported ? level : "—"}<small> / 5</small></strong></div>
          <ReplayImpactBar kind="population" value={stats?.exposed_population ?? null} maximum={data?.supported ? data.levels[5].exposed_population : null} formattedValue={stats ? approximatePeople(stats.exposed_population) : "Unavailable"} formattedMaximum={data?.supported ? approximatePeople(data.levels[5].exposed_population) : "Unavailable"} />
          <ReplayImpactBar kind="area" value={stats?.flood_area_km2 ?? null} maximum={data?.supported ? data.levels[5].flood_area_km2 : null} formattedValue={stats?.flood_area_km2 == null ? "Unavailable" : `${stats.flood_area_km2.toLocaleString("en-US", { maximumFractionDigits: 1 })} km²`} formattedMaximum={data?.supported && data.levels[5].flood_area_km2 !== null ? `${data.levels[5].flood_area_km2.toLocaleString("en-US", { maximumFractionDigits: 1 })} km²` : "Unavailable"} />
        </div>
        {data?.supported ? <FootprintChart data={data} scenario={scenario} minute={minute} onSeek={seek} /> : <p className="storm-replay-unsupported">{data ? `${data.name}: population context is available; the river footprint and replay are unavailable.` : "Loading selected district…"}</p>}
        <section className="storm-replay-line-inspector" aria-labelledby="replay-line-title"><div className="storm-replay-section-label"><ScanLine size={14} /><h3 id="replay-line-title">DRAW A LINE. EXPLORE THE SPREAD.</h3></div><p>Choose two points on the map to see how much of the line falls inside the current example water extent.</p><div className="storm-replay-line-actions"><button type="button" aria-pressed={drawing} disabled={!available} onClick={() => { stop(); if (drawing) { setDrawing(false); setPoints([]); } else { setPoints([]); setDrawing(true); container.current?.querySelector("canvas")?.focus(); } }}><ScanLine size={14} />{drawing ? "Cancel drawing" : points.length === 2 ? "Draw another line" : "Draw inspection line"}</button>{points.length === 2 && <button type="button" aria-label="Clear inspection line" onClick={() => { setPoints([]); setDrawing(false); }}><X size={14} /></button>}</div>
          {inspection && <div className="storm-replay-line-result" data-wet-km={inspection.wetKm} data-length-km={inspection.lengthKm}><div><span>Line length</span><strong>{inspection.lengthKm.toFixed(2)} km</strong></div><div><span>Approx. length inside water</span><strong>{inspection.wetKm.toFixed(2)} km</strong></div><svg viewBox="0 0 256 22" role="img" aria-label="Line A to B, blue segments intersect example water"><rect x="0" y="4" width="256" height="7" rx="2" fill="#32454e" />{inspection.wet.map((wet, index) => wet && <rect key={index} x={index / 2} y="4" width=".6" height="7" fill="#8edbff" />)}<text x="0" y="21">A</text><text x="256" y="21" textAnchor="end">B</text></svg><small>Spatial overlap only; no flow rate, depth, or velocity estimate.</small></div>}
        </section>
      </aside>
    </div>
    <section className="storm-replay-timeline" aria-label="Storm replay playback"><div className="storm-replay-playback-actions"><button type="button" className="storm-replay-play" disabled={!available || !canAnimate} aria-pressed={playing} onClick={() => { if (playing) stop(); else { setDrawing(false); if (points.length < 2) setPoints([]); if (minute >= REPLAY_MINUTES) setMinute(0); setPlaying(true); } }}>{playing ? <Pause size={17} /> : <Play size={17} />}{playing ? "Pause replay" : "Play replay"}</button><button type="button" aria-label="Restart storm replay" disabled={!available} onClick={() => seek(0)}><RotateCcw size={16} /></button><label>Speed<select aria-label="Storm replay speed" value={speed} onChange={(event) => setSpeed(Number(event.target.value))}>{[.5, 1, 2, 4].map((value) => <option key={value} value={value}>{value}×</option>)}</select></label></div><div className="storm-replay-scrubber"><label htmlFor="storm-replay-minute">EXAMPLE EVENT TIMELINE <output>{replayClock(minute)}</output></label><input id="storm-replay-minute" aria-label="Storm replay elapsed time" aria-valuetext={`${replayClock(minute)} of six hypothetical hours`} type="range" min="0" max={REPLAY_MINUTES} step="1" value={minute} disabled={!available} onChange={(event) => seek(Number(event.target.value))} /><div><span>00:00 · Before</span><button type="button" disabled={!available} onClick={() => seek(REPLAY_PEAK_MINUTE)}>03:18 · Example peak</button><span>06:00 · Retreat</span></div></div></section>
    <div className="storm-replay-notices" role="status">{satelliteError && <p>Satellite imagery could not be loaded. The local map and replay remain available; select Satellite to retry.</p>}{reducedMotion && <p>Your browser prefers reduced motion. Use the timeline for static snapshots; animated playback is disabled.</p>}<p>Hypothetical level {data?.supported ? `0–${peak}` : "0–5"} sequence, not a flood forecast. Areas and population totals cover the selected district, including when zoomed in.</p></div>
    <details className="storm-replay-method"><summary><BookOpen size={15} /> Inputs &amp; Method <span>What this replay shows</span></summary><div><h3>Current version</h3><p>The map uses real district boundaries, approximate OpenStreetMap river references, and modeled WorldPop 2025 population aggregated to a 2 km grid. The six example flood levels are the existing hypothetical river-buffer footprints. Population within each footprint uses the existing fractional-area estimate; NoData cells are excluded.</p><p>The timeline is a hand-authored rise and retreat across six illustrative hours. Lower, moderate, and higher examples peak at levels 2, 3, and 5. These are ordinal levels, with no rainfall, discharge, return period, or calibrated duration attached. The chart shows each saved footprint area, without creating a new forecast.</p><p>The water surface now uses shaded texture, softened banks, and dense persistent trails advected through a smooth artistic field following the river references. Their direction, speed, brightness, and density carry no physical meaning. A drawn line uses 512 midpoint samples to approximate overlap with the existing extent; it cannot measure water crossing the line. Satellite imagery supplies visual context, not live flood observation.</p>{terrainContext.data && <><h3>Real terrain and hydraulic references · Jhang</h3><p>Downloaded <a href={terrainContext.data.source_url} target="_blank" rel="noreferrer">Mapzen / AWS Terrain Tiles</a>, decoded their actual elevations, and aggregated them to approximately {terrainContext.data.sample_spacing_m_approx} m spacing. Elevations across the rectangular study window range from {terrainContext.data.elevation_min_m} to {terrainContext.data.elevation_max_m} m. Terrain enables a real elevation hillshade with {terrainContext.data.hillshade_exaggeration}× lighting exaggeration for this flat plain. These elevations are not aligned to a station gauge datum and do not drive the water footprint or exposure totals.</p><p><a href={`${replayTerrainBase}jhang-dem.tif`} download>Download Jhang elevation GeoTIFF</a> · <a href={`${replayTerrainBase}jhang-metadata.json`} target="_blank" rel="noreferrer">Provenance and source checksums</a></p><p>An official <a href={terrainContext.data.hydraulic_reference.url} target="_blank" rel="noreferrer">FFC Jhang/Bhakkar floodplain map</a> was retrieved as a historical hydraulic reference. It is not a time-varying depth/velocity grid or a current station calibration, and is not used to label the animation as measured or validated.</p></>}{terrainContext.error && <p>The local terrain metadata could not be loaded. The replay remains available.</p>}<h3>Future scope</h3><p>Add detailed channel, levee and drainage geometry, gauge-datum alignment, calibrated rainfall/runoff and 2D hydraulic simulation, time-varying depth and velocity rasters, and historical-event validation before supporting return-period comparisons or flow estimates across a line. Real terrain is currently prepared for Jhang; other districts retain their existing geographic data.</p><p>This view is independent of monitoring readings. Playback creates no alerts or incidents. Monitoring scenario, the 2D comparison, and Cinematic 3D remain available in their existing views.</p></div></details>
  </section>;
}
