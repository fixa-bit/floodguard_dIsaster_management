import { useEffect, useMemo, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import type { Map as MapLibreMap, StyleSpecification } from "maplibre-gl";
import type { FeatureCollection, MultiPolygon, Point, Polygon } from "geojson";
import { bbox } from "@turf/bbox";
import { Compass, Crosshair, MapPinned, Pause } from "lucide-react";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import districtUrl from "../data/pakistan/pakistan_districts.geojson?compressed";
import { loadMapAsset } from "./mapAssets";
import { TenYearFloodExposure } from "./TenYearFloodExposure";
import { PREVIEW_BASE_YEAR, previewAreaName, previewAreas, previewPoint, type PreviewAreaId, type PreviewHazard, type PreviewScenario, type PreviewSelection } from "./tenYearPreviewData";

maplibregl.setWorkerUrl(maplibreWorkerUrl);
type Boundaries = FeatureCollection<Polygon | MultiPolygon, { district: string | null; id: string }>;

const mapStyle: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "background", type: "background", paint: { "background-color": "#08191e" } }],
};

function focusArea(map: MapLibreMap, selection: PreviewSelection, boundaries: Boundaries, duration = 0, touring = false) {
  const area = previewAreas.find((item) => item.id === selection);
  const feature = area && boundaries.features.find((item) => item.properties.district === area.name);
  const bounds = feature ? bbox(feature) : [60.7, 23.5, 77.9, 37.2];
  map.getContainer().dataset.focus = selection;
  map.fitBounds([[bounds[0], bounds[1]], [bounds[2], bounds[3]]], { padding: 38, maxZoom: 7, duration, pitch: touring ? 24 : 0, bearing: touring ? -9 : 0, essential: false });
}

const palette = (score: number) => score < 35 ? [50, 141, 130] : score < 65 ? [209, 163, 77] : [212, 115, 100];

export function TenYearComparisonMaps({ selection, hazard, scenario, year, onSelectionChange, motion = false, touring = false, onToggleTour, onInteract }: {
  selection: PreviewSelection;
  hazard: PreviewHazard;
  scenario: PreviewScenario;
  year: number;
  onSelectionChange: (id: PreviewSelection) => void;
  motion?: boolean;
  touring?: boolean;
  onToggleTour: () => void;
  onInteract: () => void;
}) {
  const currentContainer = useRef<HTMLDivElement>(null);
  const futureContainer = useRef<HTMLDivElement>(null);
  const maps = useRef<MapLibreMap[]>([]);
  const [boundaries, setBoundaries] = useState<Boundaries | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const live = useRef({ selection, hazard, scenario, year, motion, touring, onSelectionChange, onInteract });
  live.current = { selection, hazard, scenario, year, motion, touring, onSelectionChange, onInteract };
  const colors = useRef(new Map<string, number[]>());
  const animation = useRef<number | null>(null);
  const lastSelection = useRef(selection);

  useEffect(() => {
    let disposed = false;
    setError(null);
    loadMapAsset<Boundaries>(districtUrl).then((data) => { if (!disposed) setBoundaries(data); }).catch(() => {
      if (!disposed) setError("District outlines could not be loaded. The chart and example values are still available.");
    });
    return () => { disposed = true; };
  }, [attempt]);

  const collections = useMemo(() => {
    if (!boundaries) return [];
    return [PREVIEW_BASE_YEAR, PREVIEW_BASE_YEAR].map(() => ({
      type: "FeatureCollection" as const,
      features: boundaries.features.map((feature) => {
        const area = previewAreas.find((item) => item.name === feature.properties.district);
        return { ...feature, id: feature.properties.id, properties: {
          ...feature.properties, demo_id: area?.id ?? "", is_hypothetical: true,
          has_example: Boolean(area),
        } };
      }),
    }));
  }, [boundaries]);
  const collectionRef = useRef(collections);
  collectionRef.current = collections;

  useEffect(() => {
    if (!boundaries || !currentContainer.current || !futureContainer.current) return;
    setReady(false);
    let synchronizing = false;
    let disposed = false;
    const readyMaps = new Set<MapLibreMap>();
    const resizeObservers: ResizeObserver[] = [];
    const markers: maplibregl.Marker[] = [];
    try {
      [currentContainer.current, futureContainer.current].forEach((container, index) => {
        delete container.dataset.ready;
        const map = new maplibregl.Map({ container, style: mapStyle, center: [69.5, 30.4], zoom: 3.7,
          minZoom: 2, maxZoom: 10, attributionControl: false, renderWorldCopies: false, cooperativeGestures: true });
        maps.current.push(map);
        map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
        map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: 'District outlines: <a href="https://github.com/parallax-geo/gis_resources_pakistan">Parallax Geo</a> · Hypothetical scores' }), "bottom-right");
        map.getCanvas().setAttribute("aria-label", `${index === 0 ? "Current" : "Future"} hypothetical planning map; arrow keys pan and plus or minus zoom`);
        map.on("movestart", (event) => {
          container.dataset.moving = "true";
          if ("originalEvent" in event && event.originalEvent) live.current.onInteract();
        });
        map.on("moveend", () => { container.dataset.moving = "false"; });
        map.on("move", () => {
          container.dataset.zoom = map.getZoom().toFixed(3);
          container.dataset.center = `${map.getCenter().lng.toFixed(4)},${map.getCenter().lat.toFixed(4)}`;
          container.dataset.pitch = map.getPitch().toFixed(2);
          container.dataset.bearing = map.getBearing().toFixed(2);
          if (synchronizing) return;
          synchronizing = true;
          try { maps.current.filter((other) => other !== map).forEach((other) => other.jumpTo({ center: map.getCenter(), zoom: map.getZoom(), bearing: map.getBearing(), pitch: map.getPitch() })); }
          finally { synchronizing = false; }
        });
        map.on("load", () => {
          if (disposed) return;
          map.addSource("preview-districts", { type: "geojson", data: collectionRef.current[index], tolerance: 0.5 });
          map.addLayer({ id: "preview-fill", type: "fill", source: "preview-districts", paint: {
            "fill-color": ["case", ["==", ["get", "has_example"], false], "#1b333a",
              ["coalesce", ["feature-state", "preview_color"], "#d1a34d"]],
            "fill-opacity": 0.85,
          } });
          map.addLayer({ id: "preview-outline", type: "line", source: "preview-districts", paint: { "line-color": "#799c9f", "line-width": 0.65, "line-opacity": 0.5 } });
          map.addLayer({ id: "preview-selected", type: "line", source: "preview-districts", filter: ["==", ["get", "demo_id"], live.current.selection], paint: { "line-color": "#79f5d7", "line-width": 2 } });
          const pins: FeatureCollection<Point> = { type: "FeatureCollection", features: previewAreas.map((area) => ({ type: "Feature", properties: { demo_id: area.id }, geometry: { type: "Point", coordinates: [...area.coordinates] } })) };
          map.addSource("preview-locations", { type: "geojson", data: pins });
          map.addLayer({ id: "preview-pins", type: "circle", source: "preview-locations", paint: { "circle-radius": 4.5, "circle-color": "#e9f9f6", "circle-stroke-width": 1.5, "circle-stroke-color": "#0e353a" } });
          previewAreas.forEach((area, markerIndex) => {
            const element = document.createElement("div");
            element.className = "outlook-map-pulse";
            element.setAttribute("aria-hidden", "true");
            const pulse = document.createElement("i");
            pulse.style.animationDelay = `${markerIndex * -0.38}s`;
            element.appendChild(pulse);
            markers.push(new maplibregl.Marker({ element }).setLngLat([...area.coordinates]).addTo(map));
            const value = previewPoint(area.id, live.current.hazard, live.current.scenario, index === 0 ? PREVIEW_BASE_YEAR : live.current.year).value;
            const target = palette(value);
            colors.current.set(`${index}:${area.id}`, target);
            const id = boundaries.features.find((feature) => feature.properties.district === area.name)?.properties.id;
            if (id) map.setFeatureState({ source: "preview-districts", id }, { preview_color: `rgb(${target.join(",")})`, example_index: value });
          });
          map.on("click", (event) => {
            const hits = map.queryRenderedFeatures(event.point, { layers: ["preview-pins", "preview-fill"] });
            const id = hits.find((hit) => hit.properties.demo_id)?.properties.demo_id as PreviewAreaId | undefined;
            if (id) live.current.onSelectionChange(id);
          });
          map.on("mousemove", (event) => {
            const hits = map.queryRenderedFeatures(event.point, { layers: ["preview-pins", "preview-fill"] });
            map.getCanvas().style.cursor = hits.some((hit) => hit.properties.demo_id) ? "pointer" : "grab";
          });
          focusArea(map, live.current.selection, boundaries, 0, live.current.touring);
          map.once("idle", () => { if (disposed) return; container.dataset.ready = "true"; readyMaps.add(map); if (readyMaps.size === 2) setReady(true); });
        });
        map.on("error", () => { if (!disposed) setError("The map could not be rendered. You can still explore the example chart and values."); });
        const observer = new ResizeObserver(() => {
          if (!container.clientWidth || !container.clientHeight) return;
          map.resize();
          if (map.getLayer("preview-fill")) focusArea(map, live.current.selection, boundaries, 0, live.current.touring);
        });
        observer.observe(container);
        resizeObservers.push(observer);
      });
    } catch {
      setError("Interactive maps are unavailable in this browser. The chart and example values are still available.");
    }
    return () => { disposed = true; if (animation.current !== null) cancelAnimationFrame(animation.current); resizeObservers.forEach((observer) => observer.disconnect()); markers.forEach((marker) => marker.remove()); maps.current.forEach((map) => map.remove()); maps.current = []; colors.current.clear(); };
  }, [boundaries, attempt]);

  useEffect(() => {
    if (!boundaries || !ready) return;
    const targets = maps.current.flatMap((map, index) => previewAreas.map((area) => {
      const id = boundaries.features.find((feature) => feature.properties.district === area.name)?.properties.id;
      const value = previewPoint(area.id, hazard, scenario, index === 0 ? PREVIEW_BASE_YEAR : year).value;
      const target = palette(value);
      const key = `${index}:${area.id}`;
      return { map, id, target, start: colors.current.get(key) ?? target, key, value };
    }));
    const startTime = performance.now();
    const duration = motion ? 750 : 0;
    let lastFrame = -Infinity;
    const frame = (now: number) => {
      const fraction = duration ? Math.min(1, (now - startTime) / duration) : 1;
      if (fraction === 1 || now - lastFrame >= 40) {
        lastFrame = now;
        const eased = fraction * (2 - fraction);
        targets.forEach(({ map, id, target, start, key, value }) => {
          const color = target.map((value, channel) => Math.round(start[channel] + (value - start[channel]) * eased));
          colors.current.set(key, color);
          if (id) map.setFeatureState({ source: "preview-districts", id }, { preview_color: `rgb(${color.join(",")})`, example_index: value });
        });
      }
      animation.current = fraction < 1 ? requestAnimationFrame(frame) : null;
    };
    frame(startTime);
    return () => { if (animation.current !== null) cancelAnimationFrame(animation.current); animation.current = null; };
  }, [boundaries, ready, hazard, scenario, year, motion]);

  useEffect(() => {
    if (!boundaries) return;
    const changed = lastSelection.current !== selection;
    lastSelection.current = selection;
    maps.current.forEach((map) => {
      if (!map.getLayer("preview-selected")) return;
      map.setFilter("preview-selected", ["==", ["get", "demo_id"], selection]);
      map.stop();
      if (changed || touring || !motion) focusArea(map, selection, boundaries, motion ? (touring ? 1800 : 950) : 0, touring);
    });
  }, [selection, boundaries, motion, touring]);

  return <section className="outlook-comparison outlook-panel" aria-labelledby="outlook-map-title" data-example="true" data-motion={motion ? "on" : "off"} data-tour={touring}>
    <header className="outlook-panel-heading"><div><h3 id="outlook-map-title"><MapPinned size={18} aria-hidden="true" /> Current versus future</h3><p>{touring ? `Guided tour · ${previewAreaName(selection)} · hypothetical example` : "Pan or zoom either map. Both views stay synchronized."}</p></div><div className="outlook-map-actions"><button className={`outlook-quiet-button ${touring ? "outlook-tour-active" : ""}`} type="button" disabled={!motion || !ready || Boolean(error)} aria-pressed={touring} onClick={onToggleTour}>{touring ? <Pause size={15} aria-hidden="true" /> : <Compass size={15} aria-hidden="true" />}{touring ? "Stop map tour" : "Start map tour"}</button><button type="button" className="outlook-quiet-button" onClick={() => { onInteract(); if (boundaries) maps.current.forEach((map) => { map.stop(); focusArea(map, "all", boundaries, motion ? 950 : 0); }); }}><Crosshair size={15} aria-hidden="true" /> Reset view</button></div></header>
    <TenYearFloodExposure maps={maps.current} ready={ready} selection={selection} onSelectionChange={onSelectionChange} onInteract={onInteract}>
    <div className="outlook-map-pair">
      {[{ label: "Current example", year: PREVIEW_BASE_YEAR, ref: currentContainer }, { label: "Future example", year, ref: futureContainer }].map((pane) => <section className="outlook-map-pane" key={pane.label} aria-label={`${pane.label} map`}>
        <header><strong>{pane.label} <span>{pane.year}</span></strong><span className="outlook-example-tag">Hypothetical</span></header>
        <div className="outlook-map-canvas" ref={pane.ref} />
        <p className="outlook-map-readout" data-map-example-index={previewPoint(selection, hazard, scenario, pane.year).value}>{previewAreaName(selection)}<strong>{previewPoint(selection, hazard, scenario, pane.year).value.toFixed(1)}<small> example index</small></strong></p>
      </section>)}
    </div>
    {!ready && !error && <p className="outlook-map-message" role="status">Preparing district outlines…</p>}
    {error && <div className="outlook-map-message" role="status"><p>{error}</p><button type="button" className="outlook-quiet-button" onClick={() => { setError(null); setAttempt((value) => value + 1); }}>Retry maps</button></div>}
    <div className="outlook-map-legend outlook-index-legend" aria-label="Hypothetical index legend"><span><i style={{ background: "#328d82" }} /> Lower &lt;35</span><span><i style={{ background: "#d1a34d" }} /> Moderate 35–&lt;65</span><span><i style={{ background: "#d47364" }} /> Higher ≥65</span><span><i style={{ background: "#1b333a" }} /> No example data</span></div>
    <p className="outlook-map-caption outlook-index-caption">Real district outlines; invented scores for eight example areas. Click a colored district or a location dot to select it. District shading does not represent flood extent; use Flood spread to explore example footprints.</p>
    </TenYearFloodExposure>
  </section>;
}
