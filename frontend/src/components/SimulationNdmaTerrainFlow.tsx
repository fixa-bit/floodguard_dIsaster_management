import { useEffect, useRef, useState } from "react";
import { Crosshair, Layers, Mountain, Pause, Play, RotateCcw, Waves } from "lucide-react";
import * as maplibregl from "maplibre-gl";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { flowFrame, terrainFlowBase, validateTerrainFlow, type TerrainFlowData } from "./ndmaTerrainFlowData";
import { TerrainFlowRenderer } from "./TerrainFlowRenderer";
import { useOutlookMotion } from "./useOutlookMotion";
import "../simulation-storm-replay.css";
import "../simulation-ndma-flow.css";

maplibregl.setWorkerUrl(maplibreWorkerUrl);
const fixed = (n: number, digits = 2) => n.toLocaleString("en-US", {maximumFractionDigits: digits});
const clock = (seconds: number) => `${String(Math.floor(seconds/3600)).padStart(2,"0")}:${String(Math.floor(seconds%3600/60)).padStart(2,"0")}`;

export function SimulationNdmaTerrainFlow() {
  const [assets, setAssets] = useState<{ data: TerrainFlowData; buffer: ArrayBuffer } | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [map, setMap] = useState<maplibregl.Map | null>(null);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [satellite, setSatellite] = useState(true);
  const [imageryError, setImageryError] = useState(false);
  const [currents, setCurrents] = useState(true);
  const [inView, setInView] = useState(true);
  const [cell, setCell] = useState<number | null>(null);
  const container = useRef<HTMLDivElement>(null), canvas = useRef<HTMLCanvasElement>(null), stage = useRef<HTMLDivElement>(null);
  const renderer = useRef<TerrainFlowRenderer | null>(null);
  const { canAnimate, reducedMotion } = useOutlookMotion(true);
  const data = assets?.data, frame = data?.frames[index];
  const available = Boolean(map && assets && !error);

  useEffect(() => {
    const controller = new AbortController();
    setError(""); setAssets(null);
    const fetchAsset = async (file: string) => {
      const response = await fetch(terrainFlowBase+file, {signal: controller.signal});
      if (!response.ok) throw new Error(`${file} returned HTTP ${response.status}`);
      return response;
    };
    Promise.all([fetchAsset("results.json").then(r => r.json()), fetchAsset("frames.bin.gz").then(async r => {
      const bytes = await r.arrayBuffer();
      if (bytes.byteLength < 2) throw new Error("River grid download was empty");
      const header = new Uint8Array(bytes,0,2);
      // Vite sends Content-Encoding: gzip for public .gz files; fetch has
      // already decoded those. Static hosts may serve the gzip file as-is.
      if (header[0] !== 0x1f || header[1] !== 0x8b) return bytes;
      return new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"))).arrayBuffer();
    })]).then(([result, buffer]) => {
      validateTerrainFlow(result, buffer);
      if (!controller.signal.aborted) {setAssets({data: result, buffer}); setIndex(0); setCell(null);}
    }).catch(cause => {if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "River model data could not load");});
    return () => controller.abort();
  }, [attempt]);

  useEffect(() => {
    if (!container.current || !data || !canvas.current) return;
    const element = container.current;
    const [w,s,e,n] = data.bounds;
    let disposed = false, instance: maplibregl.Map | null = null;
    const fit = () => {
      const [fw,fs,fe,fn] = data.focus_bounds;
      instance?.fitBounds([[fw,fs],[fe,fn]], {padding:35,duration:0});
    };
    try {
      instance = new maplibregl.Map({container: element, style: {version: 8, sources: {}, layers: [{id:"background",type:"background",paint:{"background-color":"#10262c"}}]},
        center: [(w+e)/2,(s+n)/2], zoom: 12, maxPitch: 0, dragRotate: false, touchZoomRotate: true, cooperativeGestures: true, attributionControl: false});
      const active = instance;
      active.touchZoomRotate.disableRotation();
      active.addControl(new maplibregl.NavigationControl({showCompass:false}), "top-right");
      active.addControl(new maplibregl.AttributionControl({compact:true,customAttribution:"Hydraulics and terrain: USACE HEC-RAS Muncie example"}), "bottom-right");
      active.addControl(new maplibregl.ScaleControl(), "bottom-left");
      active.on("load", () => {
        if (disposed) return;
        active.addSource("terrain", {type:"image",url: terrainFlowBase+"terrain.png",coordinates:[[w,n],[e,n],[e,s],[w,s]]});
        active.addLayer({id:"terrain",type:"raster",source:"terrain",paint:{"raster-opacity":1,"raster-fade-duration":0}});
        active.addSource("imagery", {type:"raster",tiles:["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],tileSize:256,attribution:"Imagery © Esri, Maxar, Earthstar Geographics"});
        active.addLayer({id:"imagery",type:"raster",source:"imagery",paint:{"raster-opacity":.85,"raster-saturation":-.3}},"terrain");
        active.addSource("river-boundaries",{type:"geojson",data:{type:"FeatureCollection",features:data.boundary_lines.map(b=>({type:"Feature",properties:{kind:b.kind,label:b.label},geometry:{type:"LineString",coordinates:b.coordinates}}))}});
        active.addLayer({id:"river-boundaries",type:"line",source:"river-boundaries",paint:{"line-width":5,"line-color":["case",["==",["get","kind"],"upstream"],"#ffd08b","#8ce3b5"]}});
        fit(); setMap(active); element.dataset.ready = "true";
      });
      active.on("movestart", event => {if ("originalEvent" in event && event.originalEvent) setPlaying(false);});
      active.on("click", event => {
        const mercY = (lat:number) => Math.log(Math.tan(Math.PI/4+lat*Math.PI/360));
        const col = Math.floor((event.lngLat.lng-w)/(e-w)*data.cols), row = Math.floor((mercY(n)-mercY(event.lngLat.lat))/(mercY(n)-mercY(s))*data.rows);
        if (row>=0 && col>=0 && row<data.rows && col<data.cols) {setCell(row*data.cols+col); setPlaying(false);}
      });
      active.on("error", event => {
        if (disposed) return;
        element.dataset.lastError = JSON.stringify({message:event.error?.message,sourceId:"sourceId" in event ? event.sourceId : null,keys:Object.keys(event),errorKeys:Object.keys(event.error ?? {})});
        if (("sourceId" in event && event.sourceId === "imagery") || event.error?.message?.includes("World_Imagery")) {setImageryError(true);setSatellite(false);}
        else {setError("The terrain map could not render. Retry to reload the local study.");setPlaying(false);}
      });
    } catch {setError("Interactive terrain maps are unavailable in this browser.");}
    const observer = new ResizeObserver(() => instance?.resize()); observer.observe(element);
    return () => {disposed=true;observer.disconnect();renderer.current?.dispose();renderer.current=null;instance?.remove();setMap(null);delete element.dataset.ready;};
  }, [data]);

  useEffect(() => {
    if (!map || !assets || !canvas.current) return;
    try {renderer.current = new TerrainFlowRenderer(canvas.current,map,assets.data,assets.buffer);}
    catch {setError("The water renderer could not start.");}
    return () => {renderer.current?.dispose();renderer.current=null;};
  }, [map,assets]);
  useEffect(() => {renderer.current?.setFrame(index);}, [map,assets,index]);
  useEffect(() => {renderer.current?.setCurrents(currents);}, [map,currents]);
  useEffect(() => {renderer.current?.setRunning(playing && canAnimate && inView);}, [map,playing,canAnimate,inView]);
  useEffect(() => {
    if (!map?.getLayer("imagery")) return;
    map.setLayoutProperty("imagery","visibility",satellite ? "visible" : "none");
    map.setPaintProperty("terrain","raster-opacity",satellite ? .18 : 1);
  }, [map,satellite]);
  useEffect(() => {
    if (!stage.current) return;
    const observer = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting), {threshold:.08});
    observer.observe(stage.current); return () => observer.disconnect();
  }, []);
  useEffect(() => {if (!canAnimate || !inView || !available) setPlaying(false);}, [canAnimate,inView,available]);
  useEffect(() => {
    if (!playing || !data || !canAnimate || !inView) return;
    const timer = window.setInterval(() => setIndex(current => Math.min(data.frames.length-1,current+1)), 1200/speed);
    return () => window.clearInterval(timer);
  }, [playing,data,canAnimate,inView,speed]);
  useEffect(() => {if (data && index>=data.frames.length-1) setPlaying(false);}, [index,data]);
  const selected = assets && cell !== null && assets.data.elevation_m[cell] !== assets.data.terrain_nodata ? flowFrame(assets.data,assets.buffer,index) : null;
  const selectedDepth = selected && cell !== null ? selected.depth[cell]*assets!.data.depth_unit_m : 0;
  const selectedSpeed = selected && cell !== null ? Math.hypot(selected.vx[cell],selected.vy[cell])*assets!.data.velocity_unit_ms : 0;
  const seek = (value: number) => {setPlaying(false);setIndex(value);};
  const closeUp = () => {
    if (!map || !data) return;
    setPlaying(false);
    const [w,s,e,n] = data.focus_bounds;
    map.fitBounds([[w,s],[e,n]],{padding:35,duration:0});
  };
  return <section className="storm-replay ndma-flow" aria-labelledby="ndma-flow-title" data-frame={index} data-playing={playing}>
    <header className="storm-replay-heading"><div><span className="storm-replay-eyebrow"><Mountain size={14}/> WHITE RIVER / HEC-RAS 2D</span><h2 id="ndma-flow-title">From the river, onto the floodplain.</h2><p>Start with water already in the channel. Watch a rising upstream flow move through the river and spread over its banks.</p></div><span className="storm-replay-demo"><i/> USACE example model</span></header>
    <div className="ndma-flow-facts"><span>{data?.sample ?? "Loading river model"}</span><span>Existing channel + floodplain terrain</span><span>{data ? `${data.hydraulic_cells.toLocaleString()} hydraulic cells · ${fixed(data.source_terrain_resolution_m,1)} m source terrain` : "Preparing native results"}</span><strong>USA demonstration · not a Pakistan forecast</strong></div>
    <div className="storm-replay-layout">
      <div className="storm-replay-stage ndma-flow-stage" ref={stage}>
        <div className="storm-replay-map" ref={container}/><canvas className="storm-replay-currents" ref={canvas} aria-hidden="true"/>
        <div className="storm-replay-map-title"><span>MUNCIE / INDIANA, USA</span><strong>White River</strong><small>Native HEC-RAS depths and reconstructed currents</small></div>
        <div className="storm-replay-map-tools" role="group" aria-label="Terrain flow layers"><button type="button" aria-pressed={satellite} onClick={() => {setImageryError(false);setSatellite(!satellite);}}><Layers size={14}/> Satellite</button><button type="button" aria-pressed={currents} onClick={() => setCurrents(!currents)}><Waves size={14}/> Flow trails</button><button type="button" disabled={!map} onClick={closeUp}><Waves size={14}/> Flow close-up</button><button type="button" disabled={!map || !data} onClick={() => {setPlaying(false);if(map && data) map.fitBounds([[data.bounds[0],data.bounds[1]],[data.bounds[2],data.bounds[3]]],{padding:35,duration:0});}}><Crosshair size={14}/> Study area</button></div>
        <div className="ndma-flow-time"><span>{playing ? "PLAYING" : "PAUSED"}</span><strong>{clock(frame?.seconds ?? 0)}</strong><small>Simulated elapsed time</small></div>
        <div className="ndma-flow-key"><span><b/> Upstream river boundary</span><span><b className="ndma-outlet"/> Downstream boundaries</span><span className="ndma-flow-depth"><i/> Depth: 0.1 m → 4 m+</span><span>Click to inspect. Currents display at 60× model speed.</span></div>
        {(!available || error) && <div className="storm-replay-map-loading" role="status">{error ? <><p>{error}</p><button type="button" onClick={() => {setPlaying(false);setAttempt(v=>v+1);}}>Retry terrain flow</button></> : "Loading HEC-RAS river and floodplain results…"}</div>}
      </div>
      <aside className="storm-replay-inspector ndma-flow-inspector" aria-label="Terrain flow inspector">
        <div className="storm-replay-inspector-header"><span>HEC-RAS RIVER HYDRAULICS</span><strong>{clock(frame?.seconds ?? 0)} / {clock(data?.duration_seconds ?? 86400)}</strong><small>Existing wet river · upstream flow · downstream outlets</small></div>
        <dl className="ndma-flow-metrics"><div><dt>Wet area · depth ≥ 0.1 m</dt><dd>{fixed(frame?.wet_area_km2 ?? 0)} <small>km²</small></dd></div><div><dt>Maximum water depth</dt><dd>{fixed(frame?.max_depth_m ?? 0,2)} <small>m</small></dd></div><div><dt>Peak reconstructed speed</dt><dd>{fixed(frame?.max_speed_ms ?? 0,2)} <small>m/s</small></dd></div><div><dt>Upstream river inflow</dt><dd>{fixed(frame?.inflow_m3s ?? 0,1)} <small>m³/s</small></dd></div><div><dt>Additional wet area since start</dt><dd>{fixed(frame?.additional_wet_area_km2 ?? 0)} <small>km²</small></dd></div><div><dt>River water at start</dt><dd>{fixed(data?.frames[0].wet_area_km2 ?? 0)} <small>km²</small></dd></div></dl>
        <div className="ndma-flow-cell"><h3>River and floodplain inspector</h3>{cell !== null && data && selected ? <dl><div><dt>Channel/terrain elevation</dt><dd>{fixed(data.elevation_m[cell],2)} m</dd></div><div><dt>Terrain slope</dt><dd>{fixed(data.slope_degrees[cell],2)}°</dd></div><div><dt>Computed depth</dt><dd>{fixed(selectedDepth,3)} m</dd></div><div><dt>Reconstructed speed</dt><dd>{fixed(selectedSpeed,3)} m/s</dd></div><div><dt>Map pixel</dt><dd>Row {Math.floor(cell/data.cols)+1}, column {cell%data.cols+1}</dd></div></dl> : <p>{cell!==null ? "No channel/terrain data at this location." : "Click the river or floodplain to inspect terrain, depth and reconstructed velocity. Map pixels are finer than hydraulic cells."}</p>}</div>
        <p className="ndma-flow-note">HEC-RAS routes flow through the existing river. Its water surface is mapped against detailed channel and floodplain elevations to find the shoreline.</p>
      </aside>
    </div>
    <section className="storm-replay-timeline" aria-label="Terrain flow playback"><div className="storm-replay-playback-actions"><button type="button" className="storm-replay-play" disabled={!available || !canAnimate} aria-pressed={playing} onClick={() => {if (data && index>=data.frames.length-1) setIndex(0);setPlaying(v=>!v);}}>{playing ? <Pause size={16}/> : <Play size={16}/>} {playing ? "Pause river flood" : "Play river flood"}</button><button type="button" disabled={!available} aria-label="Reset river flood" onClick={() => seek(0)}><RotateCcw size={16}/></button><label>Playback speed<select aria-label="River flood playback speed" value={speed} onChange={event => setSpeed(Number(event.target.value))}>{[.5,1,2,4].map(s=><option key={s} value={s}>{s}×</option>)}</select></label></div><div className="storm-replay-scrubber"><label htmlFor="ndma-flow-time">SIMULATED EVENT TIME<output>{clock(frame?.seconds ?? 0)}</output></label><input id="ndma-flow-time" type="range" aria-label="River flood elapsed time" min={0} max={(data?.frames.length ?? 1)-1} step={1} value={index} disabled={!available} onChange={event => seek(Number(event.target.value))}/><div><span>00:00 · existing river</span><span>12:00 · high river flow</span><span>24:00 · floodplain response</span></div></div></section>
    <div className="storm-replay-notices" role="status">{imageryError && <p>Satellite imagery is unavailable. The saved local terrain and computed water remain visible.</p>}{reducedMotion && <p>Reduced motion is enabled. Use the timeline for static computed snapshots.</p>}<p>White River, Indiana, USA / official USACE example. The river is wet at the start and receives water at its upstream boundary. This demonstration is not a Pakistan flood forecast.</p></div>
    {data && <details className="storm-replay-method"><summary>Inputs &amp; method <span>HEC-RAS channel, boundaries and computed results</span></summary><div>
      <h3>Complete existing-river model</h3><p>{data.sample}. This uses the official USACE Muncie 2025 project with its original channel terrain, hydraulic mesh, roughness and flood boundary conditions. Before the flood, HEC-RAS runs {data.initialization.baseflow_duration_hours} hours at {data.initialization.baseflow_cfs.toLocaleString()} cfs baseflow. The resulting native cell depths and face velocities initialize the rising-flow run, so the river is already flowing throughout the study. Final baseflow hour volume drift: {(data.initialization.final_hour_relative_volume_drift*100).toFixed(4)}%. Inputs, initialization checks and completed native HDF results are retained under models/river_channel_hydraulics.</p>
      <h3>What controls the water</h3><p>{data.solver}. {data.hydraulic_cells.toLocaleString()} hydraulic cells use the original channel and floodplain terrain, roughness and hydraulic property tables. {data.boundaries} The original upstream hydrograph rises from 1,000 to 20,000 cfs (approximately 28.3 to 566.3 m3/s). Water is already present in {data.numerical_checks.initial_wet_cells} hydraulic cells at the start; no interior point source is added.</p>
      <p>Native HEC-RAS result mapping intersects each computed water surface with the original detailed terrain to obtain the shoreline. Source terrain spacing is {fixed(data.source_terrain_resolution_m,2)} m. Native depth map spacing is {fixed(data.map_resolution_m,2)} m; the browser display grid is approximately {fixed(data.dx_m,1)} by {fixed(data.dy_m,1)} m. These fine display pixels do not change the hydraulic mesh resolution. Depths below 0.1 m are hidden.</p>
      <h3>Current animation</h3><p>Directions and speeds are derived by length-weighted least squares from the native signed hydraulic face velocities, then assigned to their original hydraulic cells and clipped to the computed wet extent. This is a reconstructed visualization of cell flow, not a new subcell velocity simulation. Particle travel is accelerated 60x for visibility; timeline speed is independent. Map depths and inspector speeds remain in metres and m/s.</p>
      <p>The 25 native hourly outputs are displayed directly. Additional wet area compares the selected time with the initial wet footprint; it is not an independently mapped flood-damage estimate. The inspector samples the displayed map pixel. Pixels without terrain return no data.</p>
      <h3>Verification and limits</h3><p>The native solver reports successful completion. Export verifies source checksums, finite native values, nonnegative depths, face orientations and an initially wet river. These checks do not establish observed-event accuracy. Native result SHA-256: <code>{data.native_result_sha256}</code>.</p><ul>{data.limitations.map(item=><li key={item}>{item}</li>)}</ul>
      <p><a href={data.source_manifest_url} target="_blank" rel="noreferrer">Official USACE sample manifest</a> / <a href={data.method_url} target="_blank" rel="noreferrer">HEC-RAS hydraulic output documentation</a> / <a href={terrainFlowBase+"results.json"} download>Download model and result manifest</a> / <a href={terrainFlowBase+"frames.bin.gz"} download>Download compressed depth and velocity grids</a></p><p>{data.credit}</p>
    </div></details>}
  </section>;
}
