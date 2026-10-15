import { booleanPointInPolygon } from "@turf/boolean-point-in-polygon";
import type { Feature, Geometry, Polygon, Position } from "geojson";
import type { FloodExposurePreview } from "./outlookFloodExposureData";

export const REPLAY_MINUTES = 360;
export const REPLAY_PEAK_MINUTE = 198;
export const replayScenarios = [
  { id: "lower", label: "Lower spread", peak: 2 },
  { id: "moderate", label: "Moderate spread", peak: 3 },
  { id: "higher", label: "Higher spread", peak: 5 },
] as const;
export type ReplayScenario = typeof replayScenarios[number]["id"];
export type Coordinate = [number, number];

// A hand-authored rise/recession sequence, not a hydrological model or event.
export function replayLevel(minute: number, scenario: ReplayScenario): number {
  const time = Math.max(0, Math.min(REPLAY_MINUTES, minute));
  const peak = replayScenarios.find((item) => item.id === scenario)!.peak;
  const phase = time <= REPLAY_PEAK_MINUTE ? time / REPLAY_PEAK_MINUTE : (REPLAY_MINUTES - time) / (REPLAY_MINUTES - REPLAY_PEAK_MINUTE);
  return Math.min(peak, Math.max(0, Math.round(peak * Math.sin(phase * Math.PI / 2) ** 1.6)));
}

export function replayClock(minute: number) {
  const time = Math.max(0, Math.min(REPLAY_MINUTES, Math.round(minute)));
  return `${Math.floor(time / 60).toString().padStart(2, "0")}:${(time % 60).toString().padStart(2, "0")}`;
}

export function polygonParts(geometry: Geometry | null): Polygon[] {
  if (!geometry) return [];
  if (geometry.type === "Polygon") return [geometry];
  if (geometry.type === "MultiPolygon") return geometry.coordinates.map((coordinates) => ({ type: "Polygon", coordinates }));
  if (geometry.type === "GeometryCollection") return geometry.geometries.flatMap(polygonParts);
  return [];
}

export function waterPolygons(data: FloodExposurePreview | null, level: number): Polygon[] {
  if (!data?.supported || level <= 0) return [];
  return data.water.features.filter((feature) => Number(feature.properties?.min_level) <= level).flatMap((feature) => polygonParts(feature.geometry));
}

export function distanceKm(a: Position, b: Position) {
  const rad = Math.PI / 180;
  const value = Math.sin((b[1] - a[1]) * rad / 2) ** 2 + Math.cos(a[1] * rad) * Math.cos(b[1] * rad) * Math.sin((b[0] - a[0]) * rad / 2) ** 2;
  return 6371.0088 * 2 * Math.asin(Math.sqrt(Math.min(1, value)));
}

// Midpoint quadrature over 512 equal subdivisions of the user-drawn line.
// Returns spatial overlap only. Never infer a flow, velocity, or depth from it.
export function inspectReplayLine(points: Coordinate[], polygons: Polygon[], samples = 512) {
  if (points.length !== 2) return null;
  const [a, b] = points;
  const lengthKm = distanceKm(a, b);
  const prepared = polygons.map((geometry) => {
    const vertices = geometry.coordinates.flat();
    const x = vertices.map((p) => p[0]), y = vertices.map((p) => p[1]);
    return { geometry, bounds: [Math.min(...x), Math.min(...y), Math.max(...x), Math.max(...y)] };
  });
  const wet = Array.from({ length: samples }, (_, index) => {
    const fraction = (index + .5) / samples;
    const point: Coordinate = [a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction];
    return prepared.some(({ geometry, bounds }) => point[0] >= bounds[0] && point[0] <= bounds[2] && point[1] >= bounds[1] && point[1] <= bounds[3] && booleanPointInPolygon(point, geometry));
  });
  return { lengthKm, wetKm: lengthKm * wet.filter(Boolean).length / samples, wet, resolutionKm: lengthKm / samples };
}

function lineParts(geometry: Geometry | null): Position[][] {
  if (!geometry) return [];
  if (geometry.type === "LineString") return [geometry.coordinates];
  if (geometry.type === "MultiLineString") return geometry.coordinates;
  if (geometry.type === "GeometryCollection") return geometry.geometries.flatMap(lineParts);
  return [];
}

export type CurrentRoute = { points: Coordinate[]; distances: number[]; length: number };
export function currentRoutes(data: FloodExposurePreview): CurrentRoute[] {
  return data.river_lines.features.flatMap((feature) => lineParts(feature.geometry)).filter((points) => points.length > 1).flatMap((line) => {
    const points = line.map((point) => [point[0], point[1]] as Coordinate);
    const distances = [0];
    for (let i = 1; i < points.length; i++) distances.push(distances[i - 1] + distanceKm(points[i - 1], points[i]));
    const length = distances.at(-1)!;
    return length > .01 ? [{ points, distances, length }] : [];
  });
}

export function routePoint(route: CurrentRoute, fraction: number): { point: Coordinate; normal: Coordinate } {
  const distance = ((fraction % 1 + 1) % 1) * route.length;
  let low = 1, high = route.distances.length - 1;
  while (low < high) { const mid = (low + high) >>> 1; if (route.distances[mid] < distance) low = mid + 1; else high = mid; }
  const a = route.points[low - 1], b = route.points[low];
  const part = (distance - route.distances[low - 1]) / Math.max(1e-9, route.distances[low] - route.distances[low - 1]);
  const cos = Math.cos(a[1] * Math.PI / 180);
  const dx = (b[0] - a[0]) * cos, dy = b[1] - a[1], norm = Math.hypot(dx, dy) || 1;
  return { point: [a[0] + (b[0] - a[0]) * part, a[1] + (b[1] - a[1]) * part], normal: [-dy / norm / cos, dx / norm] };
}

export function transectFeature(points: Coordinate[]): Feature | null {
  if (points.length !== 2) return null;
  return { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: points } };
}
