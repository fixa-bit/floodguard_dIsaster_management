import type { FeatureCollection, MultiPolygon, Polygon } from "geojson";
import type { NationalRiskCollection } from "../types/api";

export type DistrictBoundaries = FeatureCollection<Polygon | MultiPolygon, { district: string | null }>;

export function districtDisplayGeometry(boundaries: DistrictBoundaries | null, context: DistrictBoundaries | null): FeatureCollection {
  return { type: "FeatureCollection", features: [boundaries, context].flatMap((collection) =>
    (collection?.features ?? []).filter((feature) => feature.properties.district?.trim()).map((feature) => ({
      ...feature, properties: { ...feature.properties, district_name: feature.properties.district },
    }))) };
}

function districtKey(name: string) {
  return name.trim().toLowerCase().replace(/[^a-z0-9]/g, "");
}

export function alignDistrictScreeningGeometry(risk: NationalRiskCollection | null, boundaries: DistrictBoundaries | null): NationalRiskCollection | null {
  if (!risk || !boundaries) return risk;
  const districts = new Map<string, DistrictBoundaries["features"]>();
  for (const feature of boundaries.features) {
    if (!feature.properties.district) continue;
    const key = districtKey(feature.properties.district);
    const matches = districts.get(key) ?? [];
    matches.push(feature);
    districts.set(key, matches);
  }
  return {
    ...risk,
    features: risk.features.map((feature) => {
      const matches = districts.get(districtKey(feature.properties.district_name));
      // Only exact, unique names are safe to join; do not guess renamed or split districts.
      if (matches?.length !== 1) return feature;
      return { ...feature, geometry: matches[0].geometry, properties: { ...feature.properties,
        display_boundary_source: "Pakistan district boundary adapter", display_geometry_match: true } };
    }),
  };
}
