import type { RiverMonitoringStation } from "../types/api";

export type WaterQuantity = "status" | "current" | "forecast" | "peak";
export type FlowUnit = "cumecs" | "cusecs";
export const CUSECS_PER_CUMEC = 35.3146667215;
export const waterQuantityOptions: Array<{ id: WaterQuantity; label: string }> = [
  { id: "status", label: "Flood category" },
  { id: "current", label: "Current discharge" },
  { id: "forecast", label: "Forecast discharge" },
  { id: "peak", label: "Expected peak" },
];
export const flowBands = [
  { minimum: 0, color: "#38bdf8" },
  { minimum: 1000, color: "#34d399" },
  { minimum: 5000, color: "#facc15" },
  { minimum: 10000, color: "#f97316" },
  { minimum: 20000, color: "#f43f5e" },
];

export function stationQuantity(station: RiverMonitoringStation | undefined, quantity: WaterQuantity) {
  const value = quantity === "current" ? station?.current_discharge_cumecs
    : quantity === "forecast" ? station?.forecast_discharge_cumecs
    : quantity === "peak" ? station?.expected_peak_cumecs : null;
  return value != null && Number.isFinite(value) && value >= 0 ? value : null;
}

export function flowInUnit(value: number, unit: FlowUnit) {
  return unit === "cusecs" ? value * CUSECS_PER_CUMEC : value;
}

export function formatFlow(value: number | null | undefined, unit: FlowUnit = "cumecs") {
  if (value == null || !Number.isFinite(value)) return "Unavailable";
  const converted = flowInUnit(value, unit);
  return `${converted.toLocaleString("en", { maximumFractionDigits: Math.abs(converted) < 1 ? 3 : 1 })} ${unit === "cusecs" ? "cusecs" : "m3/s"}`;
}

export function flowColor(value: number | null) {
  if (value == null) return "#94a3b8";
  return [...flowBands].reverse().find((band) => value >= band.minimum)?.color ?? flowBands[0].color;
}
