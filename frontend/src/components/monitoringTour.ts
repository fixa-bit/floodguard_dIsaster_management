import type { FlyToOptions, Map as MapLibreMap, PaddingOptions } from "maplibre-gl";
import { preloadImageryTiles } from "./imageryTiles";
import { preloadTerrainTiles } from "./stationTerrainTiles";

// Cinematic camera for monitoring mode. Each hop is one continuous flight: the
// camera lifts off and rises until the next station is in view, easing to a
// flatter overview tilt and banking toward the direction of travel, then lands
// in a tilted 3D view framing the station's whole catchment, facing the way it
// arrived. While a stop is held the camera orbits slowly. Tiles for the next
// hop are preloaded during the stop.

/** `catchment` is the station's catchment bounding box [west, south, east, north]. */
export interface TourStation { id: string; longitude: number; latitude: number; catchment?: [number, number, number, number] }

const closeZoom = 10;     // stop zoom for a station without a known catchment
const minStopZoom = 5.6, maxStopZoom = 9.6;
const cruisePitch = 30;   // tilt at the top of the arc, so the overview reads like a map
const maxBank = 22;       // how far the camera turns toward the travel direction mid-flight
const arrivalTurn = 20;   // landing bearing for a due east or west arrival
// Smootherstep has zero velocity and acceleration at both ends: a soft lift-off and touchdown.
const smootherstep = (t: number) => t * t * t * (t * (t * 6 - 15) + 10);
const easeInOutSine = (t: number) => (1 - Math.cos(Math.PI * t)) / 2;
const imagerySourceId = "global-satellite-basemap";
const diagnostics = new URLSearchParams(window.location.search).get("mapDiagnostics") === "1";

/** Keeps the station clear of the map controls (left) and station details panel (right). */
export function stationCameraPadding(map: MapLibreMap): Required<PaddingOptions> {
  const containerWidth = map.getContainer().clientWidth;
  const mobile = containerWidth < 700;
  const panelWidth = Math.min(620, containerWidth * 0.42);
  const panelRightInset = Math.max(40, Math.min(96, containerWidth * 0.05));
  return { top: mobile ? 120 : 185, bottom: mobile ? 55 : 90, left: mobile ? 16 : 230, right: mobile ? 16 : panelWidth + panelRightInset + 24 };
}

const mercator = (longitude: number, latitude: number): [number, number] =>
  [(longitude + 180) / 360, (1 - Math.asinh(Math.tan(latitude * Math.PI / 180)) / Math.PI) / 2];
const wrap = (degrees: number) => ((degrees % 360) + 540) % 360 - 180;
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

/** Compass heading of travel (0 = north, 90 = east), or null when the points coincide. */
function travelHeading(from: [number, number], to: [number, number]) {
  const [x0, y0] = mercator(...from), [x1, y1] = mercator(...to);
  return Math.hypot(x1 - x0, y1 - y0) < 1e-7 ? null : Math.atan2(x1 - x0, y0 - y1) * 180 / Math.PI;
}

/** Landing bearing: turned toward the east/west part of the arrival direction, so the map never flips. */
function arrivalBearing(from: [number, number] | null, to: [number, number]) {
  const direction = from ? travelHeading(from, to) : null;
  return direction === null ? arrivalTurn * 0.9 : arrivalTurn * Math.sin(direction * Math.PI / 180);
}

/**
 * The stop view: the station's whole catchment in frame beside the details
 * panel, tilted so the 3D relief reads. The centre sits a third of the way from
 * the catchment's middle toward the station, so stations sharing one large
 * basin still get their own view.
 */
function stopCamera(map: MapLibreMap, station: TourStation, from: [number, number] | null) {
  const padding = stationCameraPadding(map);
  const { clientWidth: width, clientHeight: height } = map.getContainer();
  const point: [number, number] = [station.longitude, station.latitude];
  let center = point, zoom = closeZoom;
  if (station.catchment) {
    const [west, south, east, north] = station.catchment;
    const middle: [number, number] = [(west + east) / 2, (south + north) / 2];
    center = [middle[0] + (point[0] - middle[0]) * 0.35, middle[1] + (point[1] - middle[1]) * 0.35];
    const [cx, cy] = mercator(...center);
    const extent = [mercator(west, south), mercator(east, north), mercator(...point)];
    const halfX = Math.max(...extent.map(([x]) => Math.abs(x - cx))) * 512, halfY = Math.max(...extent.map(([, y]) => Math.abs(y - cy))) * 512;
    const freeX = Math.max(80, (width - padding.left - padding.right) / 2), freeY = Math.max(80, (height - padding.top - padding.bottom) / 2);
    // A tilted view pushes the near edge outward, so leave some room to keep the whole catchment in frame.
    zoom = clamp(Math.log2(Math.min(freeX / Math.max(halfX, 1e-9), freeY / Math.max(halfY, 1e-9))) - 0.35, minStopZoom, maxStopZoom);
  }
  return { center, zoom, pitch: width < 700 ? 42 : 50, bearing: arrivalBearing(from, center), padding };
}

/** Zoom at which the hop's start and end both sit comfortably inside the free map area. */
function overviewZoom(map: MapLibreMap, from: [number, number], to: [number, number]) {
  const padding = stationCameraPadding(map);
  const { clientWidth: width, clientHeight: height } = map.getContainer();
  const free = Math.max(160, Math.min(width - padding.left - padding.right, height - padding.top - padding.bottom));
  const [x0, y0] = mercator(...from), [x1, y1] = mercator(...to);
  const distance = Math.hypot(x1 - x0, y1 - y0) * 512;
  const fit = distance > 0 ? Math.log2(0.42 * free / distance) : closeZoom;
  return Math.min(closeZoom - 1.6, Math.max(4.8, fit));
}

/** Runs one camera move; resolves false if something else (user, another move) interrupted it. */
function cameraStep(map: MapLibreMap, step: FlyToOptions & { center: [number, number]; zoom: number; duration: number }, fly = false) {
  return new Promise<boolean>((resolve) => {
    const started = performance.now();
    const settle = () => {
      if (map.isMoving()) { map.once("moveend", settle); return; }
      // With terrain the map re-anchors its center to the ground when a move ends,
      // so judge completion by time: a move that ends early was interrupted.
      resolve(performance.now() - started >= step.duration - 40);
    };
    if (fly) map.flyTo({ ...step, essential: true });
    else map.easeTo({ ...step, essential: true });
    if (!map.isMoving()) settle();
    else map.once("moveend", settle);
  });
}

/**
 * One continuous flight to the stop. flyTo draws the smooth rise-and-descend
 * path; a per-frame camera hook shapes tilt (dipping to an overview at the top
 * of the arc) and heading (banking toward the travel direction) along it.
 */
async function cinematicFlight(map: MapLibreMap, stop: ReturnType<typeof stopCamera>) {
  const here = map.getCenter().toArray() as [number, number];
  const startZoom = map.getZoom(), startPitch = map.getPitch(), startBearing = map.getBearing();
  const apex = Math.min(overviewZoom(map, here, stop.center), Math.max(startZoom, stop.zoom) - 1.2);
  const climb = Math.max(0, startZoom - apex) + Math.max(0, stop.zoom - apex);
  const duration = clamp(2600 + climb * 420, 4000, 8000);
  const turn = wrap(stop.bearing - startBearing);
  const direction = travelHeading(here, stop.center);
  const bank = direction === null ? 0 : clamp(wrap(direction - (startBearing + turn / 2)) * 0.35, -maxBank, maxBank);
  const dip = Math.max(0, (startPitch + stop.pitch) / 2 - cruisePitch);
  const began = performance.now();
  map.setTransformCameraUpdate(() => {
    const k = smootherstep(clamp((performance.now() - began) / duration, 0, 1)), arc = Math.sin(Math.PI * k);
    return { pitch: startPitch + (stop.pitch - startPitch) * k - dip * arc, bearing: startBearing + turn * k + bank * arc };
  });
  try {
    return await cameraStep(map, { ...stop, minZoom: apex, duration, easing: smootherstep }, true);
  } finally {
    map.setTransformCameraUpdate(null);
  }
}

/** A slow drone orbit while a stop is held; skipped when the viewer prefers reduced motion. */
function holdOrbit(map: MapLibreMap, stop: ReturnType<typeof stopCamera>) {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  map.easeTo({ bearing: stop.bearing + Math.sign(stop.bearing || 1) * 8, zoom: stop.zoom + 0.12, duration: 9500, easing: easeInOutSine, essential: true });
}

/**
 * Flies the camera to a monitoring stop from wherever it is, then starts the
 * hold orbit. Stops early once `isCurrent()` turns false; resolves true when
 * the camera actually landed at the stop.
 */
export async function runMonitoringHop(map: MapLibreMap, station: TourStation, isCurrent: () => boolean) {
  const stop = stopCamera(map, station, map.getCenter().toArray() as [number, number]);
  const landed = await cinematicFlight(map, stop) && isCurrent();
  if (landed) {
    measureStopFootprint(map);
    holdOrbit(map, stop);
  }
  return landed;
}

// Every stop uses the same tilt and padding; only its centre, zoom and bearing
// differ. In Web Mercator a view's tile footprint keeps its shape when moved and
// scales with zoom, so the tiles the map needed at this stop (as offsets from
// the camera centre) predict the next stop's tiles once shifted to its zoom and
// rotated by the bearing difference.
type TileOffset = [z: number, dx: number, dy: number];
let stopFootprint: { zoom: number; bearing: number; terrain: TileOffset[]; detail: TileOffset[] } | null = null;

function measureStopFootprint(map: MapLibreMap) {
  const [originX, originY] = mercator(...(map.getCenter().toArray() as [number, number]));
  const offsets = (tileSize: number, roundZoom: boolean) => map.coveringTiles({ tileSize, roundZoom, maxzoom: 13 })
    .map(({ canonical: { z, x, y } }): TileOffset => [z, x + 0.5 - originX * 2 ** z, y + 0.5 - originY * 2 ** z]);
  // Terrain meshes load 512 px DEM tiles (floored zoom); hillshade and imagery load 256 px tiles (rounded zoom).
  stopFootprint = { zoom: map.getZoom(), bearing: map.getBearing(), terrain: offsets(512, false), detail: offsets(256, true) };
}

/** The measured footprint moved to `target`, rescaled by `zoomChange` and rotated by `turnDegrees`. */
function footprintKeys(offsets: TileOffset[], target: [number, number], turnDegrees: number, zoomChange: number) {
  const turn = turnDegrees * Math.PI / 180, cos = Math.cos(turn), sin = Math.sin(turn), keys = new Set<string>();
  const levelShift = Math.round(zoomChange), stretch = 2 ** (levelShift - zoomChange);
  for (const [measuredZ, measuredX, measuredY] of offsets) {
    const z = measuredZ + levelShift;
    if (z < 0 || z > 13) continue;
    const scale = 2 ** z, dx = measuredX * stretch, dy = measuredY * stretch;
    // Sample each tile's corners so the shifted, rotated footprint has no gaps.
    for (const [sx, sy] of [[-0.45, -0.45], [0.45, -0.45], [-0.45, 0.45], [0.45, 0.45]]) {
      const ox = dx + sx, oy = dy + sy;
      const x = Math.floor(target[0] * scale + ox * cos - oy * sin), y = Math.floor(target[1] * scale + ox * sin + oy * cos);
      if (y >= 0 && y < scale) keys.add(`${z}/${(x % scale + scale) % scale}/${y}`);
    }
  }
  return [...keys];
}

/** Tiles covering the whole map canvas around a stop at zoom level `z` (used for the descent). */
function screenTiles(map: MapLibreMap, target: [number, number], z: number, tileSize: number) {
  const padding = stationCameraPadding(map), { clientWidth: width, clientHeight: height } = map.getContainer();
  const scale = 2 ** z;
  const centerX = target[0] * scale + (padding.right - padding.left) / 2 / tileSize;
  const centerY = target[1] * scale + (padding.bottom - padding.top) / 2 / tileSize;
  const halfX = width / 2 / tileSize, halfY = height / 2 / tileSize;
  return tilesInBox((centerX - halfX) / scale, (centerY - halfY) / scale, (centerX + halfX) / scale, (centerY + halfY) / scale, z);
}

function tilesAround(point: [number, number], z: number, radius: number) {
  const scale = 2 ** z, x = Math.floor(point[0] * scale), y = Math.floor(point[1] * scale), keys: string[] = [];
  for (let dx = -radius; dx <= radius; dx++) for (let dy = -radius; dy <= radius; dy++) {
    if (y + dy >= 0 && y + dy < scale) keys.push(`${z}/${(x + dx + scale) % scale}/${y + dy}`);
  }
  return keys;
}

function tilesInBox(minX: number, minY: number, maxX: number, maxY: number, z: number, limit = 120) {
  const scale = 2 ** z, keys: string[] = [];
  for (let x = Math.floor(minX * scale); x <= Math.floor(maxX * scale); x++) {
    for (let y = Math.max(0, Math.floor(minY * scale)); y <= Math.min(scale - 1, Math.floor(maxY * scale)); y++) {
      if (keys.length >= limit) return keys;
      keys.push(`${z}/${(x + scale) % scale}/${y}`);
    }
  }
  return keys;
}

/** Imagery goes through the persistent imagery cache, so the map's own requests are served locally. */
function preloadImagery(map: MapLibreMap, keys: string[], concurrency = 12) {
  const satellite = map.getLayer(imagerySourceId) && map.getLayoutProperty(imagerySourceId, "visibility") !== "none";
  return satellite ? preloadImageryTiles(keys, concurrency) : Promise.resolve();
}

const png = (keys: string[]) => keys.map((key) => `${key}.png`);
/** Nearest tiles first, so the area around the station is ready soonest. */
function byDistance(keys: string[], target: [number, number]) {
  const distance = (key: string) => {
    const [z, x, y] = key.split("/").map(Number), scale = 2 ** z;
    return Math.hypot(x + 0.5 - target[0] * scale, y + 0.5 - target[1] * scale) / scale;
  };
  return keys.map((key) => [distance(key), key] as const).sort((a, b) => a[0] - b[0]).map(([, key]) => key);
}

/** Where the camera will be at `to` when flying in from `from`: the stop camera and its Mercator centre. */
function plannedStop(map: MapLibreMap, from: TourStation | null, to: TourStation) {
  const previous = from ? stopCamera(map, from, null) : null;
  const stop = stopCamera(map, to, previous ? previous.center : null);
  return { previous, stop, target: mercator(...stop.center) };
}

/** Tiles the stop view will need: the measured footprint moved there, or rings around it before any landing. */
function stopTiles(stop: ReturnType<typeof stopCamera>, target: [number, number]) {
  if (!stopFootprint) {
    const z = Math.floor(stop.zoom);
    return { terrain: [...tilesAround(target, z - 1, 1), ...tilesAround(target, z, 2)], detail: [...tilesAround(target, z + 1, 3), ...tilesAround(target, z + 2, 2)] };
  }
  const turn = stop.bearing - stopFootprint.bearing, zoomChange = stop.zoom - stopFootprint.zoom;
  return { terrain: footprintKeys(stopFootprint.terrain, target, turn, zoomChange), detail: footprintKeys(stopFootprint.detail, target, turn, zoomChange) };
}

/**
 * Preloads elevation and imagery for the hop from one stop to the next. The
 * returned promise settles once the destination stop and the overview are
 * loaded; tiles for the descent between them keep loading afterwards.
 */
export function preloadMonitoringHop(map: MapLibreMap, from: TourStation | null, to: TourStation) {
  const { previous, stop, target } = plannedStop(map, from, to);
  const tiles = stopTiles(stop, target);
  const stopTerrain = byDistance(tiles.terrain, target), stopDetail = byDistance(tiles.detail, target);
  const overviewTerrain: string[] = [], overviewDetail: string[] = [], descentTerrain: string[] = [], descentDetail: string[] = [];
  if (previous) {
    // Same top-of-arc zoom the flight will use.
    const zoom = Math.min(overviewZoom(map, previous.center, stop.center), Math.max(previous.zoom, stop.zoom) - 1.2);
    const start = mercator(...previous.center);
    const { clientWidth: width, clientHeight: height } = map.getContainer();
    const margin = Math.max(width, height) / 2 / (512 * 2 ** zoom);
    const box = [Math.min(start[0], target[0]) - margin, Math.min(start[1], target[1]) - margin,
      Math.max(start[0], target[0]) + margin, Math.max(start[1], target[1]) + margin] as const;
    overviewTerrain.push(...tilesInBox(...box, Math.floor(zoom)));
    overviewDetail.push(...tilesInBox(...box, Math.round(zoom + 1)));
    // The descent passes through the zoom levels between the top of the arc and the stop.
    for (let z = Math.floor(zoom) + 1; z < Math.floor(stop.zoom); z++) descentTerrain.push(...screenTiles(map, target, z, 512));
    for (let z = Math.round(zoom + 1) + 1; z < Math.round(stop.zoom + 1); z++) descentDetail.push(...screenTiles(map, target, z, 256));
  }
  // Hillshade (256 px DEM tiles) only renders with the studio's relief on.
  const shade = map.getLayer("station-terrain-shade") && map.getLayoutProperty("station-terrain-shade", "visibility") === "visible";
  const started = performance.now(), container = map.getContainer();
  if (diagnostics) container.dataset.monitoringPreloadPlan = JSON.stringify({ stopTerrain, stopDetail, overviewTerrain, overviewDetail, descentTerrain, descentDetail });
  return Promise.all([
    preloadTerrainTiles(png([...stopTerrain, ...overviewTerrain, ...(shade ? [...stopDetail, ...overviewDetail] : [])])),
    preloadImagery(map, [...stopDetail, ...overviewDetail]),
  ]).then(() => {
    container.dataset.monitoringPreloadMs = String(Math.round(performance.now() - started));
    void preloadTerrainTiles(png([...descentTerrain, ...(shade ? descentDetail : [])]));
    void preloadImagery(map, descentDetail);
  });
}

// After the first landing, quietly fetch the imagery and terrain for every stop
// on the tour, so even the first loop lands on ready tiles. The persistent tile
// caches keep them; stations already warmed this session are skipped.
const warmedStations = new Set<string>();
let warming = false;
export function warmMonitoringTour(map: MapLibreMap, stations: TourStation[], fromIndex: number, isActive: () => boolean) {
  if (warming || !stopFootprint || fromIndex < 0) return;
  const order = [...stations.slice(fromIndex + 1), ...stations.slice(0, fromIndex + 1)];
  warming = true;
  void (async () => {
    try {
      for (let index = 0; index < order.length && isActive(); index++) {
        const to = order[index], from = index ? order[index - 1] : stations[fromIndex];
        if (warmedStations.has(to.id)) continue;
        const { stop, target } = plannedStop(map, from, to);
        const tiles = stopTiles(stop, target);
        // Low concurrency: this runs alongside the next hop's own, more urgent preload.
        await Promise.all([preloadTerrainTiles(png(tiles.terrain)), preloadImagery(map, byDistance(tiles.detail, target), 4)]);
        warmedStations.add(to.id);
      }
    } finally {
      warming = false;
    }
  })();
}
