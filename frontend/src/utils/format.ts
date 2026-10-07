import { LOCATIONS } from "../config";

export function locationName(locationId: string | null) {
  if (!locationId) return "System";
  return LOCATIONS.find((location) => location.id === locationId)?.name ?? locationId;
}

export function parseApiDate(value: string) {
  const hasTimezone = /(?:z|[+-]\d{2}:?\d{2})$/i.test(value);
  return new Date(hasTimezone ? value : `${value}Z`);
}

export function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("en-PK", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parseApiDate(value));
}

export function formatRelativeTime(value: string) {
  const seconds = Math.round((parseApiDate(value).getTime() - Date.now()) / 1000);
  const formatter = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  if (Math.abs(seconds) < 60) return formatter.format(seconds, "second");
  const minutes = Math.round(seconds / 60);
  if (Math.abs(minutes) < 60) return formatter.format(minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) return formatter.format(hours, "hour");
  return formatter.format(Math.round(hours / 24), "day");
}
