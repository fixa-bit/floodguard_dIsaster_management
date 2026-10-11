import { bbox } from "@turf/bbox";
import { booleanPointInPolygon } from "@turf/boolean-point-in-polygon";
import { intersect } from "@turf/intersect";
import { lineSplit } from "@turf/line-split";
import type { Feature, FeatureCollection, Geometry, LineString, Polygon, MultiPolygon } from "geojson";
import type { MapCoordinate } from "./coordinateLookup";

export type StudyLayer = "districts" | "risk" | "catchments" | "glaciers" | "water" | "waterForecasts" | "gauges" | "floodHub" | "stations" | "incidents" | "reports" | "resources" | "rainfall";
export interface StudyDataset { layer: StudyLayer; collection: FeatureCollection | null }
type Catchment = Feature<Polygon | MultiPolygon>;
const boundsCache = new WeakMap<Feature, number[]>();
const clipCache = new WeakMap<Catchment, WeakMap<FeatureCollection, FeatureCollection>>();
const empty: FeatureCollection = { type: "FeatureCollection", features: [] };

function featureBounds(feature: Feature) {
  let bounds = boundsCache.get(feature);
  if (!bounds) { bounds = bbox(feature); boundsCache.set(feature, bounds); }
  return bounds;
}

export function districtAtCoordinate(point: MapCoordinate, collection: FeatureCollection | null): FeatureCollection {
  const match = collection?.features.find((feature) => {
    if (!["Polygon", "MultiPolygon"].includes(feature.geometry.type)) return false;
    const bounds = featureBounds(feature);
    return point.longitude >= bounds[0] && point.longitude <= bounds[2] && point.latitude >= bounds[1] && point.latitude <= bounds[3]
      && booleanPointInPolygon([point.longitude, point.latitude], feature as Catchment);
  });
  return match ? { type: "FeatureCollection", features: [match] } : empty;
}

function clipGeometry(geometry: Geometry, catchment: Catchment): Geometry | null {
  if (geometry.type === "Point") return booleanPointInPolygon(geometry.coordinates, catchment) ? geometry : null;
  if (geometry.type === "MultiPoint") {
    const coordinates = geometry.coordinates.filter((point) => booleanPointInPolygon(point, catchment));
    return coordinates.length ? { type: "MultiPoint", coordinates } : null;
  }
  if (geometry.type === "Polygon" || geometry.type === "MultiPolygon") {
    return intersect({ type: "FeatureCollection", features: [catchment, { type: "Feature", properties: {}, geometry }] })?.geometry ?? null;
  }
  if (geometry.type === "LineString" || geometry.type === "MultiLineString") {
    const lines = geometry.type === "LineString" ? [geometry.coordinates] : geometry.coordinates;
    const coordinates = lines.flatMap((line) => {
      const original: Feature<LineString> = { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: line } };
      const split = lineSplit(original, catchment).features;
      // Each split segment has no interior crossing; sample a nonzero edge, not a boundary endpoint.
      return (split.length ? split : [original]).filter((segment) => {
        const points = segment.geometry.coordinates;
        for (let index = 1; index < points.length; index++) {
          const [a, b] = [points[index - 1], points[index]];
          if (a[0] !== b[0] || a[1] !== b[1]) return booleanPointInPolygon([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], catchment);
        }
        return false;
      }).map((segment) => segment.geometry.coordinates);
    });
    if (!coordinates.length) return null;
    return coordinates.length === 1 ? { type: "LineString", coordinates: coordinates[0] } : { type: "MultiLineString", coordinates };
  }
  const geometries = geometry.geometries.flatMap((child) => {
    const clipped = clipGeometry(child, catchment);
    return clipped ? [clipped] : [];
  });
  return geometries.length ? { type: "GeometryCollection", geometries } : null;
}

export function clipToCatchment(collection: FeatureCollection | null, catchment: Catchment | null): FeatureCollection {
  if (!collection || !catchment) return empty;
  let cache = clipCache.get(catchment);
  if (!cache) { cache = new WeakMap(); clipCache.set(catchment, cache); }
  const cached = cache.get(collection);
  if (cached) return cached;
  const area = featureBounds(catchment);
  const features = collection.features.flatMap((feature) => {
    if (!feature.geometry) return [];
    const bounds = featureBounds(feature);
    if (bounds[0] > area[2] || bounds[2] < area[0] || bounds[1] > area[3] || bounds[3] < area[1]) return [];
    const geometry = clipGeometry(feature.geometry, catchment);
    return geometry ? [{ ...feature, geometry }] : [];
  });
  const clipped: FeatureCollection = { type: "FeatureCollection", features };
  cache.set(collection, clipped);
  return clipped;
}

export function correspondingStudyLayers(datasets: StudyDataset[]): Partial<Record<StudyLayer, boolean>> {
  return Object.fromEntries(datasets.filter((dataset) => dataset.collection?.features.length).map((dataset) => [dataset.layer, true]));
}
