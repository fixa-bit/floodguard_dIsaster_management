import { MapPinned } from "lucide-react";
import { Popup, type GeoJSONSource, type Map as MapLibreMap, type MapMouseEvent } from "maplibre-gl";
import { useEffect, useRef, type MutableRefObject } from "react";
import { createRoot } from "react-dom/client";
import type { Feature, FeatureCollection, Point, Polygon, MultiPolygon } from "geojson";
import { booleanPointInPolygon } from "@turf/boolean-point-in-polygon";
import { api } from "../services/api";
import { StationInfoCard } from "./StationInfoCard";
import { readStationCard, type StationCardData, type StationHistory } from "./stationInfo";
import { stationPopupPosition } from "./stationPopupPosition";

const pointLayers = ["priority-monitoring-points", "observed-water-stations", "water-bodies"];
const reachLayers = ["water-lines", "river-status-lines"];
const obstacleSelector = ".sidebar,.topbar,.mobile-menu,.map-layer-control,.map-command-overlay,.map-legend,.hourly-analytics-ticker,.district-inspector,.river-station-inspector,.maplibregl-ctrl-top-right";
interface Hit { key: string; card: StationCardData; coordinates: [number, number]; point: boolean }
export interface StationInteraction { hit: (event: MapMouseEvent) => boolean; click: (event: MapMouseEvent) => boolean; close: () => void; refresh: () => void }
interface Options {
  mapRef: MutableRefObject<MapLibreMap | null>; interactionRef: MutableRefObject<StationInteraction | null>;
  pickingRef: MutableRefObject<boolean>; catchment?: Feature<Polygon | MultiPolygon> | null;
  expanded?: boolean; revision: unknown; onPin: (touch: boolean) => void; onInspect: (id: string) => void;
}

export function useStationHover(options: Options) {
  const latest = useRef(options); latest.current = options;
  useEffect(() => {
    const instance = options.mapRef.current;
    if (!instance) return;
    const map = instance;
    const diagnostics = new URLSearchParams(window.location.search).get("mapDiagnostics") === "1";
    let queries = 0; let renders = 0;
    const host = document.createElement("div");
    const root = createRoot(host);
    const popup = new Popup({ anchor: "top-left", closeButton: false, closeOnClick: false, focusAfterOpen: false,
      maxWidth: "none", className: "station-info-popup", subpixelPositioning: true }).setDOMContent(host);
    let current: Hit | null = null; let pinned = false; let pendingKey = "";
    let intent = 0; let leave = 0; let frame = 0; let layoutFrame = 0; let removeTimer = 0;
    let mouseEvent: MapMouseEvent | null = null; let lastTouch = 0; let cardHovered = false; let disposed = false;
    let request: AbortController | null = null; let history: StationHistory | undefined; let historyState: string | undefined;
    let pendingStation = "";
    let lastOffset = "";
    let haloKey = "";
    const cache = new Map<string, { expires: number; value: StationHistory }>();
    const clickHits = new WeakMap<Event, Hit | null>();
    const empty: FeatureCollection = { type: "FeatureCollection", features: [] };
    const keyboard = document.createElement("button");
    keyboard.type = "button"; keyboard.className = "station-point-focus";
    keyboard.setAttribute("aria-label", "Map station points. Arrow keys select a point; Enter pins its card.");
    keyboard.title = "Station points";
    const keyboardRoot = createRoot(keyboard); keyboardRoot.render(<MapPinned size={18} />);
    map.getContainer().append(keyboard);
    const abortDetails = () => {
      if (request) {
        request.abort(); request = null; pendingStation = "";
        if (diagnostics) map.getContainer().dataset.stationHistoryAborts = String(Number(map.getContainer().dataset.stationHistoryAborts ?? 0) + 1);
      }
    };

    const visibleLayers = (ids: string[]) => ids.filter((id) => map.getLayer(id) && map.getLayoutProperty(id, "visibility") !== "none");
    const inside = (coords: number[]) => !latest.current.catchment || booleanPointInPolygon(coords, latest.current.catchment);
    const halo = (hit: Hit | null) => {
      const key = hit?.point ? `${hit.key}:${hit.coordinates.join(",")}` : "";
      if (key === haloKey) return;
      haloKey = key;
      const source = map.getSource("station-hover-halo");
      if (source?.type === "geojson") (source as GeoJSONSource).setData(hit?.point ? { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: hit.coordinates } }] } : empty);
    };
    const decode = (feature: ReturnType<MapLibreMap["queryRenderedFeatures"]>[number], event?: MapMouseEvent): Hit | null => {
      const isPoint = feature.geometry.type === "Point";
      const original = readStationCard(feature.properties);
      if (!original) return null;
      const coordinates = (isPoint ? [original.longitude, original.latitude] : event ? [event.lngLat.wrap().lng, event.lngLat.lat] : []) as [number, number];
      if (coordinates.length !== 2 || !inside(coordinates)) return null;
      const card = isPoint ? original : { ...original, longitude: coordinates[0], latitude: coordinates[1] };
      return card ? { key: `${feature.layer.id}:${card.id}`, card, coordinates, point: isPoint } : null;
    };
    const hitAt = (event: MapMouseEvent) => {
      if (latest.current.pickingRef.current) return null;
      if (clickHits.has(event.originalEvent)) return clickHits.get(event.originalEvent)!;
      const box: [[number, number], [number, number]] = [[event.point.x - 7, event.point.y - 7], [event.point.x + 7, event.point.y + 7]];
      let hit: Hit | null = null;
      for (const ids of [pointLayers, reachLayers]) {
        const layers = visibleLayers(ids);
        if (!layers.length) continue;
        const features = map.queryRenderedFeatures(box, { layers });
        if (diagnostics) map.getContainer().dataset.stationHoverQueries = String(++queries);
        features.sort((a, b) => {
          const distance = (feature: typeof a) => feature.geometry.type === "Point"
            ? map.project((feature.geometry as Point).coordinates as [number, number]).dist(event.point) : 0;
          return distance(a) - distance(b) || ids.indexOf(a.layer.id) - ids.indexOf(b.layer.id);
        });
        for (const feature of features) { hit = decode(feature, event); if (hit) break; }
        if (hit) break;
      }
      clickHits.set(event.originalEvent, hit);
      return hit;
    };
    const close = () => {
      clearTimeout(intent); clearTimeout(leave); clearTimeout(removeTimer); pendingKey = ""; leave = 0;
      abortDetails(); current = null; pinned = false; cardHovered = false;
      history = undefined; historyState = undefined; halo(null);
      if (popup.isOpen()) {
        popup.getElement().style.opacity = "0";
        removeTimer = window.setTimeout(() => popup.remove(), 150);
      }
    };
    const position = () => {
      if (!current || !popup.isOpen() || disposed) return;
      const rect = map.getContainer().getBoundingClientRect();
      const width = Math.min(326, rect.width - 16, window.innerWidth - 16);
      const bounds = { left: Math.max(rect.left, 0) + 8, top: Math.max(rect.top, 0) + 8,
        right: Math.min(rect.right, window.innerWidth) - 8, bottom: Math.min(rect.bottom, window.innerHeight) - 8 };
      const obstacles = [...document.querySelectorAll<HTMLElement>(obstacleSelector)].filter((element) => element.getClientRects().length && getComputedStyle(element).visibility !== "hidden")
        .map((element) => element.getBoundingClientRect()).filter((obstacle) => obstacle.right > bounds.left && obstacle.left < bounds.right && obstacle.bottom > bounds.top && obstacle.top < bounds.bottom);
      const card = host.querySelector<HTMLElement>(".station-info-card");
      if (!card) return;
      card.style.width = `${width}px`;
      const height = Math.min(380, (card.querySelector("header")?.getBoundingClientRect().height ?? 58) + (card.querySelector(".station-info-scroll")?.scrollHeight ?? 240) + 2);
      const projected = map.project(current.coordinates);
      const point = { x: projected.x + rect.left, y: projected.y + rect.top };
      const placement = stationPopupPosition(point, bounds, obstacles, width, height);
      if (!placement) { close(); return; }
      card.style.maxHeight = `${placement.maxHeight}px`;
      const offset: [number, number] = [placement.left - point.x, placement.top - point.y];
      if (offset.join(",") !== lastOffset) { popup.setOffset(offset); lastOffset = offset.join(","); }
      const element = popup.getElement(); element.style.visibility = "visible"; element.style.opacity = "1";
      const tip = card.querySelector<HTMLElement>(".station-info-pointer")!;
      const cx = Math.max(12, Math.min(width - 12, point.x - placement.left));
      const cy = Math.max(12, Math.min(placement.maxHeight - 12, point.y - placement.top));
      const side = point.y < placement.top ? "top" : point.y > placement.top + placement.maxHeight ? "bottom" : point.x < placement.left ? "left" : "right";
      tip.style.left = `${side === "left" ? -5 : side === "right" ? width - 5 : cx - 5}px`;
      tip.style.top = `${side === "top" ? -5 : side === "bottom" ? placement.maxHeight - 5 : cy - 5}px`;
      tip.hidden = Math.hypot(Math.max(placement.left - point.x, 0, point.x - placement.left - width),
        Math.max(placement.top - point.y, 0, point.y - placement.top - placement.maxHeight)) > 100;
    };
    const schedulePosition = () => { cancelAnimationFrame(layoutFrame); layoutFrame = requestAnimationFrame(position); };
    const inspect = () => { const id = current?.card.stationId; close(); if (id) latest.current.onInspect(id); };
    const render = () => {
      if (!current) return;
      if (diagnostics) map.getContainer().dataset.stationCardRenders = String(++renders);
      root.render(<StationInfoCard data={current.card} pinned={pinned} history={history} historyState={historyState}
        onClose={close} onPin={() => { if (current) show(current, true); }} onInspect={inspect} onLayout={schedulePosition} />);
    };
    const loadHistory = async (hit: Hit) => {
      const id = hit.card.stationId;
      if (!id || hit.card.kind === "reference") return;
      if (pendingStation === id) return;
      const cached = cache.get(id);
      if (cached && cached.expires > Date.now()) { history = cached.value; historyState = history.samples.length < 2 ? "No stored history" : undefined; render(); return; }
      abortDetails(); const controller = new AbortController(); request = controller; pendingStation = id;
      historyState = "Loading stored observations..."; render();
      try {
        const value = await api.stationHistory(id, controller.signal);
        if (controller.signal.aborted || disposed) return;
        if (cache.size >= 100) cache.delete(cache.keys().next().value!);
        cache.set(id, { expires: Date.now() + hit.card.intervalMinutes * 60000, value });
        if (current?.key === hit.key && pinned) { history = value; historyState = value.samples.length < 2 ? "No stored history" : undefined; render(); }
      } catch {
        if (!controller.signal.aborted && current?.key === hit.key && pinned) { historyState = "Stored history unavailable"; render(); }
      } finally {
        if (request === controller) { request = null; pendingStation = ""; }
      }
    };
    function show(hit: Hit, pin = false, touch = false) {
      clearTimeout(intent); clearTimeout(leave); leave = 0; clearTimeout(removeTimer); pendingKey = "";
      const changed = current?.key !== hit.key;
      if (changed) { abortDetails(); history = undefined; historyState = undefined; }
      current = hit; pinned = pin;
      popup.setLngLat(hit.coordinates); lastOffset = "";
      if (!popup.isOpen()) { popup.addTo(map); popup.getElement().style.visibility = "hidden"; popup.getElement().style.opacity = "0"; }
      if (changed) halo(hit);
      if (pin) latest.current.onPin(touch);
      render();
      if (pin && (changed || !history)) void loadHistory(hit);
    }
    const scheduleLeave = () => {
      clearTimeout(intent); pendingKey = "";
      if (current && !pinned && !cardHovered && !leave) leave = window.setTimeout(close, 150);
    };
    const move = (event: MapMouseEvent) => {
      if (!window.matchMedia("(hover: hover) and (pointer: fine)").matches || Date.now() - lastTouch < 1000) return;
      mouseEvent = event;
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0; if (!mouseEvent) return;
        const hit = hitAt(mouseEvent);
        if (!latest.current.pickingRef.current) map.getCanvas().style.cursor = hit ? "pointer" : "";
        if (pinned) return;
        if (!hit) { scheduleLeave(); return; }
        clearTimeout(leave); leave = 0;
        if (current?.key === hit.key || pendingKey === hit.key) return;
        clearTimeout(intent); pendingKey = hit.key;
        intent = window.setTimeout(() => show(hit), 120);
      });
    };
    const mouseLeave = () => { mouseEvent = null; cancelAnimationFrame(frame); frame = 0; scheduleLeave(); };
    const enterCard = () => { cardHovered = true; clearTimeout(leave); leave = 0; clearTimeout(intent); pendingKey = ""; };
    const leaveCard = () => { cardHovered = false; scheduleLeave(); };
    host.addEventListener("pointerenter", enterCard); host.addEventListener("pointerleave", leaveCard);
    const touchStart = (event: PointerEvent) => { if (event.pointerType === "touch") lastTouch = Date.now(); };
    map.getContainer().addEventListener("pointerdown", touchStart);
    map.getCanvas().addEventListener("mouseleave", mouseLeave);
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") close(); };
    window.addEventListener("keydown", escape);
    const refresh = () => {
      clickHits.delete(mouseEvent?.originalEvent as Event);
      if (latest.current.pickingRef.current) { close(); return; }
      if (!current) return;
      const layers = visibleLayers([...pointLayers, ...reachLayers]);
      const match = layers.length ? map.queryRenderedFeatures({ layers }).find((feature) => `${feature.layer.id}:${readStationCard(feature.properties)?.id}` === current?.key) : undefined;
      const updated = match ? match.geometry.type === "Point" ? decode(match)
        : inside(current.coordinates) ? { ...current, card: readStationCard(match.properties, current.coordinates)! } : null : null;
      if (!updated) { close(); return; }
      if (JSON.stringify(updated.card) !== JSON.stringify(current.card)) { current = updated; render(); }
      schedulePosition();
    };
    options.interactionRef.current = {
      hit: (event) => Boolean(hitAt(event)), close, refresh,
      click: (event) => { if (latest.current.pickingRef.current) { close(); return false; } const hit = hitAt(event); if (!hit) { close(); return false; } show(hit, true, Date.now() - lastTouch < 1000); return true; },
    };
    const setup = () => {
      if (map.getSource("station-hover-halo")) return;
      map.addSource("station-hover-halo", { type: "geojson", data: empty });
      map.addLayer({ id: "station-hover-halo", type: "circle", source: "station-hover-halo", paint: {
        "circle-radius": 17, "circle-color": "#ffffff", "circle-opacity": 0.12, "circle-stroke-color": "#ffffff", "circle-stroke-width": 2,
      } });
    };
    const keyboardHits = () => {
      const layers = visibleLayers(pointLayers);
      const unique = new Map<string, Hit>();
      for (const feature of layers.length ? map.queryRenderedFeatures({ layers }) : []) {
        const hit = decode(feature);
        if (!hit) continue;
        const point = map.project(hit.coordinates); const rect = map.getContainer().getBoundingClientRect();
        const element = document.elementFromPoint(point.x + rect.left, point.y + rect.top);
        if (element === map.getCanvas() || element === keyboard) unique.set(hit.key, hit);
      }
      return [...unique.values()].sort((a, b) => a.card.name.localeCompare(b.card.name));
    };
    const focusPoint = (hit: Hit) => {
      show(hit); const point = map.project(hit.coordinates);
      keyboard.style.left = `${point.x - 12}px`; keyboard.style.top = `${point.y - 12}px`;
      keyboard.setAttribute("aria-label", `${hit.card.name}. Arrow keys select a point; Enter pins its card.`);
    };
    keyboard.addEventListener("focus", () => { const hits = keyboardHits(); if (hits.length) focusPoint(hits[0]); });
    keyboard.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); event.stopPropagation(); if (current) show(current, true); }
      else if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) {
        event.preventDefault(); event.stopPropagation(); const hits = keyboardHits(); if (!hits.length) return;
        const index = hits.findIndex((hit) => hit.key === current?.key);
        focusPoint(hits[(index + (event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 1) + hits.length) % hits.length]);
      }
    });
    keyboard.addEventListener("blur", () => { if (!pinned) scheduleLeave(); });
    keyboard.addEventListener("click", () => { if (current) show(current, true); });
    const observer = new ResizeObserver(schedulePosition);
    observer.observe(map.getContainer());
    document.querySelectorAll(obstacleSelector).forEach((element) => observer.observe(element));
    map.on("mousemove", move); map.on("move", schedulePosition); map.on("moveend", refresh); map.on("idle", refresh);
    map.on("style.load", setup); if (map.getSource("priority-monitoring")) setup();
    const staleTimer = window.setInterval(() => { if (current) { current = { ...current, card: { ...current.card } }; render(); } }, 30000);
    return () => {
      disposed = true; options.interactionRef.current = null; observer.disconnect(); request?.abort();
      clearTimeout(intent); clearTimeout(leave); clearTimeout(removeTimer); clearInterval(staleTimer);
      cancelAnimationFrame(frame); cancelAnimationFrame(layoutFrame);
      map.off("mousemove", move); map.off("move", schedulePosition); map.off("moveend", refresh); map.off("idle", refresh); map.off("style.load", setup);
      map.getCanvas().removeEventListener("mouseleave", mouseLeave); map.getContainer().removeEventListener("pointerdown", touchStart);
      window.removeEventListener("keydown", escape); popup.remove(); root.unmount(); keyboardRoot.unmount(); keyboard.remove();
    };
  }, [options.mapRef, options.interactionRef, options.expanded]);
  useEffect(() => { options.interactionRef.current?.refresh(); }, [options.revision, options.catchment, options.pickingRef.current]);
}
