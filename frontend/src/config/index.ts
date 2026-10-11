export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ??
  "http://127.0.0.1:8000/api/v1";

export const REFRESH_INTERVAL_MS = Number(
  import.meta.env.VITE_REFRESH_INTERVAL_MS ?? 30_000,
);

export const MAP_STYLE_URL = import.meta.env.VITE_MAP_STYLE_URL ?? "";

export const LOCATIONS = [
  { id: "JHG_001", name: "Jhang", region: "Punjab", river: "Chenab", latitude: 31.2681, longitude: 72.3187 },
  { id: "RWP_001", name: "Rawalpindi", region: "Punjab", river: "Soan", latitude: 33.5651, longitude: 73.0169 },
  { id: "MUL_001", name: "Multan", region: "Punjab", river: "Chenab", latitude: 30.1575, longitude: 71.5249 },
  { id: "ISB_001", name: "Islamabad", region: "Islamabad Capital Territory", river: "Korang", latitude: 33.6844, longitude: 73.0479 },
] as const;

export const SCENARIOS = [
  "NORMAL",
  "HEAVY_RAIN",
  "DEVELOPING_FLOOD",
  "CRITICAL_FLOOD",
  "CONFIRMED_FLOOD",
  "FALSE_ALARM",
] as const;

export type LocationId = (typeof LOCATIONS)[number]["id"];
export type Scenario = (typeof SCENARIOS)[number];
