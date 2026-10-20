import type { MaralaMonthlyModelData } from "../types/api";

export const DAY_MS = 86_400_000;
export type HydrographMode = "daily" | "monthly";
export type DischargePoint = {
  key: string;
  date: string;
  time: number;
  value: number;
  kind: "history" | "forecast";
  resolution: HydrographMode;
  days?: number;
  calendarDays?: number;
};

export function dischargePoints(data: MaralaMonthlyModelData, mode: HydrographMode = "daily"): DischargePoint[] {
  const daily = data.recent_history?.station_observation ? data.recent_history.daily ?? [] : [];
  if (mode === "monthly") {
    const months = data.recent_history?.station_observation ? data.recent_history.monthly ?? [] : [];
    return [
      ...months.filter((row): row is typeof row & { flow_mean_cumecs: number } => row.flow_mean_cumecs !== null).map(row => ({ key: `history-${row.month}`, date: row.month, time: Date.parse(`${row.month}-15T12:00:00Z`), value: row.flow_mean_cumecs, kind: "history" as const, resolution: mode, days: row.days, calendarDays: row.calendar_days })),
      ...data.current_provider_outlook.forecast.map(row => ({ key: `forecast-${row.target_month}`, date: row.target_month, time: Date.parse(`${row.target_month}-15T12:00:00Z`), value: row.monthly_mean_discharge_cumecs.mean, kind: "forecast" as const, resolution: mode, days: row.days, calendarDays: row.days })),
    ].filter(point => Number.isFinite(point.value)).sort((a, b) => a.time - b.time);
  }
  const forecastStart = Date.parse(data.current_provider_outlook.forecast_issue_start);
  return [
    ...daily.map(row => ({ key: `history-${row.date}`, date: row.date, time: Date.parse(row.observed_at), value: row.inflow_cumecs, kind: "history" as const, resolution: mode })),
    // Daily means are positioned at midday UTC, not presented as 06:00 gauge predictions.
    ...(data.current_provider_outlook.daily_forecast ?? []).filter(row => Date.parse(row.date) >= forecastStart && row.date <= data.current_provider_outlook.forecast_available_through).map(row => ({ key: `forecast-${row.date}`, date: row.date, time: Date.parse(`${row.date}T12:00:00Z`), value: row.mean_cumecs, kind: "forecast" as const, resolution: mode })),
  ].filter(point => Number.isFinite(point.time) && Number.isFinite(point.value)).sort((a, b) => a.time - b.time);
}

function monthIndex(month: string) {
  const [year, number] = month.split("-").map(Number);
  return year * 12 + number - 1;
}

export function dischargeSegments(points: DischargePoint[], kind: DischargePoint["kind"]) {
  const groups: DischargePoint[][] = [];
  for (const point of points.filter(point => point.kind === kind)) {
    const group = groups.at(-1);
    const previous = group?.at(-1);
    const adjacent = previous && (point.resolution === "monthly"
      ? monthIndex(point.date) - monthIndex(previous.date) === 1
      : Date.parse(point.date) - Date.parse(previous.date) === DAY_MS);
    if (group && adjacent) group.push(point);
    else groups.push([point]);
  }
  return groups;
}
