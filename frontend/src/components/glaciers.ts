import type { Feature, FeatureCollection, MultiPolygon, Polygon } from "geojson";
import type { FilterSpecification } from "maplibre-gl";

export type GlacierConnection = "pakistan_contributor" | "divide_uncertain" | "other_basin";
export type GlacierView = "all" | "contributors" | "external";
export interface GlacierProperties {
  id: string;
  name: string;
  glims_id: string;
  area_km2: number;
  source_date: string | null;
  source: string;
  connection: GlacierConnection;
  outside_pakistan_boundary: boolean;
  highlight: string;
  drainage: string;
  main_basin_id: number | null;
  latitude: number;
  longitude: number;
}
export type GlacierFeature = Feature<Polygon | MultiPolygon, GlacierProperties>;
export type GlacierCollection = FeatureCollection<Polygon | MultiPolygon, GlacierProperties> & {
  metadata: {
    feature_count: number;
    minimum_area_km2: number;
    note: string;
    counts: Record<GlacierConnection | "external_contributors", number>;
  };
};
export const glacierColors = { external_contributor: "#ffc857", pakistan_contributor: "#4de7ff", divide_uncertain: "#f090ac", other_basin: "#d5e3ec" };
export const glacierConnectionLabels: Record<GlacierConnection, string> = {
  pakistan_contributor: "Potential Pakistan river contributor",
  divide_uncertain: "Drainage divide: uncertain",
  other_basin: "Outside mapped Indus drainage",
};
export function glacierFilter(view: GlacierView): FilterSpecification | null {
  if (view === "contributors") return ["==", ["get", "connection"], "pakistan_contributor"];
  if (view === "external") return ["==", ["get", "highlight"], "external_contributor"];
  return null;
}
