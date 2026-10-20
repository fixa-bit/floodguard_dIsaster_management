import type { FeatureCollection } from "geojson";

export type PilotLevel = {
  level: number; assumed_rise_m: number; flood_area_km2: number;
  exposed_population: number; known_raster_area_fraction: number | null; touches_study_edge: boolean;
};
export type JhangTerrainPilot = {
  schema_version: number; id: string; name: string; bounds: [number, number, number, number];
  cell_size_m: number; study_area_km2: number; baseline_connected_area_km2: number;
  known_population_2025: number; population_coverage_fraction: number;
  continuous_metrics: PilotMetric[];
  levels: PilotLevel[]; water: FeatureCollection; waterways: FeatureCollection;
  stream_corridor: FeatureCollection;
  connection_paths: FeatureCollection; study_boundary: FeatureCollection; reference_extent: FeatureCollection;
};
export type PilotMetadata = {
  population_image_bounds: [number, number, number, number];
  dem_credit: string; dem_liability_notice: string; dem_license_url: string;
  grid: { width: number; height: number; cell_m: number; nodata_cells_inside: number };
  sources: { osm: { timestamp_osm_base: string } };
};

export type PilotMetric = {
  rise_m: number; flood_area_km2: number; exposed_population: number;
  known_raster_area_fraction: number | null; touches_study_edge: boolean;
};

export const pilotAssetBase = `${import.meta.env.BASE_URL}jhang-terrain-prototype/`;

export function validateJhangPilot(data: JhangTerrainPilot): JhangTerrainPilot {
  if (data.schema_version !== 1 || data.id !== "jhang-chenab-pilot" || data.levels?.length !== 6 || data.continuous_metrics?.length !== 61
    || ![data.water, data.waterways, data.stream_corridor, data.connection_paths, data.study_boundary, data.reference_extent].every(item => item?.type === "FeatureCollection")
    || data.bounds?.length !== 4 || !data.bounds.every(Number.isFinite)) throw new Error("Invalid pilot data");
  const monotonicFields = ["assumed_rise_m", "exposed_population", "flood_area_km2"] as const;
  data.levels.forEach((entry, index) => {
    if (entry.level !== index || ![entry.assumed_rise_m, entry.exposed_population, entry.flood_area_km2].every(value => Number.isFinite(value) && value >= 0)
      || (index > 0 && monotonicFields.some(key => entry[key] < data.levels[index - 1][key]))) throw new Error("Invalid pilot levels");
  });
  data.continuous_metrics.forEach((entry, index) => {
    if (Math.abs(entry.rise_m - index*.05) > 1e-8 || ![entry.flood_area_km2, entry.exposed_population].every(value => Number.isFinite(value) && value >= 0)
      || typeof entry.touches_study_edge !== "boolean"
      || (index > 0 && (entry.flood_area_km2 < data.continuous_metrics[index-1].flood_area_km2 || entry.exposed_population < data.continuous_metrics[index-1].exposed_population))) throw new Error("Invalid continuous pilot metrics");
  });
  if (data.levels[0].exposed_population !== 0 || data.levels[0].flood_area_km2 !== 0) throw new Error("Invalid pilot baseline");
  return data;
}

export function pilotMetricAt(data: JhangTerrainPilot, rise: number) {
  const value = Math.max(0, Math.min(3, rise));
  const lowerIndex = Math.min(data.continuous_metrics.length-1, Math.floor(value/.05));
  const lower = data.continuous_metrics[lowerIndex], upper = data.continuous_metrics[Math.min(lowerIndex+1, data.continuous_metrics.length-1)];
  const fraction = upper.rise_m === lower.rise_m ? 0 : (value-lower.rise_m)/(upper.rise_m-lower.rise_m);
  const area = lower.flood_area_km2+(upper.flood_area_km2-lower.flood_area_km2)*fraction;
  const population = lower.exposed_population+(upper.exposed_population-lower.exposed_population)*fraction;
  const lowerCoverage = lower.known_raster_area_fraction ?? upper.known_raster_area_fraction;
  const upperCoverage = upper.known_raster_area_fraction ?? lower.known_raster_area_fraction;
  return { level: value, assumed_rise_m: value, flood_area_km2: area, exposed_population: population,
    known_raster_area_fraction: area ? lowerCoverage == null || upperCoverage == null ? null : lowerCoverage+(upperCoverage-lowerCoverage)*fraction : null,
    touches_study_edge: lower.touches_study_edge };
}
