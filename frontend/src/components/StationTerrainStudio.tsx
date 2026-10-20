import { useEffect, useRef, useState, type RefObject } from "react";
import { ChevronDown, ChevronUp, Compass, Mountain, ScanEye, X } from "lucide-react";
import * as maplibregl from "maplibre-gl";
import { monitoringSites } from "./monitoringSites";
import { useOutlookMotion } from "./useOutlookMotion";
import "../station-terrain.css";

const base = `${import.meta.env.BASE_URL}station-terrain/`;
const remote = "https://elevation-tiles-prod.s3.amazonaws.com/terrarium/";
const sourceId = "station-elevation-dem";
const shadeSourceId = "station-elevation-shade";
type TileIndex = {tiles: Record<string, unknown>;station_elevations_m?:Record<string,number>};
let indexPromise: Promise<TileIndex> | null = null;
let cachedIndex:TileIndex | null=null;
const tileIndex = () => indexPromise ??= fetch(base+"manifest.json").then(async r => {
  if (!r.ok) throw new Error("Terrain manifest unavailable");
  const result=await r.json() as TileIndex;cachedIndex=result;return result;
}).catch(():TileIndex => ({tiles:{}}));
maplibregl.addProtocol("station-dem",async (params, controller) => {
  const key = params.url.replace("station-dem://","");
  if (!/^\d+\/\d+\/\d+\.png$/.test(key)) throw new Error("Invalid elevation tile request");
  const manifest = await tileIndex();
  try {
    const response=await fetch((manifest.tiles[key] ? base : remote)+key,{signal:controller.signal});
    if(!response.ok)throw new Error(`HTTP ${response.status}`);
    return {data:await response.arrayBuffer()};
  } catch(error) {
    if(controller.signal.aborted)throw error;
    // A tilted view can extend beyond the detailed cache. Use a real cached
    // parent tile there if offline, preserving encoded heights with nearest
    // sampling rather than fabricating flat land or interpolating RGB values.
    const [z,x,y]=key.replace(".png","").split("/").map(Number);
    for(let delta=1;delta<=Math.min(3,z);delta++) {
      const factor=2**delta, parent=`${z-delta}/${Math.floor(x/factor)}/${Math.floor(y/factor)}.png`;
      if(!manifest.tiles[parent])continue;
      const response=await fetch(base+parent,{signal:controller.signal});
      if(!response.ok)continue;
      const bitmap=await createImageBitmap(await response.blob(),{colorSpaceConversion:"none",premultiplyAlpha:"none"});
      const canvas=new OffscreenCanvas(256,256),ctx=canvas.getContext("2d")!;
      ctx.imageSmoothingEnabled=false;
      const size=256/factor;
      ctx.drawImage(bitmap,(x%factor)*size,(y%factor)*size,size,size,0,0,256,256);
      bitmap.close();
      return {data:canvas.transferToImageBitmap()};
    }
    throw new Error(`Elevation tile ${key} unavailable`);
  }
});

const presets = [
  {id:"TARBELA",short:"Tarbela",subtitle:"Indus · reservoir & ridges",zoom:10.7,bearing:-32},
  {id:"MANGLA",short:"Mangla",subtitle:"Jhelum · lake & foothills",zoom:11,bearing:24},
  {id:"MARALA",short:"Marala",subtitle:"Chenab · river plain",zoom:12.1,bearing:-22},
  {id:"TAUNSA",short:"Taunsa",subtitle:"Indus · barrage & channels",zoom:12,bearing:-18},
];

export function StationTerrainStudio({mapRef,selectedStationId,onSelectStation,onEnter}: {
  mapRef: RefObject<maplibregl.Map | null>; selectedStationId: string | null; onSelectStation:(id:string)=>void; onEnter:()=>void;
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
  const marker = useRef<maplibregl.Marker | null>(null);
  const {canAnimate} = useOutlookMotion(true);
  const activeRef = useRef(active); activeRef.current = active;
  const stateRef = useRef({relief,bird});stateRef.current={relief,bird};
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
      const catalogHeight=cachedIndex?.station_elevations_m?.[activeRef.current];
      const ground=demLoaded && map.getTerrain() && catalogHeight!==undefined ? catalogHeight : sampled===null ? null : sampled/(map.getTerrain()?.exaggeration ?? 1);
      setElevation(ground===null ? null : Math.round(ground));
      map.getContainer().dataset.terrainLoaded=String(demLoaded);
      map.getContainer().dataset.demTilesLoaded=String(demTilesLoaded);
      map.getContainer().dataset.terrainPitch=map.getPitch().toFixed(1);
      map.getContainer().dataset.terrainBearing=map.getBearing().toFixed(1);
      if (map.getZoom()<6.5 && stateRef.current.relief) {setRelief(false);setBird(false);}
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
    if (relief && !map.getSource(sourceId)) {
      map.addSource(sourceId,{type:"raster-dem",tiles:["station-dem://{z}/{x}/{y}.png"],tileSize:256,encoding:"terrarium",maxzoom:13,
        attribution:'Elevation: <a href="https://registry.opendata.aws/terrain-tiles/">Terrain Tiles / AWS Open Data</a>'});
      // Independent DEM source caches avoid terrain/hillshade rendering artifacts.
      map.addSource(shadeSourceId,{type:"raster-dem",tiles:["station-dem://{z}/{x}/{y}.png"],tileSize:256,encoding:"terrarium",maxzoom:13});
      map.addLayer({id:"station-terrain-shade",type:"hillshade",source:shadeSourceId,minzoom:6,
        paint:{"hillshade-exaggeration":.28,"hillshade-shadow-color":"#294844","hillshade-highlight-color":"#d7decd","hillshade-accent-color":"#7f9b8a",
          "hillshade-illumination-anchor":"viewport","hillshade-illumination-direction":315}},"ndma-operational-fill");
    }
    if (map.getLayer("station-terrain-shade")) map.setLayoutProperty("station-terrain-shade","visibility",relief ? "visible" : "none");
    map.setTerrain(relief && terrainReady ? {source:sourceId,exaggeration} : null);
    map.setSky(bird && relief && terrainReady ? {"sky-color":"#a1c6c8","horizon-color":"#d4e4dc","fog-color":"#dce6df","sky-horizon-blend":.7,"horizon-fog-blend":.6,"fog-ground-blend":.3} : {});
    map.getContainer().dataset.stationTerrain=String(relief && terrainReady);
    map.getContainer().dataset.terrainExaggeration=String(exaggeration);
    if (!relief && map.getPitch()>0) map.easeTo({pitch:0,bearing:0,duration:canAnimate ? 700 : 0});
  }, [readyMap,relief,bird,exaggeration,canAnimate,terrainReady]);

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
    readyMap.flyTo({center:site.geometry.coordinates as [number,number],zoom:preset?.zoom ?? 11.5,pitch:tilted ? 58 : 0,
      bearing:tilted ? preset?.bearing ?? -25 : 0,duration:canAnimate ? 1500 : 0,essential:false});
    readyMap.getContainer().dataset.terrainStation=id;
  }
  useEffect(() => {
    if (relief && selectedStationId && selectedStationId!==active && monitoringSites.features.some(s=>s.properties.id===selectedStationId)) focus(selectedStationId,bird);
  }, [selectedStationId]);
  const choose = (id:string) => {focus(id,true);onSelectStation(id);};
  function toggleRelief() {
    if (relief) {setRelief(false);setBird(false);marker.current?.remove();}
    else focus(selectedStationId ?? active,bird);
  }
  return <section className={`station-terrain-studio ${expanded ? "is-expanded" : ""}`} aria-label="Station terrain studio">
    <div className="station-terrain-heading"><span className="station-terrain-icon"><Mountain size={18}/></span><button type="button" className="station-terrain-title" aria-expanded={expanded} onClick={()=>setExpanded(v=>!v)}><strong>Terrain studio</strong><small>{relief ? activeSite?.properties.name : "Explore the river landscape"}</small></button><button type="button" className="station-terrain-expand" aria-label={expanded ? "Collapse terrain studio" : "Expand terrain studio"} onClick={()=>setExpanded(v=>!v)}>{expanded ? <ChevronUp size={15}/> : <ChevronDown size={15}/>}</button></div>
    <div className="station-terrain-modes" role="group" aria-label="Terrain and map perspective"><button type="button" disabled={!readyMap} aria-pressed={relief} onClick={toggleRelief}><Mountain size={13}/> Relief</button><button type="button" disabled={!readyMap} aria-pressed={bird} onClick={()=>{if(bird){setBird(false);readyMap?.easeTo({pitch:0,bearing:0,duration:canAnimate ? 900 : 0});}else{setExpanded(true);focus(selectedStationId ?? active,true);}}}><ScanEye size={14}/> Bird’s-eye</button><button type="button" className="terrain-north" aria-label="Face north" title="Face north" disabled={!readyMap} onClick={()=>readyMap?.easeTo({bearing:0,duration:canAnimate ? 700 : 0})}><Compass size={15}/></button></div>
    {expanded && <div className="station-terrain-body"><div className="station-terrain-section"><span>SELECT A VIEWPOINT</span><small>River stations</small></div><div className="terrain-station-presets">{presets.map(p=><button type="button" key={p.id} aria-pressed={active===p.id && relief} disabled={!readyMap} onClick={()=>choose(p.id)}><strong>{p.short}</strong><small>{p.subtitle}</small></button>)}</div><div className="station-terrain-readouts"><span><Compass size={12}/> {heading}° heading</span><span>{pitch}° tilt</span><span>{elevation===null ? "Terrain context" : `~${Math.round(elevation)} m elevation`}</span></div><label className="terrain-relief-slider"><span>Relief intensity <output>{exaggeration.toFixed(2)}×</output></span><input type="range" aria-label="Terrain visual exaggeration" min="1" max="2" step=".05" value={exaggeration} onChange={e=>setExaggeration(Number(e.target.value))}/></label><p className="station-terrain-credit">Real elevation · visual relief only. <a href="https://registry.opendata.aws/terrain-tiles/" target="_blank" rel="noreferrer">Terrain Tiles</a></p><button type="button" className="terrain-return-flat" disabled={!readyMap} onClick={()=>{setBird(false);setRelief(false);marker.current?.remove();readyMap?.easeTo({pitch:0,bearing:0,duration:canAnimate ? 900 : 0});}}><X size={12}/> Return to flat map</button></div>}
    {failure && <p className="terrain-load-note" role="status">Elevation could not load. The flat map remains available; select a viewpoint to retry.</p>}
  </section>;
}
