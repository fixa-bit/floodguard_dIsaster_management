import { ExternalLink } from "lucide-react";
import type { RiverMonitoringStation } from "../types/api";

export function riverTimestamp(value: string | null | undefined) {
  if (!value) return "Time unavailable";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "Time unavailable";
  const daily = /^\d{4}-\d{2}-\d{2}$/.test(value);
  return new Intl.DateTimeFormat("en-PK", {
    month: "short", day: "numeric", ...(daily ? {} : { hour: "numeric", minute: "2-digit" } as const),
    timeZone: daily ? "UTC" : "Asia/Karachi",
  }).format(date) + (daily ? " (daily estimate)" : " PKT");
}

export function RiverDataSource({ source, station }: { source: string; station?: RiverMonitoringStation }) {
  const official = source.includes("FFD");
  const model = source.includes("GloFAS");
  const url = official ? "https://ffd.pmd.gov.pk/river-state?zoom=6"
    : model && station ? `https://flood-api.open-meteo.com/v1/flood?${new URLSearchParams({ latitude: String(station.latitude), longitude: String(station.longitude), daily: "river_discharge,river_discharge_p25,river_discharge_p75", past_days: "14", forecast_days: "14", cell_selection: "nearest" })}`
    : model ? "https://open-meteo.com/en/docs/flood-api" : null;
  return <small className="river-data-source">Source: {url ? <a href={url} target="_blank" rel="noreferrer">{source}<ExternalLink size={10} /></a> : source || "Unavailable"}</small>;
}
