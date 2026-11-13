import type { FlyToOptions, Map as MapLibreMap, PaddingOptions } from "maplibre-gl";
import { imageryBackdropMaxZoom, preloadImageryBackdrop, preloadImageryTiles } from "./imageryTiles";
import { preloadTerrainTiles } from "./stationTerrainTiles";

// Cinematic camera for monitoring mode. Each hop is one continuous flight,
// banking toward the direction of travel. When the ground on the way is already
// loaded it is a low glide: the camera stays near the height of the lower of the
// two views, rising further only when a hop is too long to cross at that height.
// When that ground is still downloading (a first visit: the tile servers deliver
// only a dozen or so tiles a second), it rises instead to the height where the
// always-loaded coarse imagery is all the view needs, so tiles are never seen
// arriving one by one. It lands in a tilted 3D view, facing the way it arrived:
// the station itself for a close-up station, otherwise the station's whole
// catchment. While a stop is held the camera orbits slowly. The tiles for the
// next stop and for the ground the low flight passes over are loaded, onto the
// graphics card, during the stop before.

/**
 * `catchment` is the station's catchment bounding box [west, south, east, north].
 * With `closeUp`, the stop is a 3D view of the station itself instead of its whole catchment.
 * With `flat`, the tour is the 2D one: the camera looks straight down with north up, over a
 * map without terrain, and neither tilts nor turns.
 */
export interface TourStation { id: string; longitude: number; latitude: number; catchment?: [number, number, number, number]; closeUp?: boolean; flat?: boolean }

const closeZoom = 10;     // stop zoom for a station without a known catchment
const minStopZoom = 5.6, maxStopZoom = 9.6;
const closeUpZoom = 11.4, closeUpPitch = 64;   // the 3D view of the station itself
const travelMargin = 0.15;    // how far above the lower of the two views a hop flies, in zoom levels
const maxTravelSpans = 3.5;   // a longer hop rises until it is this many screen widths long
// The highest camera zoom at which the always-loaded coarse imagery is the detail the view asks for.
const coarseViewZoom = imageryBackdropMaxZoom - 0.6;
const maxBank = 22;       // how far the camera turns toward the travel direction mid-flight
const arrivalTurn = 20;   // landing bearing for a due east or west arrival
// Smootherstep has zero velocity and acceleration at both ends: a soft lift-off and touchdown.
const smootherstep = (t: number) => t * t * t * (t * (t * 6 - 15) + 10);
const easeInOutSine = (t: number) => (1 - Math.cos(Math.PI * t)) / 2;
const imagerySourceId = "global-satellite-basemap";
const tourRegion: [number, number, number, number] = [58, 22, 82, 40];   // every station and the overview between them
const maxWayTiles = 700;   // most tiles loaded for the ground one flight passes over (per layer)
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
 * The stop view. A close-up station is seen from low and near, tilted steeply
 * so the terrain around it stands up. Any other station has its whole catchment
 * in frame beside the details panel, tilted so the 3D relief reads; the centre
 * sits a third of the way from the catchment's middle toward the station, so
 * stations sharing one large basin still get their own view.
 */
function stopCamera(map: MapLibreMap, station: TourStation, from: [number, number] | null) {
  const padding = stationCameraPadding(map);
  const { clientWidth: width, clientHeight: height } = map.getContainer();
  const point: [number, number] = [station.longitude, station.latitude];
  if (station.closeUp && !station.flat) {
    return { center: point, zoom: closeUpZoom, pitch: closeUpPitch, bearing: arrivalBearing(from, point), padding, flat: false, closeUp: true };
  }
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
  if (station.flat) return { center, zoom, pitch: 0, bearing: 0, padding, flat: true, closeUp: false };
  return { center, zoom, pitch: width < 700 ? 42 : 50, bearing: arrivalBearing(from, center), padding, flat: false, closeUp: false };
}
type StopCamera = ReturnType<typeof stopCamera>;
/** Where a flight starts: the camera's centre, zoom and bearing. */
type CameraView = { center: [number, number]; zoom: number; bearing: number };

/**
 * How the flight from `start` to `stop` is flown: its travel height (`apex`, a
 * zoom level), the flyTo curve that reaches exactly that height, its length in
 * screen spans at the starting zoom, its duration and its heading changes.
 * `groundReady` says the tiles on the way are loaded, so the flight can stay low.
 */
function flightPlan(map: MapLibreMap, start: CameraView, stop: StopCamera, groundReady: boolean) {
  const { clientWidth: width, clientHeight: height } = map.getContainer();
  const [x0, y0] = mercator(...start.center), [x1, y1] = mercator(...stop.center);
  // Ground distance in screen spans at zoom 0; a span is the longer side of the map.
  const reach = Math.hypot(x1 - x0, y1 - y0) * 512 / Math.max(width, height, 1);
  // Fly just above the lower of the two views, so the camera never climbs to an
  // overview and back; only a hop too long to cross at that height rises further.
  // Over ground that is not loaded yet, rise to where the coarse imagery suffices.
  const lowest = Math.min(start.zoom, stop.zoom) - travelMargin, low = groundReady ? lowest : Math.min(lowest, coarseViewZoom);
  const apex = Math.max(3.6, Math.min(low, reach > 0 ? Math.log2(maxTravelSpans / reach) : low));
  const spans = reach * 2 ** start.zoom, peak = 2 ** (start.zoom - apex), end = 2 ** (start.zoom - stop.zoom);
  // flyTo's `minZoom` only caps how far a flight zooms out and never sets it, so the
  // height is set through the curve: the one whose arc (van Wijk and Nuij's flight
  // path, which flyTo follows) peaks at `apex`. `minZoom` stays as the cap.
  const curve = spans < 1e-6 || peak <= Math.max(1, end) ? 1.42
    : Math.max(0.2, Math.sqrt((Math.sqrt(peak * peak - 1) + Math.sqrt(peak * peak - end * end)) / spans));
  const climb = Math.max(0, start.zoom - apex) + Math.max(0, stop.zoom - apex);
  const duration = clamp(2200 + climb * 450 + reach * 2 ** apex * 1800, 4000, 10500);
  const turn = wrap(stop.bearing - start.bearing);
  const direction = travelHeading(start.center, stop.center);
  const bank = direction === null || stop.flat ? 0 : clamp(wrap(direction - (start.bearing + turn / 2)) * 0.35, -maxBank, maxBank);
  return { apex, spans, curve, duration, turn, bank };
}

/**
 * Points along the flight flyTo will draw for this plan: how far along the
 * ground track the camera is (0 to 1), its zoom there and the share of the
 * flight flown (`k`, before easing). Used to load the tiles the flight passes.
 */
function flightSamples(spans: number, startZoom: number, stopZoom: number, curve: number, count: number) {
  const end = 2 ** (startZoom - stopZoom), curve2 = curve * curve;
  const zoomOut = (descent: boolean) => {
    const b = (end * end - 1 + (descent ? -1 : 1) * curve2 * curve2 * spans * spans) / (2 * (descent ? end : 1) * curve2 * spans);
    return Math.log(Math.sqrt(b * b + 1) - b);
  };
  const r0 = spans < 1e-6 ? NaN : zoomOut(false), length = (zoomOut(true) - r0) / curve;
  return Array.from({ length: count + 1 }, (_, index) => {
    const k = index / count, s = length * k;
    // Too short a path to rise and descend: the camera only changes zoom.
    if (!Number.isFinite(length)) return { k, along: k, zoom: startZoom + (stopZoom - startZoom) * k };
    return { k, along: clamp((Math.cosh(r0) * Math.tanh(r0 + curve * s) - Math.sinh(r0)) / curve2 / spans, 0, 1),
      zoom: startZoom - Math.log2(Math.cosh(r0) / Math.cosh(r0 + curve * s)) };
  });
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
 * One continuous flight to the stop. flyTo draws the path; a per-frame camera
 * hook carries the tilt from the view it leaves to the stop's (the 3D tour stays
 * tilted throughout, the 2D tour flat) and shapes the heading, banking toward
 * the travel direction.
 */
async function cinematicFlight(map: MapLibreMap, stop: StopCamera, groundReady: boolean) {
  const start: CameraView = { center: map.getCenter().toArray() as [number, number], zoom: map.getZoom(), bearing: map.getBearing() };
  const startPitch = map.getPitch();
  const { apex, curve, duration, turn, bank } = flightPlan(map, start, stop, groundReady);
  if (diagnostics) map.getContainer().dataset.monitoringFlight = JSON.stringify({ low: groundReady, apex: +apex.toFixed(2), ms: Math.round(duration) });
  const began = performance.now();
  map.setTransformCameraUpdate(() => {
    const k = smootherstep(clamp((performance.now() - began) / duration, 0, 1)), arc = Math.sin(Math.PI * k);
    return { pitch: startPitch + (stop.pitch - startPitch) * k, bearing: start.bearing + turn * k + bank * arc };
  });
  try {
    const { center, zoom, pitch, bearing, padding } = stop;
    return await cameraStep(map, { center, zoom, pitch, bearing, padding, curve, minZoom: apex, duration, easing: smootherstep }, true);
  } finally {
    map.setTransformCameraUpdate(null);
  }
}

// Where the hold's slow pass will leave the camera, which is where the next flight starts from.
let heldView: { id: string; zoom: number; bearing: number } | null = null;

/**
 * A slow drone pass while a stop is held: the 3D tour orbits and drifts closer
 * (a wider orbit round a close-up station), the 2D tour only drifts closer.
 * Skipped when the viewer prefers reduced motion.
 */
function holdOrbit(map: MapLibreMap, station: TourStation, stop: StopCamera) {
  heldView = { id: station.id, zoom: stop.zoom, bearing: stop.bearing };
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const side = Math.sign(stop.bearing || 1);
  const end = stop.flat ? { zoom: stop.zoom + 0.25 }
    : stop.closeUp ? { zoom: stop.zoom + 0.2, bearing: stop.bearing + side * 40 }
      : { zoom: stop.zoom + 0.2, bearing: stop.bearing + side * 16, pitch: stop.pitch + 4 };
  heldView = { id: station.id, zoom: end.zoom, bearing: end.bearing ?? stop.bearing };
  map.easeTo({ ...end, duration: 9500, easing: easeInOutSine, essential: true });
}

/**
 * Flies the camera to a monitoring stop from wherever it is, then starts the
 * hold orbit. Stops early once `isCurrent()` turns false; resolves true when
 * the camera actually landed at the stop.
 */
export async function runMonitoringHop(map: MapLibreMap, station: TourStation, isCurrent: () => boolean) {
  const stop = stopCamera(map, station, map.getCenter().toArray() as [number, number]);
  const landed = await cinematicFlight(map, stop, groundReadyFor === station.id) && isCurrent();
  if (landed) {
    measureStopFootprint(map, stop);
    holdOrbit(map, station, stop);
  }
  return landed;
}

// Stops of one kind share tilt and padding; only centre, zoom and bearing differ.
// In Web Mercator a view's tile footprint keeps its shape when moved and scales
// with zoom, so the tiles the map needed at one stop (as offsets from the camera
// centre) predict the tiles at another place, zoom and bearing once shifted,
// rescaled and rotated. A footprint is kept for each kind of stop, as their
// tilts differ.
type TileOffset = [z: number, dx: number, dy: number];
type Footprint = { zoom: number; bearing: number; terrain: TileOffset[]; detail: TileOffset[] };
const footprints: { flat?: Footprint; closeUp?: Footprint; catchment?: Footprint } = {};
const stopKind = (stop: StopCamera) => stop.flat ? "flat" : stop.closeUp ? "closeUp" : "catchment";
/** The footprint measured at a stop of this kind, else the nearest other kind measured so far. */
const footprintFor = (stop: StopCamera) => footprints[stopKind(stop)] ?? footprints.closeUp ?? footprints.catchment ?? footprints.flat;

// Footprints are remembered between sessions (for one map size), so the first
// flight of a session can load its tiles before any stop has been measured.
const footprintStore = "floodguard-tour-footprints";
const mapSize = (map: MapLibreMap) => `${map.getContainer().clientWidth}x${map.getContainer().clientHeight}`;
let footprintsRecalled = false;
function recallFootprints(map: MapLibreMap) {
  if (footprintsRecalled) return;
  footprintsRecalled = true;
  try {
    const saved = JSON.parse(localStorage.getItem(footprintStore) ?? "null") as { size?: string; footprints?: typeof footprints } | null;
    if (saved?.size !== mapSize(map) || !saved.footprints) return;
    for (const kind of ["flat", "closeUp", "catchment"] as const) {
      const footprint = saved.footprints[kind];
      if (footprint && Array.isArray(footprint.detail) && Array.isArray(footprint.terrain)) footprints[kind] ??= footprint;
    }
  } catch { /* storage blocked or an older format: the first landing measures afresh */ }
}

function measureStopFootprint(map: MapLibreMap, stop: StopCamera) {
  const [originX, originY] = mercator(...(map.getCenter().toArray() as [number, number]));
  const offsets = (tileSize: number, roundZoom: boolean) => map.coveringTiles({ tileSize, roundZoom, maxzoom: 13 })
    .map(({ canonical: { z, x, y } }): TileOffset => [z, x + 0.5 - originX * 2 ** z, y + 0.5 - originY * 2 ** z]);
  // Terrain meshes load 512 px DEM tiles (floored zoom); hillshade and imagery load 256 px tiles (rounded zoom).
  footprints[stopKind(stop)] = { zoom: map.getZoom(), bearing: map.getBearing(), terrain: offsets(512, false), detail: offsets(256, true) };
  try { localStorage.setItem(footprintStore, JSON.stringify({ size: mapSize(map), footprints })); } catch { /* storage blocked */ }
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

function tilesAround(point: [number, number], z: number, radius: number) {
  const scale = 2 ** z, x = Math.floor(point[0] * scale), y = Math.floor(point[1] * scale), keys: string[] = [];
  for (let dx = -radius; dx <= radius; dx++) for (let dy = -radius; dy <= radius; dy++) {
    if (y + dy >= 0 && y + dy < scale) keys.push(`${z}/${(x + dx + scale) % scale}/${y + dy}`);
  }
  return keys;
}

/**
 * Imagery goes through the persistent imagery cache, so the map's own requests
 * are served locally. With `onGpu`, each tile is also decoded and uploaded to
 * the graphics card as soon as it arrives, ahead of the camera.
 */
async function preloadImagery(map: MapLibreMap, keys: string[], concurrency = 12, onGpu = false) {
  const satellite = map.getLayer(imagerySourceId) && map.getLayoutProperty(imagerySourceId, "visibility") !== "none";
  if (!satellite) return;
  if (!onGpu) { await preloadImageryTiles(keys, concurrency); return; }
  // The bytes are fetched many at once (the map limits its own image requests to 16),
  // and the upload pass, which asks for the same bytes, follows as they arrive.
  const fetched = preloadImageryTiles(keys, 24);
  if (!await keepImageryOnGpu(map, keys, 16)) await fetched;
}

type CachedTile = { tileID: { key: string }; state: string; constructor: new (id: unknown, size: number) => CachedTile };
type ImageryTiles = {
  getIds(): string[]; getTileByID(id: string): CachedTile | undefined;
  _source: { tileSize: number; loadTile(tile: CachedTile): Promise<unknown>; unloadTile?(tile: CachedTile): void };
  _outOfViewCache: { has(id: unknown): boolean; add(id: unknown, tile: CachedTile): unknown };
};
/**
 * Puts imagery tiles ("z/x/y") in the map's own cache of ready-to-draw tiles,
 * as textures on the graphics card. When the camera reaches them they are drawn
 * in the same frame, so a coarser tile is never seen being replaced by a sharper
 * one. The map has no public call for this, so it uses the map's tile store
 * directly; it resolves false, having done nothing, if that store is not as expected.
 */
async function keepImageryOnGpu(map: MapLibreMap, keys: string[], concurrency = 12) {
  try {
    const tiles = (map as unknown as { style?: { tileManagers?: Record<string, ImageryTiles> } }).style?.tileManagers?.[imagerySourceId];
    const sample = tiles?.getTileByID(tiles.getIds()[0] ?? "");
    if (!tiles || !sample) return false;
    const Tile = sample.constructor, TileId = sample.tileID.constructor as new (overscaledZ: number, wrap: number, z: number, x: number, y: number) => { key: string };
    const ready = (id: { key: string }) => Boolean(tiles.getTileByID(id.key)) || tiles._outOfViewCache.has(id);
    const pending = [...new Set(keys)];
    let next = 0;
    await Promise.all(Array.from({ length: Math.min(concurrency, pending.length) }, async () => {
      while (next < pending.length) {
        const [z, x, y] = pending[next++].split("/").map(Number), id = new TileId(z, 0, z, x, y);
        if (ready(id)) continue;
        const tile = new Tile(id, tiles._source.tileSize);
        await tiles._source.loadTile(tile).catch(() => undefined);
        // The map may have loaded the same tile meanwhile; keep only one copy.
        if (tile.state !== "loaded" || ready(id)) tiles._source.unloadTile?.(tile);
        else tiles._outOfViewCache.add(id, tile);
      }
    }));
    return true;
  } catch {
    return false;   // the map still loads these tiles itself when the camera gets there
  }
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

/** Tiles the stop view will need: the measured footprint moved there, or rings around it before any landing. */
function stopTiles(stop: StopCamera, target: [number, number]) {
  const footprint = footprintFor(stop);
  if (!footprint) {
    const z = Math.floor(stop.zoom);
    return { terrain: [...tilesAround(target, z - 1, 1), ...tilesAround(target, z, 2)], detail: [...tilesAround(target, z + 1, 3), ...tilesAround(target, z + 2, 2)] };
  }
  const turn = stop.bearing - footprint.bearing, zoomChange = stop.zoom - footprint.zoom;
  return { terrain: footprintKeys(footprint.terrain, target, turn, zoomChange), detail: footprintKeys(footprint.detail, target, turn, zoomChange) };
}

/**
 * Tiles the flight from `start` to `stop` passes over, in the order it reaches
 * them: the stop footprint carried along the flight's own path, at the zoom and
 * heading the camera has at each point. Empty before any landing has been measured.
 */
function flightTiles(map: MapLibreMap, start: CameraView, stop: StopCamera) {
  const footprint = footprintFor(stop), terrain = new Set<string>(), detail = new Set<string>();
  if (!footprint) return { terrain: [], detail: [] };
  const { apex, spans, curve, turn, bank } = flightPlan(map, start, stop, true);
  const from = mercator(...start.center), to = mercator(...stop.center);
  // About three views for every screen the camera crosses, so neighbouring views overlap.
  const count = Math.round(clamp(spans * 2 ** (apex - start.zoom) * 3 + 6, 8, 28));
  for (const { k, along, zoom } of flightSamples(spans, start.zoom, stop.zoom, curve, count)) {
    const point: [number, number] = [from[0] + (to[0] - from[0]) * along, from[1] + (to[1] - from[1]) * along];
    const heading = start.bearing + turn * k + bank * Math.sin(Math.PI * k) - footprint.bearing;
    for (const key of footprintKeys(footprint.terrain, point, heading, zoom - footprint.zoom)) terrain.add(key);
    for (const key of footprintKeys(footprint.detail, point, heading, zoom - footprint.zoom)) detail.add(key);
  }
  return { terrain: [...terrain], detail: [...detail] };
}

// The station whose flight path was fully loaded by the time its preload finished: the flight there can stay low.
let groundReadyFor: string | null = null;
// The preload for the hop about to be flown; the background warm-up waits for it, as the two share one slow download.
let hopPreload: Promise<unknown> = Promise.resolve();

/**
 * Loads elevation and imagery for the hop to the next stop: first the stop's own
 * view, then the ground the low flight passes over, imagery going straight onto
 * the graphics card. `from` is the stop being held (null when the tour is
 * starting). The returned promise settles once all of it is loaded.
 */
export function preloadMonitoringHop(map: MapLibreMap, from: TourStation | null, to: TourStation) {
  groundReadyFor = null;
  recallFootprints(map);
  if (map.getLayer(imagerySourceId) && map.getLayoutProperty(imagerySourceId, "visibility") !== "none") void preloadImageryBackdrop(tourRegion);
  // The flight leaves from where the hold's slow pass ends, or from the camera as it is now.
  const center = map.getCenter().toArray() as [number, number];
  const start: CameraView = from && heldView?.id === from.id ? { center, zoom: heldView.zoom, bearing: heldView.bearing }
    : { center, zoom: map.getZoom(), bearing: map.getBearing() };
  const stop = stopCamera(map, to, center), target = mercator(...stop.center);
  const tiles = stopTiles(stop, target), way = flightTiles(map, start, stop);
  const stopTerrain = byDistance(tiles.terrain, target), stopDetail = byDistance(tiles.detail, target);
  // What the flight needs beyond the stop's own tiles (elevation and imagery tiles are separate sets).
  const stopTerrainKeys = new Set(stopTerrain), stopDetailKeys = new Set(stopDetail);
  const restTerrain = way.terrain.filter((key) => !stopTerrainKeys.has(key)), restDetail = way.detail.filter((key) => !stopDetailKeys.has(key));
  const wayTerrain = restTerrain.slice(0, maxWayTiles), wayDetail = restDetail.slice(0, maxWayTiles);
  // The whole way is covered only once a stop has been measured and nothing had to be left out.
  const wholeWay = Boolean(footprintFor(stop)) && restTerrain.length <= maxWayTiles && restDetail.length <= maxWayTiles;
  // Hillshade (256 px DEM tiles) only renders with the studio's relief on.
  const shade = map.getLayer("station-terrain-shade") && map.getLayoutProperty("station-terrain-shade", "visibility") === "visible";
  const started = performance.now(), container = map.getContainer();
  if (diagnostics) container.dataset.monitoringPreloadPlan = JSON.stringify({ stopTerrain, stopDetail, wayTerrain, wayDetail });
  const loaded = Promise.all([
    // The 2D tour has no terrain to load.
    to.flat ? Promise.resolve() : preloadTerrainTiles(png([...stopTerrain, ...wayTerrain, ...(shade ? [...stopDetail, ...wayDetail] : [])])),
    preloadImagery(map, stopDetail, 12, true).then(() => preloadImagery(map, wayDetail, 12, true)),
  ]).then(() => {
    container.dataset.monitoringPreloadMs = String(Math.round(performance.now() - started));
    if (wholeWay && hopPreload === loaded) groundReadyFor = to.id;
  });
  hopPreload = loaded;
  return loaded;
}

// After the first landing, quietly fetch the imagery and terrain for every stop
// on the tour, so even the first loop lands on ready tiles. The persistent tile
// caches keep them; stations already warmed this session are skipped.
const warmedStations = new Set<string>();
let warming = false;
export function warmMonitoringTour(map: MapLibreMap, stations: TourStation[], fromIndex: number, isActive: () => boolean) {
  if (warming || !(footprints.flat ?? footprints.closeUp ?? footprints.catchment) || fromIndex < 0) return;
  const order = [...stations.slice(fromIndex + 1), ...stations.slice(0, fromIndex + 1)];
  warming = true;
  void (async () => {
    try {
      for (let index = 0; index < order.length && isActive(); index++) {
        const to = order[index], from = index ? order[index - 1] : stations[fromIndex];
        if (warmedStations.has(to.id)) continue;
        await hopPreload.catch(() => undefined);
        const stop = stopCamera(map, to, [from.longitude, from.latitude]), target = mercator(...stop.center);
        const tiles = stopTiles(stop, target);
        // Low concurrency: this runs alongside the next hop's own, more urgent preload.
        await Promise.all([to.flat ? Promise.resolve() : preloadTerrainTiles(png(tiles.terrain)), preloadImagery(map, byDistance(tiles.detail, target), 4)]);
        warmedStations.add(to.id);
      }
    } finally {
      warming = false;
    }
  })();
}
