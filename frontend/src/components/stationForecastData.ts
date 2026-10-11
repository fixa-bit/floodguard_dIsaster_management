import type { HydroSeriesPoint, RiverMonitoringStation } from "../types/api";
import type { StationHistory } from "./stationInfo";

export function chartTime(value: string) {
  const normalized = /^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T00:00:00Z`
    : /(?:z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`;
  return Date.parse(normalized);
}

export interface DischargeSeries {
  id: string; label: string; source: string; color: string; points: HydroSeriesPoint[]; modeled: boolean;
}
const valid = (point: HydroSeriesPoint) => typeof point.value === "number" && Number.isFinite(point.value) && point.value >= 0;
export function stationForecastSeries(station: RiverMonitoringStation, history?: StationHistory): DischargeSeries[] {
  const observed = new Map<number, HydroSeriesPoint>();
  for (const sample of history?.samples ?? []) {
    const point = { ...sample, phase: "past" };
    if (valid(point) && Number.isFinite(chartTime(point.time))) observed.set(chartTime(point.time), point);
  }
  const current = { time: station.observed_at ?? "", value: station.current_discharge_cumecs, phase: "past" };
  if (station.current_source.startsWith("FFD") && valid(current) && Number.isFinite(chartTime(current.time))) observed.set(chartTime(current.time), current);
  const result: DischargeSeries[] = [{ id: "observed", label: "Observed discharge", source: history?.source ?? "FFD observed", color: "#6baeff",
    points: [...observed.values()].sort((a, b) => chartTime(a.time) - chartTime(b.time)), modeled: false }];
  for (const [index, provider] of station.providers.entries()) {
    const points = [...provider.series].filter((point) => Number.isFinite(chartTime(point.time)))
      .map((point) => ({ ...point, value: valid(point) ? point.value : null })).sort((a, b) => chartTime(a.time) - chartTime(b.time));
    const past = points.filter((point) => point.phase === "past");
    const lastPast = past.at(-1);
    const future = points.filter((point) => point.phase === "forecast");
    const firstFuture = future[0];
    const historyStart = lastPast ? chartTime(lastPast.time) - 6 * 86400000 : Infinity;
    result.push({ id: `${provider.provider}-past`, label: `${provider.provider} modeled history`, source: provider.source, color: "#a6c9c6",
      points: past.filter((point) => chartTime(point.time) >= historyStart), modeled: true });
    result.push({ id: `${provider.provider}-forecast`, label: `${provider.provider} forecast`, source: provider.source, color: ["#ff7686", "#ffc857"][index % 2],
      points: future.filter((point) => firstFuture && chartTime(point.time) < chartTime(firstFuture.time) + 5 * 86400000), modeled: true });
  }
  return result.filter((item) => item.points.some(valid));
}

export function nearestDischargePoint(series: DischargeSeries, time: number) {
  const points = series.points.filter(valid);
  const point = points.reduce<HydroSeriesPoint | undefined>((best, point) => !best || Math.abs(chartTime(point.time) - time) < Math.abs(chartTime(best.time) - time) ? point : best, undefined);
  const intervals = points.slice(1).map((point, index) => chartTime(point.time) - chartTime(points[index].time)).filter((gap) => gap > 0);
  const tolerance = series.modeled ? 12 * 3600000 : Math.min(3 * 3600000, intervals.length ? Math.min(...intervals) / 2 : 30 * 60000);
  return point && Math.abs(chartTime(point.time) - time) <= tolerance ? point : undefined;
}
