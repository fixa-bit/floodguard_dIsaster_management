import { useEffect, useRef, useState, type RefObject } from "react";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map as MapLibreMap, StyleSpecification } from "maplibre-gl";
import type { FeatureCollection } from "geojson";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import districtUrl from "../data/pakistan/pakistan_districts.geojson?compressed";
import { loadMapAsset } from "./mapAssets";
import { riverFocus } from "./simulationCinematicData";
import { previewAreas } from "./tenYearPreviewData";
import type { FloodExposurePreview } from "./outlookFloodExposureData";
import { transectFeature, type Coordinate } from "./stormReplayData";

maplibregl.setWorkerUrl(maplibreWorkerUrl);
const empty: FeatureCollection = { type: "FeatureCollection", features: [] };
const style: StyleSpecification = { version: 8, sources: {}, layers: [{ id: "background", type: "background", paint: { "background-color": "#101f25" } }] };

export function frameReplay(map: MapLibreMap, data: FloodExposurePreview, close: boolean, animate: boolean) {
  const reference = previewAreas.find((area) => area.id === data.id)!.coordinates;
  const center = close ? riverFocus(data, reference) : null;
  map.stop();
  if (center) map.flyTo({ center, zoom: 10.4, pitch: 0, bearing: 0, duration: animate ? 1500 : 0, essential: false });
  else map.fitBounds([[data.bounds[0], data.bounds[1]], [data.bounds[2], data.bounds[3]]], { padding: 40, maxZoom: 10.4, pitch: 0, bearing: 0, duration: animate ? 1000 : 0 });
}

export function useStormReplayMap({ container, data, level, satellite, population, drawing, points, canAnimate, onPoint, onInteract, onSatelliteError }: {
  container: RefObject<HTMLDivElement | null>; data: FloodExposurePreview | null; level: number; satellite: boolean; population: boolean;
  drawing: boolean; points: Coordinate[]; canAnimate: boolean; onPoint: (point: Coordinate) => void; onInteract: () => void; onSatelliteError: () => void;
}) {
  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const live = useRef({ drawing, onPoint, onInteract, onSatelliteError });
  live.current = { drawing, onPoint, onInteract, onSatelliteError };
  const currentArea = useRef("");

  useEffect(() => {
    if (!container.current) return;
    const element = container.current;
    let disposed = false, instance: MapLibreMap | null = null;
    setReady(false); setError(null); currentArea.current = "";
    try {
      instance = new maplibregl.Map({ container: element, style, center: [72.2, 31.1], zoom: 8, minZoom: 3, maxZoom: 13, maxPitch: 0, attributionControl: false, renderWorldCopies: false, cooperativeGestures: true });
      const activeMap = instance;
      activeMap.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
      activeMap.addControl(new maplibregl.ScaleControl({ maxWidth: 100, unit: "metric" }), "bottom-left");
      activeMap.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
      activeMap.getCanvas().setAttribute("aria-label", "Storm replay map; arrow keys pan, plus and minus zoom");
      activeMap.on("load", () => {
        if (disposed) return;
        activeMap.addSource("replay-districts", { type: "geojson", data: empty, attribution: 'District outlines: <a href="https://github.com/parallax-geo/gis_resources_pakistan">Parallax Geo</a>' });
        activeMap.addSource("replay-population", { type: "geojson", data: empty, attribution: 'Population: <a href="https://www.worldpop.org/">WorldPop 2025</a> · CC BY 4.0' });
        activeMap.addSource("replay-water", { type: "geojson", data: empty, attribution: 'Hypothetical flood spread · River references: <a href="https://www.openstreetmap.org/copyright">© OpenStreetMap contributors</a>' });
        activeMap.addSource("replay-rivers", { type: "geojson", data: empty });
        activeMap.addSource("replay-line", { type: "geojson", data: empty });
        activeMap.addLayer({ id: "replay-land", type: "fill", source: "replay-districts", paint: { "fill-color": "#234039", "fill-opacity": .1 } });
        activeMap.addLayer({ id: "replay-population", type: "fill", source: "replay-population", layout: { visibility: "none" }, paint: { "fill-color": ["interpolate", ["linear"], ["get", "density_km2"], 0, "#355d56", 100, "#8d9c60", 500, "#d8bc67", 2000, "#e98d62", 10000, "#ee6077"], "fill-opacity": .65 } });
        activeMap.addLayer({ id: "replay-water-glow", type: "line", source: "replay-water", paint: { "line-color": "#5b97b9", "line-opacity": 0, "line-width": 1 } });
        activeMap.addLayer({ id: "replay-water-fill", type: "fill", source: "replay-water", paint: { "fill-color": "#266eaa", "fill-opacity": .48 } });
        activeMap.addLayer({ id: "replay-water-edge", type: "line", source: "replay-water", paint: { "line-color": "#80b0c7", "line-width": .3, "line-opacity": 0 } });
        activeMap.addLayer({ id: "replay-rivers", type: "line", source: "replay-rivers", paint: { "line-color": "#578dad", "line-width": .7, "line-opacity": .15 } });
        activeMap.addLayer({ id: "replay-boundary", type: "line", source: "replay-districts", paint: { "line-color": "#a8cabe", "line-width": .65, "line-opacity": .3 } });
        activeMap.addLayer({ id: "replay-selected", type: "line", source: "replay-districts", filter: ["==", ["get", "district"], ""], paint: { "line-color": "#89e6ce", "line-width": 1.6, "line-opacity": .9 } });
        activeMap.addLayer({ id: "replay-transect", type: "line", source: "replay-line", filter: ["==", ["geometry-type"], "LineString"], paint: { "line-color": "#ffc2db", "line-width": 2.5, "line-dasharray": [3, 2] } });
        activeMap.addLayer({ id: "replay-endpoints", type: "circle", source: "replay-line", filter: ["==", ["geometry-type"], "Point"], paint: { "circle-radius": 5, "circle-color": "#fff0f5", "circle-stroke-color": "#b44c7b", "circle-stroke-width": 2 } });
        setMap(activeMap); setReady(true); element.dataset.ready = "true";
        loadMapAsset<FeatureCollection>(districtUrl).then((boundaries) => { if (!disposed) (activeMap.getSource("replay-districts") as GeoJSONSource).setData(boundaries); }).catch(() => { /* Selected data and replay remain available without optional surrounding outlines. */ });
      });
      activeMap.on("click", (event) => { if (live.current.drawing) live.current.onPoint([event.lngLat.lng, event.lngLat.lat]); });
      activeMap.on("movestart", (event) => { if ("originalEvent" in event && event.originalEvent) live.current.onInteract(); });
      activeMap.on("move", () => { element.dataset.zoom = activeMap.getZoom().toFixed(3); element.dataset.center = `${activeMap.getCenter().lng.toFixed(5)},${activeMap.getCenter().lat.toFixed(5)}`; });
      activeMap.on("idle", () => { if (activeMap.getLayer("replay-water-fill")) element.dataset.renderedWater = String(activeMap.queryRenderedFeatures({ layers: ["replay-water-fill"] }).length); });
      activeMap.on("error", (event) => {
        if (disposed) return;
        const message = event.error?.message ?? "Map rendering error";
        if (("sourceId" in event && event.sourceId === "replay-imagery") || message.includes("World_Imagery/MapServer/tile/")) live.current.onSatelliteError();
        else if (("sourceId" in event && event.sourceId === "replay-real-terrain") || message.includes("replay-real-terrain") || message.includes("simulation-terrain/")) { element.dataset.terrainError = message; }
        else { element.dataset.mapError = message; live.current.onInteract(); setError("The replay map could not be rendered. Reload it to try again."); }
      });
    } catch { setError("Interactive maps are unavailable in this browser."); }
    const observer = new ResizeObserver(() => { if (element.clientWidth && element.clientHeight) instance?.resize(); });
    observer.observe(element);
    return () => { disposed = true; observer.disconnect(); instance?.remove(); setMap(null); delete element.dataset.ready; };
  }, [container, attempt]);

  useEffect(() => {
    if (!map || !ready) return;
    if (satellite && !map.getSource("replay-imagery")) {
      // Same public imagery service already used by the operational map.
      map.addSource("replay-imagery", { type: "raster", tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"], tileSize: 256, maxzoom: 17, attribution: "Imagery © Esri, Maxar, Earthstar Geographics, and GIS user community" });
      map.addLayer({ id: "replay-imagery", type: "raster", source: "replay-imagery", paint: { "raster-opacity": .85, "raster-saturation": -.25, "raster-brightness-max": .85 } }, "replay-land");
    }
    if (map.getLayer("replay-imagery")) map.setLayoutProperty("replay-imagery", "visibility", satellite ? "visible" : "none");
    map.setPaintProperty("replay-land", "fill-opacity", satellite ? .08 : .75);
    map.setLayoutProperty("replay-population", "visibility", population ? "visible" : "none");
    map.getContainer().dataset.satellite = String(satellite);
    map.getContainer().dataset.population = String(population);
  }, [map, ready, satellite, population]);

  useEffect(() => {
    if (!map || !ready) return;
    (map.getSource("replay-water") as GeoJSONSource).setData(data?.water ?? empty);
    (map.getSource("replay-rivers") as GeoJSONSource).setData(data?.river_lines ?? empty);
    (map.getSource("replay-population") as GeoJSONSource).setData(data?.population ?? empty);
    map.setFilter("replay-selected", ["==", ["get", "district"], data?.name ?? ""]);
    map.getContainer().dataset.area = data?.id ?? "";
    if (data && currentArea.current !== data.id) { frameReplay(map, data, data.supported, false); currentArea.current = data.id; }
  }, [map, ready, data]);

  useEffect(() => {
    if (!map || !ready) return;
    ["replay-water-fill", "replay-water-edge", "replay-water-glow"].forEach((id) => map.setFilter(id, ["<=", ["get", "min_level"], level]));
    map.getContainer().dataset.level = String(level);
  }, [map, ready, level]);

  useEffect(() => {
    if (!map || !ready) return;
    const feature = transectFeature(points);
    (map.getSource("replay-line") as GeoJSONSource).setData({ type: "FeatureCollection", features: [...(feature ? [feature] : []), ...points.map((point) => ({ type: "Feature" as const, properties: {}, geometry: { type: "Point" as const, coordinates: point } }))] });
    map.getCanvas().style.cursor = drawing ? "crosshair" : "";
  }, [map, ready, points, drawing]);

  useEffect(() => { if (!canAnimate) map?.stop(); }, [map, canAnimate]);
  return { map, ready, error, retry: () => setAttempt((value) => value + 1) };
}
