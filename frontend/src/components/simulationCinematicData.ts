import type { FeatureCollection, Geometry, MultiPolygon, Polygon, Position } from "geojson";
import type { FloodExposurePreview } from "./outlookFloodExposureData";

function polygons(geometry: Geometry): Polygon["coordinates"][] {
  if (geometry.type === "Polygon") return [geometry.coordinates];
  if (geometry.type === "MultiPolygon") return geometry.coordinates;
  if (geometry.type === "GeometryCollection") return geometry.geometries.flatMap(polygons);
  return [];
}

// Inset glyphs create space between columns. Original grid geometry/counts and
// all population/footprint calculations remain untouched.
export function cinematicPopulation(data: FloodExposurePreview): FeatureCollection<MultiPolygon, { id: number; population_2025: number; density_km2: number }> {
  return { type: "FeatureCollection", features: data.population.features.flatMap((feature) => {
    const parts = polygons(feature.geometry);
    const points = parts.flatMap((part) => part.flat());
    if (!points.length) return [];
    let west = Infinity, south = Infinity, east = -Infinity, north = -Infinity;
    points.forEach(([x, y]) => { west = Math.min(west, x); south = Math.min(south, y); east = Math.max(east, x); north = Math.max(north, y); });
    const cx = (west + east) / 2, cy = (south + north) / 2;
    return [{ type: "Feature" as const, id: feature.id, properties: { id: feature.properties.id, population_2025: feature.properties.population_2025, density_km2: feature.properties.density_km2 }, geometry: { type: "MultiPolygon" as const, coordinates: parts.map((part) => part.map((ring) => ring.map(([x, y]) => [cx + (x - cx) * .64, cy + (y - cy) * .64]))) } }];
  }) };
}

export function densityFocus(data: FloodExposurePreview): [number, number] | null {
  const feature = data.population.features.reduce<(typeof data.population.features)[number] | null>((best, item) => !best || item.properties.density_km2 > best.properties.density_km2 ? item : best, null);
  const points = feature && polygons(feature.geometry).flatMap((part) => part.flat());
  if (!points?.length) return null;
  const firstRing = polygons(feature!.geometry)[0][0];
  const unique = firstRing.slice(0, -1);
  return [unique.reduce((sum, point) => sum + point[0], 0) / unique.length, unique.reduce((sum, point) => sum + point[1], 0) / unique.length];
}

function linePoints(geometry: Geometry): Position[] {
  if (geometry.type === "LineString") return geometry.coordinates;
  if (geometry.type === "MultiLineString") return geometry.coordinates.flat();
  if (geometry.type === "GeometryCollection") return geometry.geometries.flatMap(linePoints);
  return [];
}

export function riverFocus(data: FloodExposurePreview, reference: readonly number[]): [number, number] | null {
  const points = data.river_lines.features.flatMap((feature) => feature.geometry ? linePoints(feature.geometry) : []);
  if (!points.length) return null;
  const distance = ([x, y]: Position) => ((x - reference[0]) * Math.cos(reference[1] * Math.PI / 180)) ** 2 + (y - reference[1]) ** 2;
  const closest = points.reduce((best, point) => distance(point) < distance(best) ? point : best);
  return [closest[0], closest[1]];
}
