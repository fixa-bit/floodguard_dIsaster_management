import type { Feature } from "geojson";
import type { RiverMonitoringStation } from "../types/api";

export type StationKind = "gauge" | "barrage" | "dam" | "reference";
export interface InfoRow { label: string; value: string; source?: string }
export interface StationCardData {
  id: string; stationId?: string; kind: StationKind; name: string; longitude: number; latitude: number;
  meta: InfoRow[]; readings: InfoRow[]; thresholds: InfoRow[]; trend: InfoRow[];
  status: "Normal" | "Rising" | "Flood-Danger" | "Unavailable"; source?: string; sourceUrl?: string;
  recordedAt?: string; intervalMinutes: number; dangerMessage?: string; trendDirection?: "up" | "down" | "steady";
  trendModeled?: boolean;
}
export interface StationHistory { station_id: string; source: string; samples: Array<{ time: string; value: number }> }
const numeric = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const text = (value: unknown) => typeof value === "string" && value.trim() && !["undefined", "null", "NaN"].includes(value) ? value : undefined;
const number = (value: unknown, unit: string) => numeric(value) ? `${value.toLocaleString("en-PK", { maximumFractionDigits: 2 })} ${unit}` : undefined;
const row = (label: string, value?: string): InfoRow[] => value ? [{ label, value }] : [];
export function stationWaterLevel(station?: RiverMonitoringStation, properties: Record<string, unknown> = {}) {
  if (numeric(station?.observed_level_value) && text(station?.observed_level_unit)) return {
    value: number(station.observed_level_value, station.observed_level_unit!)!,
    source: text(station.level_source) ?? "Source unavailable",
    recordedAt: text(station.level_observed_at),
  };
  if (numeric(properties.observed_level_m)) return {
    value: number(properties.observed_level_m, "m")!, source: text(properties.level_source) ?? "Source unavailable",
    recordedAt: text(properties.level_observed_at),
  };
  return { value: "Unavailable", source: "Not provided by current feeds", recordedAt: undefined };
}
export function pakistanTime(value?: string) {
  if (!value || !Number.isFinite(Date.parse(value))) return undefined;
  return `${new Intl.DateTimeFormat("en-PK", { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit", hour12: true, timeZone: "Asia/Karachi" }).format(new Date(value))} PKT`;
}
export function stationIsStale(card: StationCardData, now = Date.now()) {
  return card.kind !== "reference" && (!card.recordedAt || !Number.isFinite(Date.parse(card.recordedAt))
    || now - Date.parse(card.recordedAt) > card.intervalMinutes * 60000);
}

export function stationCardProperties(feature: Feature, station: RiverMonitoringStation | undefined, intervalMinutes: number,
  geography: { basin?: string; province?: string; district?: string } = {}) {
  const p = feature.properties ?? {};
  const coords = feature.geometry.type === "Point" ? feature.geometry.coordinates : [0, 0];
  const kind: StationKind = feature.geometry.type !== "Point" || p.category === "confluences" ? "reference"
    : p.category === "dams" || /dam|reservoir/.test(p.feature_kind ?? "") ? "dam"
    : p.category === "barrages" || /barrage|headwork/.test(p.feature_kind ?? "") ? "barrage" : "gauge";
  const observed = station?.current_source?.startsWith("FFD");
  const current = station?.current_discharge_cumecs ?? p.observed_discharge_cumecs;
  const observedAt = text(station?.observed_at) ?? text(p.observed_at);
  // Daily modeled hydrographs are not timestamped gauge observations.
  const recordedAt = observedAt;
  const level = stationWaterLevel(station, p);
  const dischargeSource = text(station?.current_source) ?? text(p.discharge_source) ?? "Source unavailable";
  const dischargeRows: InfoRow[] = [{ label: station && !observed ? "Modeled discharge" : "Current discharge",
    value: number(current, "cumecs") ?? "Unavailable", source: numeric(current) ? dischargeSource : "Not provided by current feeds" }];
  const levelRows: InfoRow[] = [{ label: "Water level", value: level.value, source: level.source },
    ...row("Level recorded at", level.recordedAt !== recordedAt ? pakistanTime(level.recordedAt) : undefined)];
  const change = station?.change_24h_cumecs;
  const category = station?.flood_category ?? p.flood_category;
  const status: StationCardData["status"] = /flood/i.test(category ?? "") ? "Flood-Danger"
    : category === "Below low" || category === "NORMAL" ? numeric(change) && change > 0 && station?.change_source?.startsWith("FFD") ? "Rising" : "Normal"
    : category === "RISING" ? "Rising" : "Unavailable";
  const danger = numeric(p.danger_discharge_cumecs) ? p.danger_discharge_cumecs : undefined;
  const dangerMessage = numeric(current) && danger !== undefined ? current === danger ? "At danger level" : `${number(Math.abs(current - danger), "cumecs")} ${current > danger ? "above" : "below"} danger level`
    : numeric(p.observed_level_m) && numeric(p.danger_level_m) ? p.observed_level_m === p.danger_level_m ? "At danger level" : `${number(Math.abs(p.observed_level_m - p.danger_level_m) * 100, "cm")} ${p.observed_level_m > p.danger_level_m ? "above" : "below"} danger level` : undefined;
  const data: StationCardData = {
    id: String(feature.id ?? p.id ?? p.name), stationId: text(p.stationId) ?? text(p.monitoring_station_id), kind,
    name: text(p.name) ?? station?.name ?? "Monitoring point", longitude: coords[0], latitude: coords[1],
    meta: [...row("River", text(p.river) ?? text(p.water_system) ?? station?.river), ...row("Station ID", text(p.stationId) ?? text(p.monitoring_station_id)),
      ...row("Basin / Catchment", geography.basin ?? station?.basin), ...row("Province", geography.province ?? text(p.province)), ...row("District", geography.district ?? text(p.district))],
    readings: kind === "reference" ? [] : kind === "dam" ? [
      ...row("Storage level", number(p.storage_level_m ?? p.observed_level_m, "m")), ...row("Inflow", number(p.inflow_cumecs, "cumecs")),
      ...row("Outflow", number(p.outflow_cumecs, "cumecs")), ...row("Full", number(p.percent_full, "%")),
      ...dischargeRows, ...levelRows, ...row("Recorded at", pakistanTime(recordedAt)),
    ] : [...dischargeRows, ...levelRows, ...row("Recorded at", pakistanTime(recordedAt))],
    thresholds: kind === "reference" ? [] : [...row("Warning", number(p.warning_discharge_cumecs, "cumecs") ?? number(p.warning_level_m, "m")),
      ...row("Danger", number(p.danger_discharge_cumecs, "cumecs") ?? number(p.danger_level_m, "m")),
      ...row("Highest recorded flood", number(p.highest_recorded_discharge_cumecs, "cumecs") ?? number(p.highest_recorded_level_m, "m")), ...row("Flood record date", pakistanTime(text(p.highest_recorded_at)))],
    trend: kind === "reference" ? [] : [...row("3h change", number(p.change_3h_cumecs, "cumecs")),
      ...row(station?.change_source?.startsWith("GloFAS") ? "24h change (modeled)" : "24h change", number(change, "cumecs"))],
    trendDirection: numeric(change) ? change > 0 ? "up" : change < 0 ? "down" : "steady" : undefined,
    trendModeled: station?.change_source?.startsWith("GloFAS"),
    status: kind === "reference" ? "Unavailable" : status, recordedAt, intervalMinutes: numeric(intervalMinutes) && intervalMinutes > 0 ? intervalMinutes : 60,
    source: kind === "reference" ? undefined : text(station?.current_source) ?? text(p.telemetry_status),
    sourceUrl: text(p.source)?.startsWith("https://") ? p.source : undefined, dangerMessage,
  };
  return { ...feature, properties: { ...p, station_card: JSON.stringify(data) } };
}
export function readStationCard(properties: Record<string, unknown>, coordinates?: number[]): StationCardData | null {
  try {
    const data = JSON.parse(String(properties.station_card)) as StationCardData;
    if (!data.id || !data.name || !numeric(data.longitude) || !numeric(data.latitude)) return null;
    return coordinates ? { ...data, longitude: coordinates[0], latitude: coordinates[1] } : data;
  } catch { return null; }
}
export function sparklinePath(samples: StationHistory["samples"]) {
  const points = samples.filter((point) => numeric(point.value) && Number.isFinite(Date.parse(point.time)));
  if (points.length < 2) return undefined;
  const min = Math.min(...points.map((point) => point.value)); const max = Math.max(...points.map((point) => point.value));
  const start = Date.parse(points[0].time); const duration = Date.parse(points.at(-1)!.time) - start;
  if (duration <= 0) return undefined;
  return points.map((point, index) => `${index ? "L" : "M"}${(4 + (Date.parse(point.time) - start) / duration * 292).toFixed(2)},${(max === min ? 26 : 46 - (point.value - min) / (max - min) * 40).toFixed(2)}`).join(" ");
}

export function withStationHistory(card: StationCardData, history?: StationHistory): StationCardData {
  if (!history || !card.recordedAt || !card.source?.startsWith("FFD")) return card;
  const current = history.samples.find((sample) => Date.parse(sample.time) === Date.parse(card.recordedAt!));
  if (!current || !numeric(current.value)) return card;
  const trend = [...card.trend];
  let change: number | undefined;
  for (const hours of [3, 24]) {
    const previous = history.samples.find((sample) => Date.parse(sample.time) === Date.parse(current.time) - hours * 3600000);
    if (!previous || !numeric(previous.value)) continue;
    const value = current.value - previous.value;
    for (let index = trend.length - 1; index >= 0; index--) if (trend[index].label.startsWith(`${hours}h change`)) trend.splice(index, 1);
    trend.push({ label: `${hours}h change`, value: number(value, "cumecs")! });
    change ??= value;
  }
  return change === undefined ? card : { ...card, trend, trendDirection: change > 0 ? "up" : change < 0 ? "down" : "steady", trendModeled: false };
}
