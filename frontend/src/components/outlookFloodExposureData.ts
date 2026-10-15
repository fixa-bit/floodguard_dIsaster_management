import type { FeatureCollection, Geometry } from "geojson";
import type { PreviewAreaId } from "./tenYearPreviewData";

export type ExposureLevel = {
  level: number;
  example_buffer_m: number;
  flood_area_km2: number | null;
  exposed_population: number | null;
  known_raster_area_fraction: number | null;
};
export type FloodExposurePreview = {
  id: PreviewAreaId;
  name: string;
  bounds: [number, number, number, number];
  supported: boolean;
  rivers: string[];
  known_population_2025: number;
  valid_native_pixels: number;
  levels: ExposureLevel[];
  population: FeatureCollection<Geometry, { id: number; population_2025: number; density_km2: number; exposed_by_level: number[] }>;
  water: FeatureCollection;
  river_lines: FeatureCollection;
};

// URLs only: Vite compresses these assets; the selected district loads on demand.
const files = import.meta.glob<string>("../data/outlook-exposure/*.geojson", { eager: true, query: "?compressed", import: "default" });
export function exposureAssetUrl(id: PreviewAreaId) { return files[`../data/outlook-exposure/${id}.geojson`]; }

export function approximatePeople(value: number | null) {
  if (value === null) return "Unavailable";
  if (value === 0) return "0";
  if (value < 100) return "<100";
  return `~${(Math.round(value / 100) * 100).toLocaleString("en-US")}`;
}
