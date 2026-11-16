import type { FeatureCollection } from "geojson";
import * as maplibregl from "maplibre-gl";
import type { FlyToOptions, Map as MapLibreMap, PaddingOptions } from "maplibre-gl";
import { backdropTileKeys, imageryBackdropMaxZoom, imageryOutsidePack, preloadImageryBackdrop, preloadImageryTiles } from "./imageryTiles";
import { courseLength, fromMercator, riverCourse, riverNetwork, smoothCourse, toMercator, type MercatorPoint } from "./riverRoute";
import { preloadTerrainTiles } from "./stationTerrainTiles";

// Cinematic camera for monitoring mode. Each hop is one continuous low glide,
// banking toward the direction of travel: the camera stays near the height of
// the lower of the two views, rising further only when a hop is too long to
// cross at that height. It lands in a tilted 3D view, facing the way it arrived:
// the station itself for a close-up station, otherwise the station's whole
// catchment. While a stop is held the camera orbits slowly.
//
// No tile is ever downloaded while the camera is over it. The tiles for the next
// stop and for the ground the flight passes over are loaded, onto the graphics
// card, during the stop before, coarse levels of detail first. The map is only
// allowed to ask for imagery as fine as what is already loaded for the whole
// view it is about to show (the detail cap below), so on a first visit (the tile
// servers deliver only a dozen or so tiles a second) the flight is uniformly a
// little softer instead of showing sharp squares arriving one by one.

/**
 * `catchment` is the station's catchment bounding box [west, south, east, north],
 * `catchmentId` the catchment it lies in. With `closeUp`, the stop is a 3D view of
 * the station itself instead of its whole catchment. With `flat`, the tour is the
 * 2D one: the camera looks straight down with north up, over a map without
 * terrain, and neither tilts nor turns.
 */
export interface TourStation {
  id: string; longitude: number; latitude: number;
  catchment?: [number, number, number, number]; catchmentId?: string; closeUp?: boolean; flat?: boolean;
}

// The 3D tour goes catchment by catchment: entering a catchment, the camera
// rises to an establishing shot of the whole catchment (highlighted on the map),
// holds it for a few seconds with a slow drift, then descends to the first
// station; it then moves from station to station within the catchment, along
// the river where one links them, before rising to the next catchment.
const catchmentHold = 3500;   // how long the establishing shot of a catchment is held, in ms
const orbitTurn = 14;         // how far the slow pass at a station turns, in degrees

let sequence: TourStation[] = [];
/** The tour's stations in order; the camera plans each landing to face the way it will leave. */
export function setTourSequence(stations: TourStation[]) { sequence = stations; }
const stationAfter = (station: TourStation) => {
  const index = sequence.findIndex((item) => item.id === station.id);
  return index < 0 || sequence.length < 2 ? null : sequence[(index + 1) % sequence.length];
};
// The station the camera last landed at, so the next hop knows whether it stays in the same catchment.
let lastStation: TourStation | null = null;

const closeZoom = 10;     // stop zoom for a station without a known catchment
const minStopZoom = 5.6, maxStopZoom = 9.6;
const closeUpZoom = 11.6, closeUpPitch = 64;   // the 3D view of the station itself
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
// Every station and the overview between them, plus the horizon a tilted camera sees beyond them.
const tourRegion: [number, number, number, number] = [52, 16, 88, 44];
const tourHorizon: [number, number, number, number] = [25, 0, 115, 55];   // zoom 4 and 5 only: the far edge of a tilted view
const tourBackdrop = () => preloadImageryBackdrop(tourRegion, tourHorizon);
const maxWayTiles = 700;   // most elevation tiles loaded for the ground one flight passes over
const maxLevelTiles = 6000;   // most imagery tiles one level of detail of a flight may need to be loaded at all
const maxGpuRouteTiles = 1000;   // most of them loaded onto the graphics card ahead of the flight
const tourMaxDetail = 13;   // the finest imagery zoom the tour uses (the measured footprints stop there too)
const diagnostics = new URLSearchParams(window.location.search).get("mapDiagnostics") === "1";

/** Keeps the station clear of the map controls (left) and station details panel (right). */
export function stationCameraPadding(map: MapLibreMap): Required<PaddingOptions> {
  const containerWidth = map.getContainer().clientWidth;
  const mobile = containerWidth < 700;
  const panelWidth = Math.min(620, containerWidth * 0.42);
  const panelRightInset = Math.max(40, Math.min(96, containerWidth * 0.05));
  // While the tour's route rail is showing beside the map controls, keep clear of it too.
  const rail = document.querySelector(".tour-route-rail")?.getBoundingClientRect();
  const railEdge = rail && rail.width > 0 ? rail.right - map.getContainer().getBoundingClientRect().left + 24 : 0;
  return { top: mobile ? 120 : 185, bottom: mobile ? 55 : 90, left: mobile ? 16 : Math.max(230, railEdge), right: mobile ? 16 : panelWidth + panelRightInset + 24 };
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
type StopCamera = {
  center: [number, number]; zoom: number; pitch: number; bearing: number; padding: Required<PaddingOptions>;
  flat: boolean; closeUp: boolean;
  /** The catchment establishing shot rather than a station's own stop. */
  establishing: boolean;
  /** Where the slow pass at the stop turns to (the heading the camera leaves on). */
  orbitTo?: number;
};

/** Frames the catchment `bbox` (and `point`) within `padding`, centred `toward` of the way from its middle to the point. */
function frameCatchment(map: MapLibreMap, bbox: [number, number, number, number], point: [number, number], padding: Required<PaddingOptions>, toward: number) {
  const { clientWidth: width, clientHeight: height } = map.getContainer();
  const [west, south, east, north] = bbox;
  const middle: [number, number] = [(west + east) / 2, (south + north) / 2];
  const center: [number, number] = [middle[0] + (point[0] - middle[0]) * toward, middle[1] + (point[1] - middle[1]) * toward];
  const [cx, cy] = mercator(...center);
  const extent = [mercator(west, south), mercator(east, north), mercator(...point)];
  const halfX = Math.max(...extent.map(([x]) => Math.abs(x - cx))) * 512, halfY = Math.max(...extent.map(([, y]) => Math.abs(y - cy))) * 512;
  const freeX = Math.max(80, (width - padding.left - padding.right) / 2), freeY = Math.max(80, (height - padding.top - padding.bottom) / 2);
  // A tilted view pushes the near edge outward, so leave some room to keep the whole catchment in frame.
  return { center, zoom: clamp(Math.log2(Math.min(freeX / Math.max(halfX, 1e-9), freeY / Math.max(halfY, 1e-9))) - 0.35, minStopZoom, maxStopZoom) };
}

function stopCamera(map: MapLibreMap, station: TourStation, from: [number, number] | null, heading?: number, orbitTo?: number): StopCamera {
  const padding = stationCameraPadding(map);
  const width = map.getContainer().clientWidth;
  const point: [number, number] = [station.longitude, station.latitude];
  if (station.closeUp && !station.flat) {
    return { center: point, zoom: closeUpZoom, pitch: closeUpPitch, bearing: heading ?? arrivalBearing(from, point), padding, flat: false, closeUp: true, establishing: false, orbitTo };
  }
  const { center, zoom } = station.catchment ? frameCatchment(map, station.catchment, point, padding, 0.35) : { center: point, zoom: closeZoom };
  if (station.flat) return { center, zoom, pitch: 0, bearing: 0, padding, flat: true, closeUp: false, establishing: false };
  return { center, zoom, pitch: width < 700 ? 42 : 50, bearing: arrivalBearing(from, center), padding, flat: false, closeUp: false, establishing: false };
}

/**
 * The establishing shot of `station`'s catchment: the whole catchment, tilted
 * so its relief reads, facing `bearing` (the way the camera will look on landing
 * at the station, so the descent never has to turn). The station panel is not
 * open yet, so only the map controls on the left need room.
 */
function catchmentView(map: MapLibreMap, station: TourStation & { catchment: [number, number, number, number] }, bearing: number): StopCamera {
  const width = map.getContainer().clientWidth, mobile = width < 700;
  const padding = { ...stationCameraPadding(map), right: mobile ? 16 : 60 };
  const { center, zoom } = frameCatchment(map, station.catchment, [station.longitude, station.latitude], padding, 0.15);
  return { center, zoom, pitch: mobile ? 40 : 48, bearing, padding, flat: false, closeUp: false, establishing: true };
}
/** Where a flight starts: the camera's centre, zoom and bearing (and tilt, when known). */
type CameraView = { center: [number, number]; zoom: number; bearing: number; pitch?: number };

// River flights. In the 3D tour the camera travels from one station to the next
// along the river between them, looking ahead along the water: it lifts off the
// station, glides down (or up) the river at a height that keeps the ground
// moving at an even, unhurried pace, and settles on the next station looking
// along the river it arrived on. Where the water route is far longer than the
// direct one (stations on rivers that only meet hundreds of kilometres away),
// it flies the same way along a straight line instead.

let rivers: ReturnType<typeof riverNetwork> | null = null;
const routes = new Map<string, Route>();
/** The river lines the tour follows (the map's river features); call again when they change. */
export function setTourRivers(lines: FeatureCollection) {
  rivers = lines.features.length ? riverNetwork(lines) : null;
  routes.clear();
}

type Route = { points: MercatorPoint[]; alongRiver: boolean; length: number };
const maxRiverDetour = 2;   // a river route at most this many times the direct distance is followed
const routeKey = (from: [number, number], to: [number, number]) => [...from, ...to].map((value) => value.toFixed(3)).join(",");
/** The ground route between two points (longitude, latitude): along the river when it links them, else straight. */
function hopRoute(from: [number, number], to: [number, number]): Route {
  const key = routeKey(from, to), known = routes.get(key);
  if (known) return known;
  const a = toMercator(...from), b = toMercator(...to), direct = Math.hypot(b[0] - a[0], b[1] - a[1]);
  const course = rivers ? riverCourse(rivers, from, to) : null, along = course ? courseLength(course) : Infinity;
  const route = course && along <= maxRiverDetour * direct + 1e-5 ? { points: course, alongRiver: true, length: along }
    : { points: [a, b], alongRiver: false, length: direct };
  routes.set(key, route);
  return route;
}

/** Compass heading (0 = north) from one Mercator point to another. */
const headingBetween = (a: MercatorPoint, b: MercatorPoint) => Math.atan2(b[0] - a[0], a[1] - b[1]) * 180 / Math.PI;
const kilometres = (km: number) => km / (40_075 * Math.cos(30 * Math.PI / 180));
/** The heading a route arrives on (or, with `atStart`, leaves on), averaged over a dozen kilometres. */
function routeHeading(route: Route, atStart = false) {
  if (route.length < kilometres(1)) return undefined;
  const smooth = smoothCourse(route.points, 120, Math.min(kilometres(3), route.length / 12));
  const reach = Math.ceil(smooth.length * Math.min(0.5, kilometres(12) / route.length)), last = smooth.length - 1;
  return atStart ? headingBetween(smooth[0], smooth[reach]) : headingBetween(smooth[Math.max(0, last - reach)], smooth[last]);
}

const stationPoint = (station: TourStation): [number, number] => [station.longitude, station.latitude];
const sameCatchment = (a: TourStation | null, b: TourStation) => Boolean(a?.catchmentId) && a?.catchmentId === b.catchmentId;

/** The heading the camera leaves `station` on for `next`: along the river within a catchment, else straight for the next catchment. */
function departureHeading(station: TourStation, next: TourStation) {
  if (sameCatchment(station, next) && rivers) {
    const route = hopRoute(stationPoint(station), stationPoint(next));
    if (route.alongRiver) return routeHeading(route, true);
  }
  const [west, south, east, north] = next.catchment ?? [next.longitude, next.latitude, next.longitude, next.latitude];
  const target = sameCatchment(station, next) ? stationPoint(next) : [(west + east) / 2, (south + north) / 2] as [number, number];
  return travelHeading(stationPoint(station), target) ?? undefined;
}

/**
 * The close-up stop at `to`. It lands facing almost the way it will leave for
 * the next station (`orbitTo`), at most `orbitTurn` short of it on the side it
 * arrives from (`arrival`, the heading it comes in on), and the slow pass while
 * the stop is held turns the rest of the way. So the camera neither swings round
 * on landing nor on taking off.
 */
function stationStop(map: MapLibreMap, to: TourStation, from: TourStation | null, arrival: number | undefined) {
  const next = stationAfter(to), departure = next && next.id !== to.id ? departureHeading(to, next) : undefined;
  if (departure === undefined) return stopCamera(map, to, from ? stationPoint(from) : null, arrival);
  const toward = arrival === undefined ? orbitTurn : wrap(departure - arrival);
  const turn = Math.abs(toward) < 6 ? 6 * (Math.sign(toward) || 1) : clamp(toward, -orbitTurn, orbitTurn);
  return stopCamera(map, to, from ? stationPoint(from) : null, departure - turn, departure);
}

/** One move of a hop: from `start` to the view `to`, along `track` (else one smooth arc), then held for `hold` ms. */
type Leg = { start: CameraView; to: StopCamera; track: Track | null; hold?: number };

/**
 * How the camera gets from `start` (at the station `from`; null when the tour
 * starts) to the station `to`. Within a catchment it is one move, along the river
 * when one links the two stations. Entering a catchment it is three: an arc up to
 * the catchment's establishing shot, a hold there, and an arc down to the station.
 */
function planHop(map: MapLibreMap, start: CameraView, from: TourStation | null, to: TourStation): { stop: StopCamera; legs: Leg[] } {
  if (to.flat) {
    const stop = stopCamera(map, to, start.center);
    return { stop, legs: [{ start, to: stop, track: null }] };
  }
  // From far above (the overview) the camera never travels along a river.
  if (from && sameCatchment(from, to) && start.zoom > closeUpZoom - 3 && rivers) {
    const route = hopRoute(stationPoint(from), stationPoint(to));
    const stop = stationStop(map, to, from, routeHeading(route));
    return { stop, legs: [{ start, to: stop, track: cameraTrack(map, start, stop, route) }] };
  }
  const stop = stationStop(map, to, from, undefined);
  if (!to.catchment) return { stop, legs: [{ start, to: stop, track: null }] };
  const view = catchmentView(map, { ...to, catchment: to.catchment }, stop.bearing), held = orbitEnd(view);
  const afterHold: CameraView = { center: view.center, zoom: held.zoom, bearing: held.bearing ?? view.bearing, pitch: held.pitch ?? view.pitch };
  return { stop, legs: [{ start, to: view, track: null, hold: catchmentHold }, { start: afterHold, to: stop, track: null }] };
}

/** The camera at a station's close-up stop, as a flight's starting view. */
const closeUpStart = (station: TourStation): CameraView => ({ center: stationPoint(station), zoom: closeUpZoom, bearing: 0, pitch: closeUpPitch });

const cameraView = (map: MapLibreMap): CameraView =>
  ({ center: map.getCenter().toArray() as [number, number], zoom: map.getZoom(), bearing: map.getBearing(), pitch: map.getPitch() });

type TrackPoint = { point: MercatorPoint; zoom: number; pitch: number; bearing: number };
type Track = { duration: number; cruiseZoom: number; at(progress: number): TrackPoint };
const rampShare = 0.27;   // share of the flight spent speeding up, and again slowing down
const cruiseScreenSpeed = 0.7;   // screen heights of ground per second while cruising: an unhurried glide

/** Share of the distance covered at time `u` (0 to 1): a smooth start, an even cruise, a smooth stop. */
function travelled(u: number) {
  const r = rampShare, total = 1 - r;
  const ramp = (t: number) => t / 2 - r / (2 * Math.PI) * Math.sin(Math.PI * t / r);
  if (u <= r) return ramp(u) / total;
  if (u >= 1 - r) return 1 - ramp(1 - u) / total;
  return (r / 2 + (u - r)) / total;
}

/**
 * The camera's whole flight along `route` from `start` to `stop`, worked out in
 * advance: its duration, and for any moment its centre on the route, zoom, tilt
 * and heading. The same track flies the camera and tells the preload which tiles
 * the flight will show.
 */
function cameraTrack(map: MapLibreMap, start: CameraView, stop: StopCamera, route: Route): Track {
  const height = Math.max(1, map.getContainer().clientHeight);
  const screens = (length: number, zoom: number) => length * 512 * 2 ** zoom / height;   // ground length in screen heights
  const cruiseShare = 1 - 2 * rampShare, cruiseDistanceShare = cruiseShare / (1 - rampShare);
  // Longer routes take longer, up to 20 s, and are flown higher so the ground still passes at an even pace.
  let duration = clamp(4.5 + route.length / kilometres(1) * 0.009, 6, 13);
  const lowest = Math.min(start.zoom, stop.zoom) - 0.5;
  let cruiseZoom = Math.log2(cruiseScreenSpeed * duration * cruiseShare / screens(route.length * cruiseDistanceShare, 0));
  if (cruiseZoom > lowest) {
    // A short hop at the lowest cruising height: shorten the flight to keep the pace.
    cruiseZoom = lowest;
    duration = clamp(screens(route.length * cruiseDistanceShare, cruiseZoom) / (cruiseScreenSpeed * cruiseShare), 5, 13);
  }
  cruiseZoom = Math.max(6.2, cruiseZoom);
  // The camera's path is the route smoothed at the scale of more than half a
  // screen at cruising height: it follows the river's broad sweep, never its
  // every meander, so the view does not sway from side to side.
  const screenAtCruise = height / (512 * 2 ** cruiseZoom);
  const path = smoothCourse(route.points, 700, route.alongRiver ? screenAtCruise * 0.6 : 0);
  const step = route.length > 0 ? 1 / (path.length - 1) : 0;
  const pointAt = (share: number): MercatorPoint => {
    const position = clamp(share, 0, 1) * (path.length - 1), index = Math.min(path.length - 2, Math.floor(position)), t = position - index;
    return [path[index][0] + (path[index + 1][0] - path[index][0]) * t, path[index][1] + (path[index + 1][1] - path[index][1]) * t];
  };
  // The heading of travel: the direction from a little behind to well ahead of
  // the camera's point (most of a screen at cruising height), unwrapped into one
  // continuous turn and smoothed along the path.
  const lookAhead = route.length > 0 ? Math.min(0.35, screenAtCruise * 0.8 / route.length) : 0;
  const headings: number[] = [];
  for (let index = 0; index < path.length; index++) {
    const share = index * step, heading = headingBetween(pointAt(share - lookAhead * 0.3), pointAt(share + lookAhead));
    headings.push(index ? headings[index - 1] + wrap(heading - headings[index - 1]) : heading);
  }
  const alongPath = gaussian(headings, Math.max(1, path.length * lookAhead * 0.6));
  const headingAt = (share: number) => sampled(alongPath, share);
  // Over open country the tilt eases off at great heights, so the horizon stays near.
  const cruisePitch = clamp(46 + (cruiseZoom - 6.5) * 4.5, 46, 62);
  const startPitch = start.pitch ?? stop.pitch;
  const lift = (u: number) => smootherstep(clamp(u / (rampShare + 0.08), 0, 1));
  const land = (u: number) => smootherstep(clamp((u - (1 - rampShare - 0.08)) / (rampShare + 0.08), 0, 1));
  // The heading over time: from the view it leaves, onto the river ahead while
  // lifting off, along it, and onto the stop's view while landing. All in one
  // continuous (unwrapped) range of degrees, so a turn never flips round the
  // ±180° seam, then smoothed over time so the camera never turns faster than
  // a slow pan.
  const offsetToStart = start.bearing + wrap(headingAt(0) - start.bearing) - headingAt(0);
  const arriving = headingAt(1) + offsetToStart, landing = arriving + wrap(stop.bearing - arriving);
  const samples = 480, rawBearings: number[] = [];
  for (let index = 0; index <= samples; index++) {
    const u = index / samples, along = headingAt(travelled(u)) + offsetToStart;
    const lifted = start.bearing + (along - start.bearing) * lift(u);
    rawBearings.push(lifted + (landing - lifted) * land(u));
  }
  const bearings = gaussian(rawBearings, samples * turnSmoothing / duration);
  // At a stop the station sits left of centre, clear of its details panel; in
  // flight the panel is closed, so the river is brought to the middle of the
  // screen. The map's centre point is drawn this many pixels right of the
  // screen's middle (negative: left).
  const offset = (stop.padding.left - stop.padding.right) / 2;
  return {
    duration: duration * 1000,
    cruiseZoom,
    at(u) {
      const share = travelled(clamp(u, 0, 1)), up = lift(u), down = land(u);
      const zoom = start.zoom + (cruiseZoom - start.zoom) * up + (stop.zoom - cruiseZoom) * down;
      const pitch = startPitch + (cruisePitch - startPitch) * up + (stop.pitch - cruisePitch) * down;
      const bearing = sampled(bearings, u);
      // Shift the map centre sideways so the river's point is drawn mid-screen while cruising.
      const [x, y] = pointAt(share), shift = offset * (up - down) / (512 * 2 ** zoom), turn = bearing * Math.PI / 180;
      return { point: [x + Math.cos(turn) * shift, y + Math.sin(turn) * shift], zoom, pitch, bearing };
    },
  };
}

const turnSmoothing = 1.0;   // seconds over which the camera's turns are smoothed

/** Gaussian smoothing of a series with `sigma` (in samples), the window narrowing to nothing at both ends so the ends stay put. */
function gaussian(values: number[], sigma: number) {
  const radius = Math.max(1, Math.round(sigma)), last = values.length - 1;
  return values.map((value, index) => {
    const reach = Math.min(radius * 3, index, last - index);
    if (!reach) return value;
    let sum = 0, weight = 0;
    for (let offset = -reach; offset <= reach; offset++) {
      const w = Math.exp(-(offset * offset) / (2 * radius * radius));
      sum += values[index + offset] * w; weight += w;
    }
    return sum / weight;
  });
}

/** The series `values` (evenly spaced over 0 to 1) read at `share`, between samples linearly. */
function sampled(values: number[], share: number) {
  const position = clamp(share, 0, 1) * (values.length - 1), index = Math.min(values.length - 2, Math.floor(position));
  return values[index] + (values[index + 1] - values[index]) * (position - index);
}

/** Flies `track` to `stop`; resolves false if something else (user, another move) interrupted it. */
async function trackFlight(map: MapLibreMap, track: Track, stop: StopCamera) {
  if (diagnostics) map.getContainer().dataset.monitoringFlight = JSON.stringify({ river: true, cruise: +track.cruiseZoom.toFixed(2), ms: Math.round(track.duration) });
  const began = performance.now();
  let elevation: number | null = null, last = began;
  map.setTransformCameraUpdate((next) => {
    const now = performance.now(), u = clamp((now - began) / track.duration, 0, 1);
    const { point, zoom, pitch, bearing } = track.at(u);
    const center = new maplibregl.LngLat(...fromMercator(point));
    // The ground under the camera's point, followed gently so valleys and ridges never jolt it;
    // near the end it settles on the elevation the map itself lands on.
    const ground = map.queryTerrainElevation(center);
    if (ground !== null && Number.isFinite(ground)) {
      elevation = elevation === null ? ground : elevation + (ground - elevation) * (1 - Math.exp(-(now - last) / 700));
    }
    last = now;
    const settle = smootherstep(clamp((u - 0.85) / 0.15, 0, 1));
    return { center, zoom, pitch, bearing, elevation: elevation === null ? next.elevation : elevation + (next.elevation - elevation) * settle };
  });
  try {
    const { center, zoom, pitch, bearing, padding } = stop;
    return await cameraStep(map, { center, zoom, pitch, bearing, padding, duration: track.duration, easing: (t) => t });
  } finally {
    map.setTransformCameraUpdate(null);
  }
}

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
  // A descent from the overview never rises first: that would widen a view already wider than what is loaded.
  const apex = start.zoom < stop.zoom - 3 ? start.zoom : Math.max(3.6, Math.min(low, reach > 0 ? Math.log2(maxTravelSpans / reach) : low));
  const spans = reach * 2 ** start.zoom, peak = 2 ** (start.zoom - apex), end = 2 ** (start.zoom - stop.zoom);
  // flyTo's `minZoom` only caps how far a flight zooms out and never sets it, so the
  // height is set through the curve: the one whose arc (van Wijk and Nuij's flight
  // path, which flyTo follows) peaks at `apex`. `minZoom` stays as the cap.
  const curve = spans < 1e-6 || peak <= Math.max(1, end) ? 1.42
    : Math.max(0.2, Math.sqrt((Math.sqrt(peak * peak - 1) + Math.sqrt(peak * peak - end * end)) / spans));
  const climb = Math.max(0, start.zoom - apex) + Math.max(0, stop.zoom - apex);
  const turn = wrap(stop.bearing - start.bearing);
  // Unhurried: about 0.6 s per zoom level climbed or descended, and long enough
  // that the camera never turns faster than about 15° a second.
  const duration = clamp(Math.max(1800 + climb * 420 + reach * 2 ** apex * 1400, Math.abs(turn) * 70), 3500, 8500);
  // No banking: a level camera reads as calm over a wall-sized screen.
  const bank = 0;
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
  // Descending from the flat overview, the tilt comes with the descent rather than
  // with time: tilted while still high, the camera would see half a continent of
  // horizon, far more ground than is loaded.
  const descent = startPitch < 15 && stop.zoom - start.zoom > 3;
  map.setTransformCameraUpdate((transform) => {
    const u = clamp((performance.now() - began) / duration, 0, 1), k = smootherstep(u), arc = Math.sin(Math.PI * k);
    const tilt = descent ? clamp((transform.zoom - start.zoom) / (stop.zoom - start.zoom), 0, 1) ** 1.5 : k;
    // The turn is spread over the whole flight (a sine ease peaks at a gentler rate than smootherstep).
    return { pitch: startPitch + (stop.pitch - startPitch) * tilt, bearing: start.bearing + turn * easeInOutSine(u) + bank * arc };
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

const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
/** Where the hold's slow pass ends. */
function orbitEnd(stop: StopCamera): { zoom: number; bearing?: number; pitch?: number } {
  if (reducedMotion()) return { zoom: stop.zoom };
  const side = Math.sign(stop.bearing || 1);
  // A station's slow pass turns to face the way the camera will leave; a
  // catchment's establishing shot drifts in a little.
  return stop.flat ? { zoom: stop.zoom + 0.25 }
    : stop.closeUp ? { zoom: stop.zoom + 0.25, bearing: stop.orbitTo ?? stop.bearing + side * 16 }
      : stop.establishing ? { zoom: stop.zoom + 0.15, bearing: stop.bearing + side * 6, pitch: stop.pitch + 3 }
        : { zoom: stop.zoom + 0.2, bearing: stop.bearing + side * 16, pitch: stop.pitch + 4 };
}

/**
 * A slow drone pass while a stop is held: the 3D tour orbits and drifts closer
 * (a wider orbit round a close-up station), the 2D tour only drifts closer.
 * Skipped when the viewer prefers reduced motion.
 */
function holdOrbit(map: MapLibreMap, station: TourStation, stop: StopCamera, duration = 9500) {
  const end = orbitEnd(stop);
  heldView = { id: station.id, zoom: end.zoom, bearing: end.bearing ?? stop.bearing };
  if (!reducedMotion()) map.easeTo({ ...end, duration, easing: easeInOutSine, essential: true });
}

/**
 * Flies the camera to a monitoring stop from wherever it is, then starts the
 * hold orbit. Stops early once `isCurrent()` turns false; resolves true when
 * the camera actually landed at the stop.
 */
export async function runMonitoringHop(map: MapLibreMap, station: TourStation, isCurrent: () => boolean, onCatchment?: (showing: boolean) => void) {
  // A flight nobody loaded the route for (a station picked by hand mid-tour) keeps to the backdrop.
  if (preloadedFor !== station.id) { flightDetail.set(station.id, detailFloor); routePlanned.delete(station.id); }
  followDetail(map, station.id, "flight");
  // A flight leaving before even its coarse route (zoom 7) is loaded, as the
  // first one of a tour can, waits a moment for it.
  if (imageryShown(map)) await detailReached(flightDetail, station.id, detailFloor, 3000);
  // Take off on a calm main thread: changing stations rebuilds the station panel,
  // and a stalled frame as the camera starts to move reads as a jolt.
  await steadyFrames();
  if (!isCurrent()) return false;
  // Planned from exactly where the camera is now, so the flight starts without a jump.
  const from = lastStation;
  const { stop, legs } = planHop(map, cameraView(map), from, station);
  // Within a catchment the 3D tour follows the river from station to station;
  // entering one it arcs up to the catchment's establishing shot, holds it, and
  // arcs down to the station. A flight whose route was planned from a measured
  // stop glides low; before any stop has been measured it rises to where the
  // always-loaded coarse imagery suffices.
  let landed = true;
  for (const leg of legs) {
    // `onCatchment` hears when the camera heads for a catchment's establishing shot, and when it leaves it.
    onCatchment?.(Boolean(leg.hold));
    const arrived = await (leg.track ? trackFlight(map, leg.track, leg.to) : cinematicFlight(map, leg.to, routePlanned.has(station.id))) && isCurrent();
    if (!arrived) { landed = false; break; }
    if (leg.hold) {
      measureStopFootprint(map, leg.to);
      const end = orbitEnd(leg.to);
      if (!await cameraStep(map, { center: leg.to.center, ...end, padding: leg.to.padding, duration: leg.hold, easing: easeInOutSine }) || !isCurrent()) { landed = false; break; }
    }
  }
  onCatchment?.(false);
  landed &&= isCurrent();
  // An interrupted hop still counts as arriving: the next one plans from this station.
  lastStation = station;
  if (isCurrent()) followDetail(map, station.id, "stop");
  if (landed) {
    measureStopFootprint(map, stop);
    // The station's details open as the camera lands; the slow pass waits for them to settle.
    heldView = { id: station.id, zoom: orbitEnd(stop).zoom, bearing: orbitEnd(stop).bearing ?? stop.bearing };
    void steadyFrames().then((waited) => { if (isCurrent()) holdOrbit(map, station, stop, 6500 - waited); });
  }
  return landed;
}

/**
 * Resolves once three frames in a row have come at a steady rate (or after
 * `limit` ms), with how long it waited.
 */
function steadyFrames(limit = 1200) {
  return new Promise<number>((resolve) => {
    const started = performance.now();
    let last = started, calm = 0;
    const tick = (now: number) => {
      calm = now - last < 22 ? calm + 1 : 0;
      last = now;
      if (calm >= 3 || now - started > limit) resolve(Math.max(0, now - started));
      else requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}

/** Loads the coarse imagery under the whole tour (zoom 4 to 7), so even the first flight has it ready. */
export function prepareMonitoringTour() {
  void tourBackdrop().catch(() => undefined);
}

/** Ends the tour's hold on the map's imagery detail (monitoring mode turned off). */
export function endMonitoringTour(map: MapLibreMap) {
  detailFollows = null;
  lastStation = null;
  setImageryMaxzoom(map, null);
  setTourTileCache(map, false);
}

// While touring, the imagery's cache of ready-to-draw tiles on the graphics card
// holds about three times its usual number (some 3500 tiles at full-HD), so a
// long river flight's preloaded tiles are still there when the camera reaches them.
let usualCacheLevels: number | null = null;
function setTourTileCache(map: MapLibreMap, touring: boolean) {
  const tiles = (map as unknown as { style?: { tileManagers?: Record<string, { _maxTileCacheZoomLevels: number | null }> } }).style?.tileManagers?.[imagerySourceId];
  if (!tiles) return;
  usualCacheLevels ??= tiles._maxTileCacheZoomLevels ?? 28;
  tiles._maxTileCacheZoomLevels = touring ? usualCacheLevels * 3 : usualCacheLevels;
}

// The detail cap. With 3D terrain the map swaps a sharper imagery tile in within
// one frame (it cross-fades tiles only on a flat map), so a tile arriving while
// the camera is over it shows as a sharp square on the blurred one beneath. The
// tour therefore caps the imagery source's highest zoom at the finest level that
// is fully loaded for what is on screen: the flight's whole route while flying,
// the stop while it is held. Routes load coarse levels first, so the cap rises
// as downloads finish and the view sharpens as a whole, never square by square.
const detailFloor = imageryBackdropMaxZoom;   // the coarse level the backdrop loads over the whole tour region
const firstLevel = 5;   // the level a route starts from, before any of it is loaded: the overview map's own
const flightDetail = new Map<string, number>();   // station → finest level loaded for the whole flight there
const stopDetail = new Map<string, number>();   // station → finest level loaded for its stop and hold
const routePlanned = new Set<string>();   // stations whose flight route was known (from a measured stop) when it was loaded
let detailFollows: { map: MapLibreMap; station: string; phase: "flight" | "stop" } | null = null;
let uncappedMaxzoom: number | null = null;

function setImageryMaxzoom(map: MapLibreMap, level: number | null) {
  const source = map.getSource(imagerySourceId) as { maxzoom: number } | undefined;
  if (!source) return;
  uncappedMaxzoom ??= source.maxzoom;
  const maxzoom = level === null ? uncappedMaxzoom : Math.min(level, tourMaxDetail);
  if (source.maxzoom === maxzoom) return;
  source.maxzoom = maxzoom;
  if (diagnostics) map.getContainer().dataset.monitoringDetail = String(level ?? "");
  map.triggerRepaint();
}

function followDetail(map: MapLibreMap, station: string, phase: "flight" | "stop") {
  detailFollows = { map, station, phase };
  setTourTileCache(map, true);
  applyDetailCap();
}

function applyDetailCap() {
  if (!detailFollows) return;
  const { map, station, phase } = detailFollows;
  setImageryMaxzoom(map, (phase === "flight" ? flightDetail : stopDetail).get(station) ?? firstLevel);
}

const detailWaiters = new Set<() => void>();
function raiseDetail(levels: Map<string, number>, station: string, level: number) {
  if ((levels.get(station) ?? -1) >= level) return;
  levels.set(station, level);
  applyDetailCap();
  for (const waiter of [...detailWaiters]) waiter();
}

/** Resolves once `station` has reached `level` in `levels`, or after `timeout` ms. */
function detailReached(levels: Map<string, number>, station: string, level: number, timeout: number) {
  return new Promise<void>((resolve) => {
    const check = () => {
      if ((levels.get(station) ?? -1) < level) return;
      detailWaiters.delete(check);
      clearTimeout(timer);
      resolve();
    };
    const timer = setTimeout(() => { detailWaiters.delete(check); resolve(); }, timeout);
    detailWaiters.add(check);
    check();
  });
}

/** The tiles `keys` ("z/x/y") at no finer than `level`: a finer tile is replaced by its ancestor at that level. */
function atLevel(keys: string[], level: number) {
  const tiles = new Set<string>();
  for (const key of keys) {
    const [z, x, y] = key.split("/").map(Number);
    tiles.add(z <= level ? key : `${level}/${x >> (z - level)}/${y >> (z - level)}`);
  }
  return [...tiles];
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
  _outOfViewCache: { has(id: unknown): boolean; add(id: unknown, tile: CachedTile): unknown; getAndRemove(id: unknown): CachedTile | undefined };
};
/**
 * Puts imagery tiles ("z/x/y") in the map's own cache of ready-to-draw tiles,
 * as textures on the graphics card. When the camera reaches them they are drawn
 * in the same frame, so a coarser tile is never seen being replaced by a sharper
 * one. A tile already in that cache is moved to its newest end: the cache drops
 * its oldest tiles first, so those the coming flight needs stay. The map has no
 * public call for this, so it uses the map's tile store directly; it resolves
 * false, having done nothing, if that store is not as expected.
 */
async function keepImageryOnGpu(map: MapLibreMap, keys: string[], concurrency = 12) {
  try {
    const tiles = (map as unknown as { style?: { tileManagers?: Record<string, ImageryTiles> } }).style?.tileManagers?.[imagerySourceId];
    const sample = tiles?.getTileByID(tiles.getIds()[0] ?? "");
    if (!tiles || !sample) return false;
    const Tile = sample.constructor, TileId = sample.tileID.constructor as new (overscaledZ: number, wrap: number, z: number, x: number, y: number) => { key: string };
    const cache = tiles._outOfViewCache;
    const ready = (id: { key: string }) => Boolean(tiles.getTileByID(id.key)) || cache.has(id);
    const pending = [...new Set(keys)];
    let next = 0;
    await Promise.all(Array.from({ length: Math.min(concurrency, pending.length) }, async () => {
      while (next < pending.length) {
        const [z, x, y] = pending[next++].split("/").map(Number), id = new TileId(z, 0, z, x, y);
        if (cache.has(id)) { const kept = cache.getAndRemove(id); if (kept) cache.add(id, kept); continue; }
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

/**
 * Tiles the stop view will need, from landing to the end of the hold's slow
 * pass: the measured footprint moved there, or rings around it before any landing.
 */
function stopTiles(stop: StopCamera, target: [number, number]) {
  const footprint = footprintFor(stop);
  if (!footprint) {
    const z = Math.floor(stop.zoom);
    return { terrain: [...tilesAround(target, z - 1, 1), ...tilesAround(target, z, 2)], detail: [...tilesAround(target, z + 1, 3), ...tilesAround(target, z + 2, 2)] };
  }
  const end = orbitEnd(stop), endBearing = end.bearing ?? stop.bearing, terrain = new Set<string>(), detail = new Set<string>();
  // The start, middle and end of the slow pass, which turns the view by up to 40°.
  for (const view of [0, 0.5, 1].map((t) => ({ zoom: stop.zoom + (end.zoom - stop.zoom) * t, bearing: stop.bearing + (endBearing - stop.bearing) * t }))) {
    const turn = view.bearing - footprint.bearing, zoomChange = view.zoom - footprint.zoom;
    for (const key of footprintKeys(footprint.terrain, target, turn, zoomChange)) terrain.add(key);
    for (const key of footprintKeys(footprint.detail, target, turn, zoomChange)) detail.add(key);
  }
  return { terrain: [...terrain], detail: [...detail] };
}

/**
 * Tiles the flight from `start` to `stop` passes over, in the order it reaches
 * them: the stop footprint carried along the flight's own path, at the zoom and
 * heading the camera has at each point. Empty before any landing has been measured.
 */
function flightTiles(map: MapLibreMap, start: CameraView, stop: StopCamera, track: Track | null) {
  const footprint = footprintFor(stop), terrain = new Set<string>(), detail = new Set<string>();
  if (!footprint) return { terrain: [], detail: [] };
  if (track) {
    // About three views for every screen of ground the camera crosses.
    const count = Math.round(clamp(track.duration / 1000 * cruiseScreenSpeed * 3 + 10, 12, 160));
    for (let index = 0; index <= count; index++) {
      const { point, zoom, bearing } = track.at(index / count);
      for (const key of footprintKeys(footprint.terrain, point, bearing - footprint.bearing, zoom - footprint.zoom)) terrain.add(key);
      for (const key of footprintKeys(footprint.detail, point, bearing - footprint.bearing, zoom - footprint.zoom)) detail.add(key);
    }
    return { terrain: [...terrain], detail: [...detail] };
  }
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

// The preload for the hop about to be flown; the background warm-up waits for it, as the two share one slow download.
let hopPreload: Promise<unknown> = Promise.resolve();
let preloadedFor: string | null = null;   // the station that preload leads to

const imageryShown = (map: MapLibreMap) => Boolean(map.getLayer(imagerySourceId)) && map.getLayoutProperty(imagerySourceId, "visibility") !== "none";

/**
 * Tiles a whole hop shows, in the order it shows them: every leg's flight, the
 * catchment's establishing shot while it is held, and the station's stop.
 */
function hopTiles(map: MapLibreMap, start: CameraView, from: TourStation | null, to: TourStation) {
  const { stop, legs } = planHop(map, start, from, to);
  const terrain = new Set<string>(), detail = new Set<string>();
  for (const leg of legs) {
    const way = flightTiles(map, leg.start, leg.to, leg.track);
    const held = leg.hold ? stopTiles(leg.to, mercator(...leg.to.center)) : { terrain: [], detail: [] };
    for (const key of [...way.terrain, ...held.terrain]) terrain.add(key);
    for (const key of [...way.detail, ...held.detail]) detail.add(key);
  }
  return { stop, way: { terrain: [...terrain], detail: [...detail] } };
}

/**
 * Loads elevation and imagery for the hop to the next stop, imagery going
 * straight onto the graphics card. Imagery comes level by level, coarse first:
 * the stop and the whole route up to zoom 10 (a few dozen tiles), then the stop
 * at full detail, then the route one finer level at a time. After each level the
 * detail cap for that flight or stop is raised to it. `from` is the stop being
 * held (null when the tour is starting). The returned promise settles once all
 * of it is loaded.
 */
export function preloadMonitoringHop(map: MapLibreMap, from: TourStation | null, to: TourStation) {
  recallFootprints(map);
  const satellite = imageryShown(map);
  const backdrop = satellite ? tourBackdrop() : Promise.resolve();
  // The flight leaves from where the hold's slow pass ends, or from the camera as it is now.
  const now = cameraView(map);
  const start: CameraView = from && heldView?.id === from.id ? { ...now, zoom: heldView.zoom, bearing: heldView.bearing } : now;
  const { stop, way } = hopTiles(map, start, from, to), target = mercator(...stop.center);
  const tiles = stopTiles(stop, target);
  const stopTerrain = byDistance(tiles.terrain, target), stopImagery = byDistance(tiles.detail, target);
  // What the flight needs beyond the stop's own tiles (elevation and imagery tiles are separate sets).
  const stopTerrainKeys = new Set(stopTerrain), stopImageryKeys = new Set(stopImagery);
  const wayTerrain = way.terrain.filter((key) => !stopTerrainKeys.has(key)).slice(0, maxWayTiles);
  // The route in the order the camera reaches it, ending at the stop.
  const route = [...way.detail.filter((key) => !stopImageryKeys.has(key)), ...stopImagery];
  if (footprintFor(stop)) routePlanned.add(to.id); else routePlanned.delete(to.id);
  // A new route: none of it counts as loaded yet.
  flightDetail.set(to.id, firstLevel);
  applyDetailCap();
  // Hillshade (256 px DEM tiles) only renders with the studio's relief on.
  const shade = map.getLayer("station-terrain-shade") && map.getLayoutProperty("station-terrain-shade", "visibility") === "visible";
  const started = performance.now(), container = map.getContainer();
  if (diagnostics) container.dataset.monitoringPreloadPlan = JSON.stringify({ stopTerrain, stopDetail: stopImagery, wayTerrain, wayDetail: route.slice(0, route.length - stopImagery.length) });
  const imagery = async () => {
    if (!satellite) {
      // Vector background: no imagery is drawn, so nothing needs holding back.
      raiseDetail(stopDetail, to.id, tourMaxDetail);
      raiseDetail(flightDetail, to.id, tourMaxDetail);
      return;
    }
    // Without a measured stop the route is unknown: that flight keeps to the backdrop.
    const planned = routePlanned.has(to.id), coarse = 10;
    if (!planned) void backdrop.then(() => raiseDetail(flightDetail, to.id, detailFloor), () => undefined);
    // The coarsest levels are a handful of tiles each, so even a first flight soon has a whole picture.
    for (let level = firstLevel + 1; level <= coarse; level++) {
      await preloadImagery(map, atLevel(route, level), 12, true);
      raiseDetail(stopDetail, to.id, level);
      if (planned) raiseDetail(flightDetail, to.id, level);
    }
    for (let level = coarse + 1; level <= tourMaxDetail; level++) {
      await preloadImagery(map, atLevel(stopImagery, level), 12, true);
      raiseDetail(stopDetail, to.id, level);
    }
    // A flight is only allowed a level whose whole route is loaded; a level too
    // large to load in reasonable time ends the climb.
    if (!planned) return;
    for (let level = coarse + 1; level <= tourMaxDetail; level++) {
      const keys = atLevel(route, level);
      if (keys.length > maxLevelTiles) break;
      // The first stretch goes onto the graphics card; a long river route's
      // remainder waits in memory, a few milliseconds from the screen, as the
      // camera only meets it at the far edge of the view.
      await Promise.all([preloadImagery(map, keys.slice(0, maxGpuRouteTiles), 12, true), preloadImageryTiles(keys.slice(maxGpuRouteTiles), 12)]);
      raiseDetail(flightDetail, to.id, level);
    }
  };
  const loaded = Promise.all([
    // The 2D tour has no terrain to load.
    to.flat ? Promise.resolve() : preloadTerrainTiles(png([...stopTerrain, ...wayTerrain, ...(shade ? [...stopImagery, ...route.slice(0, maxWayTiles)] : [])])),
    imagery(),
  ]).then(() => {
    container.dataset.monitoringPreloadMs = String(Math.round(performance.now() - started));
  });
  hopPreload = loaded;
  preloadedFor = to.id;
  return loaded;
}

/**
 * Every tile the tour draws, for building the local tile pack: each stop with
 * its hold, each flight between consecutive stops at every level of detail it
 * steps through, the first flight in from the camera's current view (the
 * overview), and the backdrop. Imagery keys are "z/x/y"; terrain keys are the
 * 512 px mesh tiles as "z/x/y".
 */
export function monitoringTourTiles(map: MapLibreMap, stations: TourStation[]) {
  recallFootprints(map);
  const imagery = new Set<string>(backdropTileKeys(tourRegion, tourHorizon)), terrain = new Set<string>();
  const overview = cameraView(map);
  const addRoute = (keys: string[]) => {
    for (let level = firstLevel; level <= tourMaxDetail; level++) for (const key of atLevel(keys, level)) imagery.add(key);
  };
  stations.forEach((to, index) => {
    const count = stations.length, from = stations[(index - 1 + count) % count], before = stations[(index - 2 + count) % count];
    const starts = [count > 1 ? departureView(map, from, before) : null, index === 0 ? overview : null];
    for (const start of starts) {
      if (!start) continue;
      const { stop, way } = hopTiles(map, start, start === overview ? null : from, to);
      const tiles = stopTiles(stop, mercator(...stop.center));
      for (const key of [...tiles.terrain, ...way.terrain]) terrain.add(key);
      addRoute(tiles.detail);
      addRoute(way.detail);
    }
  });
  return { measured: Boolean(footprints.closeUp ?? footprints.catchment ?? footprints.flat), stations: stations.length, imagery: [...imagery], terrain: [...terrain] };
}

/** The view a flight from `from` leaves from: where the hold's slow pass there ends (`before` is the stop before it). */
function departureView(map: MapLibreMap, from: TourStation, before: TourStation): CameraView {
  const held = planHop(map, closeUpStart(before), before, from).stop, end = orbitEnd(held);
  return { center: held.center, zoom: end.zoom, bearing: end.bearing ?? held.bearing, pitch: end.pitch ?? held.pitch };
}

// After the first landing, quietly fetch the imagery and terrain for every stop
// on the tour, then for every flight between them, so later hops find their
// tiles in the persistent tile caches and are ready within a second or two.
// Stops and flights already warmed this session are skipped.
const warmedStations = new Set<string>();
const warmedFlights = new Set<string>();
let warming = false;
export function warmMonitoringTour(map: MapLibreMap, stations: TourStation[], fromIndex: number, isActive: () => boolean) {
  if (warming || !(footprints.flat ?? footprints.closeUp ?? footprints.catchment) || fromIndex < 0) return;
  const order = [...stations.slice(fromIndex + 1), ...stations.slice(0, fromIndex + 1)];
  const previous = (index: number) => index ? order[index - 1] : stations[fromIndex];
  warming = true;
  void (async () => {
    try {
      // Low concurrency throughout: this runs alongside each hop's own, more urgent preload.
      for (let index = 0; index < order.length && isActive(); index++) {
        const to = order[index], from = previous(index);
        if (warmedStations.has(to.id)) continue;
        await hopPreload.catch(() => undefined);
        const stop = planHop(map, closeUpStart(from), from, to).stop, target = mercator(...stop.center);
        const tiles = stopTiles(stop, target);
        // Only what the app does not ship: shipped tiles load from disk in milliseconds when needed.
        await Promise.all([to.flat ? Promise.resolve() : preloadTerrainTiles(png(tiles.terrain), true), preloadImagery(map, await imageryOutsidePack(byDistance(tiles.detail, target)), 4)]);
        warmedStations.add(to.id);
      }
      for (let index = 0; index < order.length && isActive(); index++) {
        const to = order[index], from = previous(index), key = `${from.id}>${to.id}`;
        if (warmedFlights.has(key) || from.id === to.id) continue;
        await hopPreload.catch(() => undefined);
        const before = index > 1 ? order[index - 2] : index === 1 ? stations[fromIndex] : stations[(fromIndex - 1 + stations.length) % stations.length];
        const { way } = hopTiles(map, departureView(map, from, before), from, to);
        // Every level the hop's own preload steps through, as far as it would go.
        const levels: string[] = [];
        for (let level = 8; level <= tourMaxDetail; level++) {
          const keys = atLevel(way.detail, level);
          if (keys.length > maxLevelTiles) break;
          levels.push(...keys);
        }
        await Promise.all([
          to.flat ? Promise.resolve() : preloadTerrainTiles(png(way.terrain.slice(0, maxWayTiles)), true),
          preloadImagery(map, await imageryOutsidePack(levels), 4),
        ]);
        warmedFlights.add(key);
      }
    } finally {
      warming = false;
    }
  })();
}
