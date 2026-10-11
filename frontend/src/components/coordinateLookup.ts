import { bbox } from "@turf/bbox";
import { booleanPointInPolygon } from "@turf/boolean-point-in-polygon";
import type { Feature, FeatureCollection, MultiPolygon, Polygon } from "geojson";

export interface MapCoordinate { latitude: number; longitude: number }
export interface CoordinateMatch { kind: string; name: string; fields: [string, string][] }
interface LookupGroup { kind: string; collection: FeatureCollection; nameKey: string; fields: [string, string][] }
interface IndexedPolygon { feature: Feature<Polygon | MultiPolygon>; bounds: number[]; match: CoordinateMatch }

export function parseMapCoordinate(latitude: string, longitude: string): MapCoordinate {
  if (!latitude.trim() || !longitude.trim()) throw new Error("Enter both latitude and longitude.");
  const lat = Number(latitude);
  const lon = Number(longitude);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) throw new Error("Coordinates must be valid numbers.");
  if (lat < -90 || lat > 90) throw new Error("Latitude must be between -90 and 90.");
  if (lon < -180 || lon > 180) throw new Error("Longitude must be between -180 and 180.");
  if (Math.abs(lat) > 85.051129) throw new Error("This map supports latitudes between -85.051129 and 85.051129.");
  return { latitude: lat, longitude: lon };
}

export function coordinateMatch(kind: string, properties: Record<string, unknown>, nameKey: string, fields: [string, string][]): CoordinateMatch {
  return { kind, name: String(properties[nameKey] ?? properties.id ?? kind), fields: fields.flatMap(([key, label]) => {
    const value = properties[key];
    if (value == null || value === "") return [];
    return [[label, typeof value === "number" && ["risk_probability", "confidence"].includes(key)
      ? `${Math.round(value * 100)}%` : String(value)] as [string, string]];
  }) };
}

export function indexCoordinatePolygons(groups: LookupGroup[]): IndexedPolygon[] {
  return groups.flatMap((group) => group.collection.features.flatMap((feature) => {
    if (!["Polygon", "MultiPolygon"].includes(feature.geometry.type)) return [];
    return [{ feature: feature as Feature<Polygon | MultiPolygon>, bounds: bbox(feature),
      match: coordinateMatch(group.kind, feature.properties ?? {}, group.nameKey, group.fields) }];
  }));
}

export function lookupCoordinatePolygons(point: MapCoordinate, index: IndexedPolygon[]): CoordinateMatch[] {
  return index.filter(({ feature, bounds }) => point.longitude >= bounds[0] && point.longitude <= bounds[2]
    && point.latitude >= bounds[1] && point.latitude <= bounds[3]
    && booleanPointInPolygon([point.longitude, point.latitude], feature)).map(({ match }) => match);
}
