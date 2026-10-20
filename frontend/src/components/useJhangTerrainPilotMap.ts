import { useEffect, useRef, useState, type RefObject } from "react";
import * as maplibregl from "maplibre-gl";
import type { CanvasSource, GeoJSONSource, Map as MapLibreMap, StyleSpecification } from "maplibre-gl";
import type { FeatureCollection } from "geojson";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { pilotAssetBase, type JhangTerrainPilot, type PilotMetadata } from "./jhangTerrainPrototypeData";

maplibregl.setWorkerUrl(maplibreWorkerUrl);
const empty: FeatureCollection = { type: "FeatureCollection", features: [] };
const style: StyleSpecification = { version: 8, sources: {}, layers: [{ id: "background", type: "background", paint: { "background-color": "#16292a" } }] };
function imageCorners([w, s, e, n]: number[]): [[number, number], [number, number], [number, number], [number, number]] { return [[w, n], [e, n], [e, s], [w, s]]; }

export function useJhangTerrainPilotMap({ container, data, metadata, level, floodplain, satellite, terrain, population, paths, onInteract, onImageryError }: {
  container: RefObject<HTMLDivElement | null>; data: JhangTerrainPilot | null; metadata: PilotMetadata | null;
  level: number; floodplain: boolean; satellite: boolean; terrain: boolean; population: boolean; paths: boolean;
  onInteract: () => void; onImageryError: () => void;
}) {
  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [imageError, setImageError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const callbacks = useRef({ onInteract, onImageryError });
  callbacks.current = { onInteract, onImageryError };
  const framed = useRef(false);
  const spreadSource = useRef<CanvasSource | null>(null);
  const spreadPixels = useRef<ImageData | null>(null);
  const controls = useRef({ level, floodplain, paths });
  controls.current = { level, floodplain, paths };
  const [spreadReady, setSpreadReady] = useState(false);
  const [spreadError, setSpreadError] = useState(false);
  useEffect(() => {
    if (!container.current || !data || !metadata) return;
    const element = container.current;
    let active: MapLibreMap | null = null, disposed = false;
    setMap(null); setReady(false); setError(null); setImageError(false); setSpreadReady(false); setSpreadError(false); framed.current = false; spreadSource.current = null; spreadPixels.current = null;
    try {
      active = new maplibregl.Map({ container: element, style, center: [72.265, 31.30], zoom: 11,
        minZoom: 8, maxZoom: 15, maxPitch: 0, renderWorldCopies: false, attributionControl: false, cooperativeGestures: true });
      const instance = active;
      instance.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
      instance.addControl(new maplibregl.ScaleControl({ unit: "metric", maxWidth: 100 }), "bottom-left");
      instance.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
      instance.getCanvas().setAttribute("aria-label", "Jhang terrain prototype map; arrow keys pan, plus and minus zoom");
      instance.on("load", () => {
        if (disposed) return;
        for (const id of ["boundary", "reference", "water", "channels", "paths"]) instance.addSource(`pilot-${id}`, { type: "geojson", data: empty,
          ...(id === "channels" ? { attribution: '<a href="https://www.openstreetmap.org/copyright">© OpenStreetMap contributors</a> · ODbL' } : {}) });
        instance.addLayer({ id: "pilot-land", type: "fill", source: "pilot-boundary", paint: { "fill-color": "#315646", "fill-opacity": .25 } });
        instance.addLayer({ id: "pilot-reference", type: "fill", source: "pilot-reference", paint: { "fill-color": "#739baf", "fill-opacity": .09 } });
        instance.addLayer({ id: "replay-water-fill", type: "fill", source: "pilot-water", paint: { "fill-color": "#55bfe0", "fill-opacity": .48 } });
        instance.addLayer({ id: "pilot-paths", type: "line", source: "pilot-paths", paint: { "line-color": "#c3e9f2", "line-width": 1, "line-opacity": .6, "line-dasharray": [2, 4] } });
        const spreadCanvas = document.createElement("canvas");
        spreadCanvas.width = metadata.grid.width; spreadCanvas.height = metadata.grid.height;
        instance.addSource("pilot-progressive-spread", { type: "canvas", canvas: spreadCanvas, animate: false,
          coordinates: imageCorners([72.18, 31.23, 72.35, 31.37]) });
        instance.addLayer({ id: "pilot-progressive-spread", type: "raster", source: "pilot-progressive-spread",
          paint: { "raster-opacity": .68, "raster-resampling": "linear", "raster-fade-duration": 0 } }, "pilot-paths");
        instance.addLayer({ id: "pilot-canals", type: "line", source: "pilot-channels", filter: ["==", ["get", "waterway"], "canal"], paint: { "line-color": "#e3b17a", "line-width": 1.4, "line-opacity": .9, "line-dasharray": [3, 2] } });
        instance.addLayer({ id: "pilot-river", type: "line", source: "pilot-channels", filter: ["==", ["get", "waterway"], "river"], paint: { "line-color": "#b3e7ef", "line-width": 1.7, "line-opacity": .8 } });
        instance.addLayer({ id: "pilot-boundary", type: "line", source: "pilot-boundary", paint: { "line-color": "#a1cab7", "line-width": 1, "line-opacity": .65, "line-dasharray": [5, 4] } });
        setMap(instance); setReady(true); element.dataset.ready = "true";
      });
      instance.on("movestart", event => { if ("originalEvent" in event && event.originalEvent) callbacks.current.onInteract(); });
      instance.on("move", () => { element.dataset.zoom = instance.getZoom().toFixed(3); });
      instance.on("idle", () => { if (instance.getLayer("replay-water-fill")) element.dataset.renderedWater = String(instance.queryRenderedFeatures({ layers: ["replay-water-fill"] }).length); });
      instance.on("error", event => {
        if (disposed) return;
        const source = "sourceId" in event ? String(event.sourceId) : "";
        const message = event.error?.message ?? "";
        if (source === "pilot-imagery" || message.includes("World_Imagery/MapServer/tile/")) callbacks.current.onImageryError();
        else if (["pilot-terrain", "pilot-population"].includes(source) || message.includes("jhang-terrain-prototype/")) setImageError(true);
        else { callbacks.current.onInteract(); setError("The study map could not render. Reload the map to try again."); }
      });
    } catch { setError("Interactive maps are unavailable in this browser."); }
    const observer = new ResizeObserver(() => { if (element.clientWidth && element.clientHeight) active?.resize(); });
    observer.observe(element);
    return () => { disposed = true; observer.disconnect(); spreadSource.current?.pause(); spreadSource.current = null; spreadPixels.current = null; active?.remove(); delete element.dataset.ready; };
  }, [container, attempt, data, metadata]);
  useEffect(() => {
    if (!map || !ready || !data || !metadata) return;
    for (const [id, value] of [["boundary", data.study_boundary], ["reference", data.reference_extent], ["water", data.stream_corridor], ["channels", data.waterways], ["paths", data.connection_paths]] as const) (map.getSource(`pilot-${id}`) as GeoJSONSource).setData(value);
    const canvasSource = map.getSource("pilot-progressive-spread") as CanvasSource;
    const surface = canvasSource.getCanvas();
    surface.width = metadata.grid.width; surface.height = metadata.grid.height;
    spreadSource.current = canvasSource;
    const image = new Image();
    image.onload = () => {
      if (!map.getSource("pilot-progressive-spread")) return;
      const context = surface.getContext("2d", { willReadFrequently: true });
      if (!context || image.width !== surface.width || image.height !== surface.height) { setSpreadError(true); return; }
      context.drawImage(image, 0, 0, surface.width, surface.height);
      spreadPixels.current = context.getImageData(0, 0, surface.width, surface.height);
      setSpreadReady(true);
    };
    image.onerror = () => setSpreadError(true);
    image.src = pilotAssetBase + "flood-threshold.png";
    for (const [id, url, bounds] of [["pilot-terrain", "terrain.png", data.bounds], ["pilot-population", "population.png", metadata.population_image_bounds]] as const) {
      if (!map.getSource(id)) {
        map.addSource(id, { type: "image", url: pilotAssetBase + url, coordinates: imageCorners([...bounds]) });
        map.addLayer({ id, type: "raster", source: id, paint: { "raster-opacity": id === "pilot-terrain" ? .35 : .75, "raster-fade-duration": 0, "raster-resampling": id === "pilot-population" ? "nearest" : "linear" } }, "pilot-reference");
      }
    }
    if (!framed.current) {
      map.flyTo({ center: [72.262, 31.297], zoom: 12.5, duration: 0 });
      framed.current = true;
    }
  }, [map, ready, data, metadata]);
  useEffect(() => {
    if (!map || !ready || !data || !metadata) return;
    map.setFilter("replay-water-fill", ["<=", ["get", "min_level"], level]);
    map.setFilter("pilot-paths", ["<=", ["get", "min_level"], level]);
    for (const [id, visible] of [["pilot-terrain", terrain], ["pilot-population", population], ["pilot-paths", paths], ["pilot-progressive-spread", floodplain]] as const) if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
    if (satellite && !map.getSource("pilot-imagery")) {
      map.addSource("pilot-imagery", { type: "raster", tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"], tileSize: 256, maxzoom: 17, attribution: 'Imagery © Esri, Maxar, Earthstar Geographics, GIS user community' });
      map.addLayer({ id: "pilot-imagery", type: "raster", source: "pilot-imagery", paint: { "raster-opacity": .9, "raster-saturation": -.15 } }, "pilot-land");
    }
    if (map.getLayer("pilot-imagery")) map.setLayoutProperty("pilot-imagery", "visibility", satellite ? "visible" : "none");
    Object.assign(map.getContainer().dataset, { level: level.toFixed(2), floodplain: String(floodplain), population: String(population), paths: String(paths), satellite: String(satellite) });
  }, [map, ready, data, metadata, level, floodplain, satellite, terrain, population, paths]);
  useEffect(() => {
    const mapSource = spreadSource.current, sourcePixels = spreadPixels.current;
    if (!map || !mapSource || !sourcePixels || !spreadReady) return;
    const surface = mapSource.getCanvas(), context = surface.getContext("2d");
    if (!context) return;
    const image = context.createImageData(surface.width, surface.height);
    let active = 0;
    for (let i = 0; i < sourcePixels.data.length; i += 4) {
      if (controls.current.floodplain && sourcePixels.data[i+3] && (sourcePixels.data[i] || sourcePixels.data[i+1])) {
        const threshold = ((sourcePixels.data[i] << 8) | sourcePixels.data[i+1]) / 65535 * 8;
        if (threshold > 0 && threshold <= level) {
          image.data[i] = 54; image.data[i+1] = 145; image.data[i+2] = 207;
          image.data[i+3] = 155; active++;
        }
      }
    }
    context.putImageData(image, 0, 0);
    map.getContainer().dataset.spreadCells = String(active);
    mapSource.play();
    map.once("render", () => mapSource.pause());
    map.triggerRepaint();
  }, [map, ready, spreadReady, level, floodplain]);
  return { map, ready, error, imageError, spreadReady, spreadError, retry: () => setAttempt(value => value + 1) };
}
