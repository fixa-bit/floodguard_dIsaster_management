import { useEffect, useRef, useState, type RefObject } from "react";
import { ChevronDown, ChevronUp, Compass, Mountain, ScanEye, X } from "lucide-react";
import * as maplibregl from "maplibre-gl";
import { monitoringSites } from "./monitoringSites";
import { cancelHoldOrbit } from "./monitoringTour";
import { useOutlookMotion } from "./useOutlookMotion";
import { stationCatalogElevation } from "./stationTerrainTiles";
import "../station-terrain.css";

const easeInOutSine = (t: number) => 0.5 - 0.5 * Math.cos(Math.PI * t);
/** Distance in km between two points. */
function distanceKm(from: maplibregl.LngLat, to: [number, number]) {
  return from.distanceTo(new maplibregl.LngLat(to[0], to[1])) / 1000;
}

const sourceId = "station-elevation-dem";
const shadeSourceId = "station-elevation-shade";

const presets = [
  {id:"TARBELA",short:"Tarbela",subtitle:"Indus · reservoir & ridges",zoom:10.7,bearing:-32},
  {id:"MANGLA",short:"Mangla",subtitle:"Jhelum · lake & foothills",zoom:11,bearing:24},
  {id:"MARALA",short:"Marala",subtitle:"Chenab · river plain",zoom:12.1,bearing:-22},
  {id:"TAUNSA",short:"Taunsa",subtitle:"Indus · barrage & channels",zoom:12,bearing:-18},
];

function addStationTerrainSources(map:maplibregl.Map) {
  if (map.getSource(sourceId)) return;
  map.addSource(sourceId,{type:"raster-dem",tiles:["station-dem://{z}/{x}/{y}.png"],tileSize:256,encoding:"terrarium",maxzoom:13,
    attribution:'Elevation: <a href="https://registry.opendata.aws/terrain-tiles/">Terrain Tiles / AWS Open Data</a>'});
  // Independent DEM source caches avoid terrain/hillshade rendering artifacts.
  map.addSource(shadeSourceId,{type:"raster-dem",tiles:["station-dem://{z}/{x}/{y}.png"],tileSize:256,encoding:"terrarium",maxzoom:13});
  map.addLayer({id:"station-terrain-shade",type:"hillshade",source:shadeSourceId,minzoom:6,
    paint:{"hillshade-exaggeration":.28,"hillshade-shadow-color":"#294844","hillshade-highlight-color":"#d7decd","hillshade-accent-color":"#7f9b8a",
      "hillshade-illumination-anchor":"viewport","hillshade-illumination-direction":315}},"ndma-operational-fill");
}

// `monitoring` keeps the cached 3D terrain on while the map's monitoring mode
// tours stations; the monitoring camera, not this studio, drives each stop.
// `birdsEye` (monitoring mode off) opens every chosen station in bird's-eye, framed with
// `padding` so the station sits clear of the details panel. Without `allowRelief` (the Overview)
// the studio offers bird's-eye only: no Relief button and no hillshade relief layer, though the
// tilted view still stands on the 3D terrain.
export function StationTerrainStudio({mapRef,selectedStationId,onSelectStation,onEnter,monitoring=false,birdsEye=false,padding,allowRelief=true,catchmentBounds,hidden=false}: {
  mapRef: RefObject<maplibregl.Map | null>; selectedStationId: string | null; onSelectStation:(id:string)=>void; onEnter:()=>void; monitoring?:boolean;
  birdsEye?:boolean; padding?:()=>maplibregl.PaddingOptions; allowRelief?:boolean;
  /** A station's catchment as [west, south, east, north], shown from above on the way in. */
  catchmentBounds?:(id:string)=>[number,number,number,number] | undefined;
  /** Hide the studio panel (monitoring mode on); it stays mounted so the tour keeps its 3D terrain. */
  hidden?:boolean;
}) {
  const [expanded,setExpanded] = useState(false);
  const [relief,setRelief] = useState(false);
  const [bird,setBird] = useState(false);
  const [active,setActive] = useState("TARBELA");
  const [exaggeration,setExaggeration] = useState(1);
  const [failure,setFailure] = useState(false);
  const [readyMap,setReadyMap] = useState<maplibregl.Map | null>(null);
  const [elevation,setElevation] = useState<number | null>(null);
  const [heading,setHeading] = useState(0);
  const [pitch,setPitch] = useState(0);
  const [terrainReady,setTerrainReady] = useState(false);
  // A bird's-eye journey under way: the terrain stays attached throughout.
  const [journeying,setJourneying] = useState(false);
  const marker = useRef<maplibregl.Marker | null>(null);
  const terrainWasOn = useRef(false);
  // While the studio's own flight to a station is in the air (it may start far out, below zoom 6.5).
  const flying = useRef(false);
  // Each bird's-eye journey has a number; a newer one, or the viewer taking the map, ends the older one.
  const journey = useRef(0);
  const {canAnimate} = useOutlookMotion(true);
  const activeRef = useRef(active); activeRef.current = active;
  const stateRef = useRef({relief,bird,monitoring});stateRef.current={relief,bird,monitoring};
  const activeSite = monitoringSites.features.find(s=>s.properties.id===active);

  useEffect(() => {
    let frame = 0, disposed = false;
    const connect = () => {
      const map = mapRef.current;
      if (disposed) return;
      if (!map?.getLayer("ndma-operational-fill")) {frame=requestAnimationFrame(connect);return;}
      setReadyMap(map);
    };
    connect();
    return () => {disposed=true;cancelAnimationFrame(frame);};
  }, [mapRef]);

  useEffect(() => {
    if (!readyMap) return;
    const map=readyMap;
    let demTilesLoaded=0;
    const update = () => {
      setHeading(Math.round((map.getBearing()+360)%360));setPitch(Math.round(map.getPitch()));
      setTerrainReady(map.getZoom()>=7);
      const site=monitoringSites.features.find(s=>s.properties.id===activeRef.current);
      const demLoaded=demTilesLoaded>0;
      const sampled=site && map.getTerrain() && demLoaded ? map.queryTerrainElevation(site.geometry.coordinates as [number,number]) : null;
      const catalogHeight=stationCatalogElevation(activeRef.current);
      const ground=demLoaded && map.getTerrain() && catalogHeight!==undefined ? catalogHeight : sampled===null ? null : sampled/(map.getTerrain()?.exaggeration ?? 1);
      setElevation(ground===null ? null : Math.round(ground));
      map.getContainer().dataset.terrainLoaded=String(demLoaded);
      map.getContainer().dataset.demTilesLoaded=String(demTilesLoaded);
      map.getContainer().dataset.terrainPitch=map.getPitch().toFixed(1);
      map.getContainer().dataset.terrainBearing=map.getBearing().toFixed(1);
      map.getContainer().dataset.terrainZoom=map.getZoom().toFixed(2);
      if (map.getZoom()<6.5 && stateRef.current.relief && !stateRef.current.monitoring && !flying.current) {setRelief(false);setBird(false);}
    };
    const error = (event:maplibregl.ErrorEvent & {sourceId?:string}) => {
      if (event.sourceId===sourceId || event.sourceId===shadeSourceId || event.error?.message.includes("Elevation tile")) {map.getContainer().dataset.terrainError=event.error?.message;setFailure(true);setRelief(false);setBird(false);}
    };
    let lastSample=0;
    const sampleRenderedTerrain=()=>{const now=performance.now();if(now-lastSample>250){lastSample=now;update();}};
    const onDemContent=(event:maplibregl.MapSourceDataEvent)=>{if((event.sourceId===sourceId || event.sourceId===shadeSourceId) && event.sourceDataType==="content"){demTilesLoaded++;update();}};
    // Other raster layers can keep idle pending when offline. Sample after
    // actual DEM rendering as well, without polling or starting render loops.
    map.on("sourcedata",onDemContent);map.on("render",sampleRenderedTerrain);map.on("moveend",update);map.on("idle",update);map.on("error",error);update();
    return () => {map.off("sourcedata",onDemContent);map.off("render",sampleRenderedTerrain);map.off("moveend",update);map.off("idle",update);map.off("error",error);marker.current?.remove();marker.current=null;};
  }, [readyMap]);

  useEffect(() => {
    if (!readyMap) return;
    const map=readyMap;
    const terrainOn=relief || monitoring;
    // Monitoring flights between distant stations briefly zoom out; keep the
    // terrain attached so the camera does not jump mid-flight.
    const terrainActive=monitoring || (relief && (terrainReady || journeying));
    if (terrainOn) addStationTerrainSources(map);
    // Monitoring mode shows the 3D terrain mesh only; the finer hillshade layer
    // (studio relief) would otherwise pop in tile by tile after every landing.
    if (map.getLayer("station-terrain-shade")) map.setLayoutProperty("station-terrain-shade","visibility",relief && allowRelief ? "visible" : "none");
    // Monitoring stops frame whole catchments (zoomed out), so lift the relief there to keep the 3D evident.
    const heightScale=monitoring ? Math.max(exaggeration,1.6) : exaggeration;
    const current=map.getTerrain();
    if (terrainActive ? current?.source!==sourceId || current.exaggeration!==heightScale : current) map.setTerrain(terrainActive ? {source:sourceId,exaggeration:heightScale} : null);
    map.setSky(((bird && relief) || monitoring) && terrainActive ? {"sky-color":"#a1c6c8","horizon-color":"#d4e4dc","fog-color":"#dce6df","sky-horizon-blend":.7,"horizon-fog-blend":.6,"fog-ground-blend":.3} : {});
    map.getContainer().dataset.stationTerrain=String(terrainActive);
    map.getContainer().dataset.monitoringTerrain=String(monitoring && terrainActive);
    map.getContainer().dataset.terrainExaggeration=String(heightScale);
    // Flatten only as the terrain goes off: re-running for other reasons (terrainReady flips as a
    // camera flight crosses zoom 7) must not cancel that flight with an easeTo.
    const turnedOff=terrainWasOn.current && !terrainOn;
    terrainWasOn.current=terrainOn;
    // (Not while a flight is under way, e.g. out to the top view of Pakistan: it already ends flat.)
    if (turnedOff && map.getPitch()>0 && !map.isMoving()) map.easeTo({pitch:0,bearing:0,duration:canAnimate ? 700 : 0});
  }, [readyMap,relief,bird,exaggeration,canAnimate,terrainReady,monitoring,allowRelief,journeying]);

  function focus(id:string,tilted:boolean) {
    const site=monitoringSites.features.find(s=>s.properties.id===id);
    if (!site || !readyMap) return;
    const preset=presets.find(p=>p.id===id);
    onEnter();
    delete readyMap.getContainer().dataset.terrainError;
    setActive(id);setFailure(false);setRelief(true);setBird(tilted);
    marker.current?.remove();
    const element=document.createElement("div");element.className="terrain-station-beacon";
    const dot=document.createElement("span"), label=document.createElement("strong");label.textContent=site.properties.name;
    element.append(dot,label);
    marker.current=new maplibregl.Marker({element,anchor:"bottom"}).setLngLat(site.geometry.coordinates as [number,number]).addTo(readyMap);
    // Stop any move already running first, so its end is not taken for this flight's.
    readyMap.stop();
    flying.current=true;
    readyMap.once("moveend",()=>{flying.current=false;});
    readyMap.flyTo({center:site.geometry.coordinates as [number,number],zoom:preset?.zoom ?? 11.5,pitch:tilted ? 58 : 0,
      bearing:tilted ? preset?.bearing ?? -25 : 0,duration:canAnimate ? 1500 : 0,essential:false,...(padding ? {padding:padding()} : {})});
    readyMap.getContainer().dataset.terrainStation=id;
  }
  useEffect(() => {
    if (monitoring || !selectedStationId || !monitoringSites.features.some(s=>s.properties.id===selectedStationId)) return;
    // Monitoring mode off: every chosen station opens in bird's-eye (3D relief, tilted).
    if (birdsEye) { if (selectedStationId!==active || !relief || !bird) void journeyTo(selectedStationId); return; }
    if (relief && selectedStationId!==active) focus(selectedStationId,bird);
  }, [selectedStationId, birdsEye, readyMap]);
  const choose = (id:string) => {if (birdsEye) {onSelectStation(id);void journeyTo(id);} else {focus(id,true);onSelectStation(id);}};

  // The viewer dragging, scrolling or pinching the map takes the camera: any journey stops there.
  useEffect(() => {
    if (!readyMap) return;
    const takeOver = (event: { originalEvent?: unknown }) => { if (event.originalEvent) journey.current += 1; };
    readyMap.on("movestart", takeOver);
    return () => { readyMap.off("movestart", takeOver); };
  }, [readyMap]);

  /**
   * A slow, cinematic journey to a station (monitoring mode off, Overview), in three gentle
   * movements that each start and end at rest, so nothing ever jolts: the camera glides out and
   * across to look straight down on the station's whole catchment; lingers there a moment,
   * drifting slightly; then descends into the station's bird's-eye view, tilting as it comes in.
   * The 3D terrain stays attached for the whole journey (switching it on part-way makes the
   * ground jump under the camera).
   */
  async function journeyTo(id:string) {
    const site=monitoringSites.features.find(s=>s.properties.id===id);
    const map=readyMap;
    if (!site || !map) return;
    const preset=presets.find(p=>p.id===id);
    const center=site.geometry.coordinates as [number,number];
    const framing=padding ? {padding:padding()} : {};
    const land={center,zoom:preset?.zoom ?? 11.5,bearing:preset?.bearing ?? -25,pitch:58,...framing};
    onEnter();
    delete map.getContainer().dataset.terrainError;
    setActive(id);setFailure(false);setRelief(true);setBird(true);
    marker.current?.remove();
    const element=document.createElement("div");element.className="terrain-station-beacon";
    const dot=document.createElement("span"), label=document.createElement("strong");label.textContent=site.properties.name;
    element.append(dot,label);
    marker.current=new maplibregl.Marker({element,anchor:"bottom"}).setLngLat(center).addTo(map);
    map.getContainer().dataset.terrainStation=id;
    cancelHoldOrbit();
    map.stop();
    const token=++journey.current;
    if (!canAnimate) { map.jumpTo(land); return; }
    // Attach the terrain before the camera moves, and keep it attached until the journey ends.
    flying.current=true;
    setJourneying(true);
    addStationTerrainSources(map);
    if (map.getTerrain()?.source!==sourceId) map.setTerrain({source:sourceId,exaggeration});
    const move=(start:()=>void)=>new Promise<boolean>((resolve)=>{map.once("moveend",()=>resolve(token===journey.current));start();});
    try {
      const bounds=catchmentBounds?.(id);
      const overview=bounds ? map.cameraForBounds([[bounds[0],bounds[1]],[bounds[2],bounds[3]]],{...framing,bearing:0}) : undefined;
      if (overview?.center && overview.zoom!==undefined) {
        const above={center:overview.center,zoom:overview.zoom,bearing:0,pitch:0,...framing};
        const km=distanceKm(map.getCenter(),[maplibregl.LngLat.convert(overview.center).lng,maplibregl.LngLat.convert(overview.center).lat]);
        map.getContainer().dataset.terrainJourney="catchment";
        // 1. Glide out and across to look straight down on the catchment.
        if (!await move(()=>map.flyTo({...above,curve:1.2,duration:Math.min(6000,Math.max(3800,3200+km*2.2)),easing:easeInOutSine,essential:true}))) return;
        // 2. Linger over it, drifting in a touch, while it is highlighted.
        map.getContainer().dataset.terrainJourney="linger";
        if (!await move(()=>map.easeTo({zoom:overview.zoom!+0.18,...framing,duration:2200,easing:easeInOutSine,essential:true}))) return;
      }
      // 3. Descend into the station's bird's-eye view, tilting and turning as the camera comes in.
      map.getContainer().dataset.terrainJourney="descent";
      await move(()=>map.flyTo({...land,curve:1.05,duration:5200,easing:easeInOutSine,essential:true}));
    } finally {
      if (token===journey.current) { flying.current=false; setJourneying(false); delete map.getContainer().dataset.terrainJourney; }
    }
  }

  /** Bird's-eye on the Overview: tilts the current view in place (or back to flat); it never flies to a station. */
  function tiltInPlace() {
    const map=readyMap;
    if (!map) return;
    journey.current+=1;
    map.stop();
    if (bird) { setBird(false); map.easeTo({pitch:0,bearing:0,duration:canAnimate ? 2200 : 0,easing:easeInOutSine}); return; }
    setBird(true);
    // The 3D ground only where it is worth it (closer in); far out the view simply tilts.
    if (map.getZoom()>=6.5) setRelief(true);
    map.easeTo({pitch:52,duration:canAnimate ? 2600 : 0,easing:easeInOutSine});
  }
  function toggleRelief() {
    if (relief) {setRelief(false);setBird(false);marker.current?.remove();}
    else focus(selectedStationId ?? active,bird);
  }
  if (hidden) return null;
  return <section className={`station-terrain-studio ${expanded ? "is-expanded" : ""}`} aria-label="Station terrain studio">
    <div className="station-terrain-heading"><span className="station-terrain-icon"><Mountain size={18}/></span><button type="button" className="station-terrain-title" aria-expanded={expanded} onClick={()=>setExpanded(v=>!v)}><strong>Terrain studio</strong><small>{relief ? activeSite?.properties.name : monitoring ? "3D terrain on for monitoring mode" : "Explore the river landscape"}</small></button><button type="button" className="station-terrain-expand" aria-label={expanded ? "Collapse terrain studio" : "Expand terrain studio"} onClick={()=>setExpanded(v=>!v)}>{expanded ? <ChevronUp size={15}/> : <ChevronDown size={15}/>}</button></div>
    <div className="station-terrain-modes" role="group" aria-label="Terrain and map perspective">{allowRelief && <button type="button" disabled={!readyMap} aria-pressed={relief} onClick={toggleRelief}><Mountain size={13}/> Relief</button>}<button type="button" disabled={!readyMap} aria-pressed={bird} onClick={()=>{if(birdsEye){tiltInPlace();return;}if(bird){setBird(false);readyMap?.easeTo({pitch:0,bearing:0,duration:canAnimate ? 900 : 0});}else{setExpanded(true);focus(selectedStationId ?? active,true);}}}><ScanEye size={14}/> Bird’s-eye</button><button type="button" className="terrain-north" aria-label="Face north" title="Face north" disabled={!readyMap} onClick={()=>readyMap?.easeTo({bearing:0,duration:canAnimate ? 700 : 0})}><Compass size={15}/></button></div>
    {expanded && <div className="station-terrain-body"><div className="station-terrain-section"><span>SELECT A VIEWPOINT</span><small>River stations</small></div><div className="terrain-station-presets">{presets.map(p=><button type="button" key={p.id} aria-pressed={active===p.id && relief} disabled={!readyMap} onClick={()=>choose(p.id)}><strong>{p.short}</strong><small>{p.subtitle}</small></button>)}</div><div className="station-terrain-readouts"><span><Compass size={12}/> {heading}° heading</span><span>{pitch}° tilt</span><span>{elevation===null ? "Terrain context" : `~${Math.round(elevation)} m elevation`}</span></div>{allowRelief && <label className="terrain-relief-slider"><span>Relief intensity <output>{exaggeration.toFixed(2)}×</output></span><input type="range" aria-label="Terrain visual exaggeration" min="1" max="2" step=".05" value={exaggeration} onChange={e=>setExaggeration(Number(e.target.value))}/></label>}<p className="station-terrain-credit">Real elevation · visual relief only. <a href="https://registry.opendata.aws/terrain-tiles/" target="_blank" rel="noreferrer">Terrain Tiles</a></p><button type="button" className="terrain-return-flat" disabled={!readyMap} onClick={()=>{setBird(false);setRelief(false);marker.current?.remove();readyMap?.easeTo({pitch:0,bearing:0,duration:canAnimate ? 900 : 0});}}><X size={12}/> Return to flat map</button></div>}
    {failure && <p className="terrain-load-note" role="status">Elevation could not load. The flat map remains available; select a viewpoint to retry.</p>}
  </section>;
}
