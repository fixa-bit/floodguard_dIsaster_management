import type { ExperimentalHydrograph } from "../types/api";

export const CUSECS_PER_CUMEC = 35.3147;
export const validFlow = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value >= 0;
export const pointTime = (t: string) => Date.parse(t);
export const pktTime = (t: string | number) => Number.isFinite(typeof t === "number" ? t : pointTime(t))
  ? `${new Intl.DateTimeFormat("en-PK", { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit", timeZone: "Asia/Karachi" }).format(new Date(t))} PKT` : "Unavailable";
export function chartData(data: ExperimentalHydrograph, align: boolean) {
  const observed = data.observed.filter((p) => validFlow(p.v) && Number.isFinite(pointTime(p.t))).sort((a, b) => pointTime(a.t) - pointTime(b.t));
  const raw = data.forecast.filter((p) => validFlow(p.v) && Number.isFinite(pointTime(p.t))).sort((a, b) => pointTime(a.t) - pointTime(b.t));
  const last = observed.at(-1);
  // Daily model points are never relabeled as observed; an optional shift is explicit.
  const forecast = last ? raw.filter((p) => pointTime(p.t) > pointTime(last.t)) : raw;
  const offset = align && last && forecast[0] ? last.v - forecast[0].v : 0;
  const shift = (value: number | null | undefined) => validFlow(value) && value + offset >= 0 ? value + offset : null;
  return { observed, forecast: forecast.map((p) => ({ ...p, v: shift(p.v), p25: shift(p.p25), p75: shift(p.p75) })), offset };
}

export function hydrographCsv(data: ExperimentalHydrograph, align = false) {
  const series = chartData(data, align);
  const quote = (value: unknown) => `"${String(value ?? "").replaceAll('"', '""')}"`;
  const rows = [["Station", "Time (UTC)", "Series", "Discharge (cusecs)", "p25 (cusecs)", "p75 (cusecs)", "Source", "Alignment offset (cusecs)"],
    ...series.observed.map((p) => [data.station.station_id, p.t, "Observed inflow", p.v, "", "", p.source ?? data.sources.observed.join("; "), ""]),
    ...series.forecast.map((p) => [data.station.station_id, p.t, align ? "Forecast (shifted, experimental)" : "Forecast (experimental)", p.v, p.p25, p.p75, data.sources.forecast, series.offset]),
    ...Object.entries(data.thresholds).filter(([, value]) => validFlow(value)).map(([name, value]) => [data.station.station_id, "", `${name} threshold`, value, "", "", "Station configuration", ""]),
    ...(validFlow(data.highestRecorded.value) ? [[data.station.station_id, data.highestRecorded.date ?? "", "Highest recorded flow", data.highestRecorded.value, "", "", "Station configuration", ""]] : [])];
  return rows.map((row) => row.map(quote).join(",")).join("\r\n");
}
