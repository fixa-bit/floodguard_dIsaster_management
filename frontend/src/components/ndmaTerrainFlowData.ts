export type TerrainFlowFrame = {
  seconds: number; inflow_m3s: number; volume_m3: number; additional_wet_area_km2: number;
  wet_area_km2: number; max_depth_m: number; max_speed_ms: number;
};
export type TerrainFlowData = {
  version: number; sample: string; bounds: [number, number, number, number]; rows: number; cols: number;
  dx_m: number; dy_m: number; duration_seconds: number; interval_seconds: number;
  depth_unit_m: number; velocity_unit_ms: number; wet_threshold_m: number;
  solver: string; boundaries: string; study: string; hydraulic_cells: number; grid_crs: string;
  depth_color_max_m: number; source_terrain_resolution_m: number; map_resolution_m: number; terrain_nodata: number;
  focus_bounds: [number, number, number, number];
  boundary_lines: { kind: string; label: string; coordinates: [number,number][] }[];
  hydrograph_seconds_m3s: number[][];
  frames: TerrainFlowFrame[]; elevation_m: number[]; slope_degrees: number[];
  native_result_sha256: string; source_manifest_url: string;
  initialization: {baseflow_duration_hours:number; baseflow_cfs:number; final_hour_relative_volume_drift:number};
  numerical_checks: { solver_completed: boolean; nonnegative_depth_passed: boolean; source_verified: boolean; initial_wet_cells: number };
  method_url: string; credit: string; limitations: string[];
};
export const terrainFlowBase = `${import.meta.env.BASE_URL}river-channel-flow/`;
export function validateTerrainFlow(data: TerrainFlowData, buffer: ArrayBuffer) {
  const count = data.rows * data.cols;
  if (data.version !== 2 || !Number.isInteger(data.rows) || !Number.isInteger(data.cols) || count < 4 || count > 1000000 ||
      !data.frames?.length || !data.numerical_checks?.solver_completed || !data.numerical_checks?.source_verified || !data.numerical_checks?.nonnegative_depth_passed ||
      !data.numerical_checks.initial_wet_cells || !data.native_result_sha256 || !data.boundary_lines?.some(b=>b.kind==="upstream") ||
      ![data.dx_m, data.dy_m, data.depth_unit_m, data.velocity_unit_ms].every(v => Number.isFinite(v) && v > 0) ||
      data.bounds?.length !== 4 || !data.bounds.every(Number.isFinite) || data.bounds[0] >= data.bounds[2] || data.bounds[1] >= data.bounds[3] ||
      data.elevation_m?.length !== count || data.slope_degrees?.length !== count ||
      !data.elevation_m.every(Number.isFinite) || !data.slope_degrees.every(Number.isFinite) ||
      buffer.byteLength !== data.frames.length * count * 3 * 2 ||
      data.frames.some((f, i) => ![f.seconds, f.wet_area_km2, f.max_depth_m, f.max_speed_ms].every(Number.isFinite) ||
        (i > 0 && f.seconds <= data.frames[i-1].seconds))) throw new Error("HEC-RAS river assets are incomplete or incompatible");
}
export function flowFrame(data: TerrainFlowData, buffer: ArrayBuffer, index: number) {
  const count = data.rows*data.cols, offset = index*count*3*2;
  return { depth: new Int16Array(buffer, offset, count), vx: new Int16Array(buffer, offset+count*2, count), vy: new Int16Array(buffer, offset+count*4, count) };
}
