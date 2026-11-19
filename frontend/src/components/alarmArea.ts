import { useEffect, useState } from "react";

import { LOCATIONS } from "../config";
import { api } from "../services/api";

/**
 * The Alerts & Alarms page filtered to the top bar's operational area: an alert or alarm is in
 * the area when its station (or place) lies within `AREA_RADIUS_KM` of the area's centre.
 * `null` is the whole of Pakistan (everything is shown).
 */
export type AlarmArea = { name: string; latitude: number; longitude: number } | null;
export const AREA_RADIUS_KM = 150;

type Point = { latitude: number; longitude: number };

/** Alarm targets that are places rather than river stations. */
const PLACES: Record<string, Point> = {
  LAHORE_GRID: { latitude: 31.5204, longitude: 74.3587 },
};

function distanceKm(a: Point, b: Point) {
  const r = Math.PI / 180, dLat = (b.latitude - a.latitude) * r, dLng = (b.longitude - a.longitude) * r;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.latitude * r) * Math.cos(b.latitude * r) * Math.sin(dLng / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(h));
}

/** River station positions (by id, upper case), loaded once for the page. */
export function useStationPoints() {
  const [points, setPoints] = useState<Map<string, Point> | null>(null);
  useEffect(() => {
    let live = true;
    api.riverMonitoring()
      .then((result) => { if (live) setPoints(new Map(result.stations.map((station) => [station.id.toUpperCase(), { latitude: station.latitude, longitude: station.longitude }]))); })
      .catch(() => { if (live) setPoints(new Map()); });
    return () => { live = false; };
  }, []);
  return points;
}

/** Where an id (station, place or operational location) is, if known. */
export function pointOf(id: unknown, stations: Map<string, Point> | null): Point | undefined {
  if (typeof id !== "string" || !id) return undefined;
  const key = id.toUpperCase();
  return stations?.get(key) ?? PLACES[key] ?? LOCATIONS.find((location) => location.id === key);
}

/**
 * Whether something at `point` belongs to the area. National items (e.g. the seasonal Indus
 * basin alarm) belong to every area; items with no known place show only for the whole country.
 */
export function inArea(area: AlarmArea, point: Point | undefined, national = false) {
  if (!area || national) return true;
  return point ? distanceKm(area, point) <= AREA_RADIUS_KM : false;
}
