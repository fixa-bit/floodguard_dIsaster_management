import type { FlyToOptions, Map as MapLibreMap, PaddingOptions, RasterTileSource } from "maplibre-gl";
import { inBatches, preloadTerrainTiles } from "./stationTerrainTiles";

// Camera choreography for monitoring mode: each hop zooms out (flattened,
// north-up) until the next station is in view, travels there, then descends
// into a tilted 3D stop. Tiles for the next hop are preloaded during the stop.

export interface TourStation { id: string; longitude: number; latitude: number }

const stopZoom = 10;
const overviewPitch = 20;
const easeInOut = (t: number) => t < 0.5 ? 4 * t ** 3 : 1 - (-2 * t + 2) ** 3 / 2;
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

function stopCamera(map: MapLibreMap, station: TourStation) {
  let hash = 0;
  for (const character of station.id) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  return {
    center: [station.longitude, station.latitude] as [number, number],
    zoom: stopZoom,
    pitch: map.getContainer().clientWidth < 700 ? 45 : 55,
    bearing: hash % 2 ? 18 : -18,
    padding: stationCameraPadding(map),
  };
}

/** Zoom at which the hop's start and end both sit comfortably inside the free map area. */
function overviewZoom(map: MapLibreMap, from: [number, number], to: [number, number]) {
  const padding = stationCameraPadding(map);
  const { clientWidth: width, clientHeight: height } = map.getContainer();
  const free = Math.max(160, Math.min(width - padding.left - padding.right, height - padding.top - padding.bottom));
  const [x0, y0] = mercator(...from), [x1, y1] = mercator(...to);
  const distance = Math.hypot(x1 - x0, y1 - y0) * 512;
  const fit = distance > 0 ? Math.log2(0.42 * free / distance) : stopZoom;
  return Math.min(stopZoom - 1.6, Math.max(4.8, fit));
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
 * Moves the camera to a monitoring stop. `hop` runs the zoom-out / travel /
 * descend sequence from the current view; otherwise (entering monitoring mode)
 * it flies straight in. Stops early once `isCurrent()` turns false; resolves
 * true when the camera actually landed at the stop.
 */
export async function runMonitoringHop(map: MapLibreMap, station: TourStation, hop: boolean, isCurrent: () => boolean) {
  const stop = stopCamera(map, station);
  let landed: boolean;
  if (!hop) landed = await cameraStep(map, { ...stop, duration: 2600, curve: 1.42 }, true);
  else {
    const here = map.getCenter().toArray() as [number, number];
    const zoom = Math.min(map.getZoom(), overviewZoom(map, here, stop.center));
    const zoomOut = map.getZoom() - zoom;
    if (zoomOut > 0.05 || map.getPitch() > overviewPitch + 2) {
      const done = await cameraStep(map, { center: here, zoom, pitch: overviewPitch, bearing: 0, padding: stop.padding,
        duration: 1100 + zoomOut * 170, easing: easeInOut });
      if (!done || !isCurrent()) return false;
    }
    const [x0, y0] = mercator(...here), [x1, y1] = mercator(...stop.center);
    const travelPixels = Math.hypot(x1 - x0, y1 - y0) * 512 * 2 ** zoom;
    const travelled = await cameraStep(map, { center: stop.center, zoom, duration: Math.min(2600, Math.max(1100, 900 + travelPixels * 2.2)), easing: easeInOut });
    if (!travelled || !isCurrent()) return false;
    landed = await cameraStep(map, { ...stop, duration: 1700 + (stopZoom - zoom) * 180, easing: easeInOut });
  }
  if (landed && isCurrent()) measureStopFootprint(map, station);
  return landed && isCurrent();
}

// Every stop uses the same camera (zoom, tilt, padding) apart from its bearing,
// and at a fixed zoom the Web Mercator tile grid looks the same everywhere. So
// the tiles the map needed at this stop, as offsets from the station, predict
// the tiles the next stop will need once rotated by the bearing difference.
type TileOffset = [z: number, dx: number, dy: number];
let stopFootprint: { bearing: number; terrain: TileOffset[]; detail: TileOffset[] } | null = null;

function measureStopFootprint(map: MapLibreMap, station: TourStation) {
  const [originX, originY] = mercator(station.longitude, station.latitude);
  const offsets = (tileSize: number, roundZoom: boolean) => map.coveringTiles({ tileSize, roundZoom, maxzoom: 13 })
    .map(({ canonical: { z, x, y } }): TileOffset => [z, x + 0.5 - originX * 2 ** z, y + 0.5 - originY * 2 ** z]);
  // Terrain meshes load 512 px DEM tiles (floored zoom); hillshade and imagery load 256 px tiles (rounded zoom).
  stopFootprint = { bearing: map.getBearing(), terrain: offsets(512, false), detail: offsets(256, true) };
}

function footprintKeys(offsets: TileOffset[], target: [number, number], turnDegrees: number) {
  const turn = turnDegrees * Math.PI / 180, cos = Math.cos(turn), sin = Math.sin(turn), keys = new Set<string>();
  for (const [z, dx, dy] of offsets) {
    const scale = 2 ** z;
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

const prefetchedImagery = new Set<string>();
function preloadImagery(map: MapLibreMap, keys: string[]) {
  const template = (map.getSource(imagerySourceId) as RasterTileSource | undefined)?.tiles?.[0];
  if (!template || map.getLayoutProperty(imagerySourceId, "visibility") === "none") return Promise.resolve();
  const urls = [...new Set(keys)].map((key) => {
    const [z, x, y] = key.split("/");
    return template.replace("{z}", z).replace("{x}", x).replace("{y}", y);
  }).filter((url) => !prefetchedImagery.has(url));
  // The imagery server allows caching, so the map's own request for these tiles is served by the browser cache.
  return inBatches(urls, (url) => fetch(url, { priority: "low" } as RequestInit).then(async (response) => {
    await response.blob();
    if (response.ok) prefetchedImagery.add(url);
  }), 12);
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

/**
 * Preloads elevation and imagery for the hop from one stop to the next. The
 * returned promise settles once the destination stop and the overview are
 * loaded; tiles for the descent between them keep loading afterwards.
 */
export function preloadMonitoringHop(map: MapLibreMap, from: TourStation | null, to: TourStation) {
  const target = mercator(to.longitude, to.latitude);
  const turn = stopFootprint ? stopCamera(map, to).bearing - stopFootprint.bearing : 0;
  const stopTerrain = byDistance(stopFootprint ? footprintKeys(stopFootprint.terrain, target, turn) : [...tilesAround(target, 9, 1), ...tilesAround(target, 10, 2)], target);
  const stopDetail = byDistance(stopFootprint ? footprintKeys(stopFootprint.detail, target, turn) : [...tilesAround(target, 11, 3), ...tilesAround(target, 12, 2)], target);
  const overviewTerrain: string[] = [], overviewDetail: string[] = [], descentTerrain: string[] = [], descentDetail: string[] = [];
  if (from) {
    const zoom = overviewZoom(map, [from.longitude, from.latitude], [to.longitude, to.latitude]);
    const start = mercator(from.longitude, from.latitude);
    const { clientWidth: width, clientHeight: height } = map.getContainer();
    const margin = Math.max(width, height) / 2 / (512 * 2 ** zoom);
    const box = [Math.min(start[0], target[0]) - margin, Math.min(start[1], target[1]) - margin,
      Math.max(start[0], target[0]) + margin, Math.max(start[1], target[1]) + margin] as const;
    overviewTerrain.push(...tilesInBox(...box, Math.floor(zoom)));
    overviewDetail.push(...tilesInBox(...box, Math.round(zoom + 1)));
    for (const z of [8, 9]) if (z > Math.floor(zoom)) descentTerrain.push(...screenTiles(map, target, z, 512));
    for (const z of [8, 9, 10]) if (z > Math.round(zoom + 1)) descentDetail.push(...screenTiles(map, target, z, 256));
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
