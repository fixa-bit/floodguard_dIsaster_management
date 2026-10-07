import { useCallback, useEffect, useRef, useState } from "react";

import { LOCATIONS, REFRESH_INTERVAL_MS } from "../config";
import { ApiError, api } from "../services/api";
import type {
  CitizenReport,
  DashboardSummary,
  Incident,
  ModelForecastPoint,
  NationalRiskCollection,
  ResourceGroups,
  RiskResponse,
  RiverResponse,
  SimulationStatus,
  SystemEvent,
  SystemStatus,
  WaterIntelligenceCollection,
  WeatherResponse,
} from "../types/api";

export interface DashboardData {
  summary: DashboardSummary | null;
  risk: RiskResponse | null;
  modelForecasts: ModelForecastPoint[];
  weather: WeatherResponse | null;
  river: RiverResponse | null;
  locationWeather: WeatherResponse[];
  locationRivers: RiverResponse[];
  incidents: Incident[];
  reports: CitizenReport[];
  events: SystemEvent[];
  system: SystemStatus | null;
  simulation: SimulationStatus | null;
  nationalRisk: NationalRiskCollection | null;
  waterIntelligence: WaterIntelligenceCollection | null;
  resources: ResourceGroups;
}

const initialData: DashboardData = {
  summary: null,
  risk: null,
  modelForecasts: [],
  weather: null,
  river: null,
  locationWeather: [],
  locationRivers: [],
  incidents: [],
  reports: [],
  events: [],
  system: null,
  simulation: null,
  nationalRisk: null,
  waterIntelligence: null,
  resources: { shelters: [], hospitals: [], contacts: [] },
};

const NORMAL_RIVER_REFRESH_MS = 15 * 60 * 1000;
const FLOOD_RIVER_REFRESH_MS = 3 * 60 * 1000;
const FLOOD_LIKE_RIVER_STATUSES = new Set(["RISING", "WARNING", "DANGER", "FLOOD", "CRITICAL", "ALERT"]);

function errorMessage(reason: unknown): string {
  if (reason instanceof ApiError) {
    return reason.status === 0 ? reason.message : `${reason.code}: ${reason.message}`;
  }
  return "Unexpected dashboard request failure";
}

export function useDashboardData(locationId: string) {
  const [data, setData] = useState<DashboardData>(initialData);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [autoRefreshMs, setAutoRefreshMs] = useState(NORMAL_RIVER_REFRESH_MS);
  const requestId = useRef(0);

  const refresh = useCallback(async (initial = false) => {
    const currentRequest = ++requestId.current;
    if (initial) setLoading(true);
    else setRefreshing(true);

    const [requests, locationWeatherRequests, locationRiverRequests] = await Promise.all([
      Promise.allSettled([
        api.dashboard(),
        api.risk(locationId),
        api.modelForecasts(),
        api.weather(locationId),
        api.river(locationId),
        api.incidents(),
        api.citizenReports(),
        api.events(),
        api.systemStatus(),
        api.simulationStatus(),
        api.shelters(),
        api.hospitals(),
        api.contacts(),
        api.nationalRisk(),
        api.waterIntelligence(),
      ] as const),
      Promise.allSettled(LOCATIONS.map((location) => api.weather(location.id))),
      Promise.allSettled(LOCATIONS.map((location) => api.river(location.id))),
    ]);

    if (currentRequest !== requestId.current) return;

    const failures = [...requests, ...locationWeatherRequests, ...locationRiverRequests]
      .filter((result): result is PromiseRejectedResult => result.status === "rejected")
      .map((result) => errorMessage(result.reason));
    const locationWeather = locationWeatherRequests
      .filter((result): result is PromiseFulfilledResult<WeatherResponse> => result.status === "fulfilled")
      .map((result) => result.value);
    const locationRivers = locationRiverRequests
      .filter((result): result is PromiseFulfilledResult<RiverResponse> => result.status === "fulfilled")
      .map((result) => result.value);

    setData((previous) => ({
      summary: requests[0].status === "fulfilled" ? requests[0].value : previous.summary,
      risk: requests[1].status === "fulfilled" ? requests[1].value : previous.risk,
      modelForecasts: requests[2].status === "fulfilled" ? requests[2].value : previous.modelForecasts,
      weather: requests[3].status === "fulfilled" ? requests[3].value : previous.weather,
      river: requests[4].status === "fulfilled" ? requests[4].value : previous.river,
      locationWeather: locationWeather.length > 0 ? locationWeather : previous.locationWeather.length > 0 ? previous.locationWeather : requests[3].status === "fulfilled" ? [requests[3].value] : previous.locationWeather,
      locationRivers: locationRivers.length > 0 ? locationRivers : previous.locationRivers,
      incidents: requests[5].status === "fulfilled" ? requests[5].value : previous.incidents,
      reports: requests[6].status === "fulfilled" ? requests[6].value : previous.reports,
      events: requests[7].status === "fulfilled" ? requests[7].value : previous.events,
      system: requests[8].status === "fulfilled" ? requests[8].value : previous.system,
      simulation: requests[9].status === "fulfilled" ? requests[9].value : previous.simulation,
      nationalRisk: requests[13].status === "fulfilled" ? requests[13].value : previous.nationalRisk,
      waterIntelligence: requests[14].status === "fulfilled" ? requests[14].value : previous.waterIntelligence,
      resources: {
        shelters: requests[10].status === "fulfilled" ? requests[10].value : previous.resources.shelters,
        hospitals: requests[11].status === "fulfilled" ? requests[11].value : previous.resources.hospitals,
        contacts: requests[12].status === "fulfilled" ? requests[12].value : previous.resources.contacts,
      },
    }));
    setErrors([...new Set(failures)]);
    setLastUpdated(new Date());
    setLoading(false);
    setRefreshing(false);
  }, [locationId]);

  useEffect(() => {
    void refresh(true);
  }, [refresh]);

  useEffect(() => {
    const riverRefreshMs = data.locationRivers.some((river) => FLOOD_LIKE_RIVER_STATUSES.has(river.status.toUpperCase()))
      ? FLOOD_RIVER_REFRESH_MS
      : NORMAL_RIVER_REFRESH_MS;
    setAutoRefreshMs(riverRefreshMs);
    const timer = window.setInterval(() => void refresh(false), riverRefreshMs || REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [data.locationRivers, refresh]);

  return { data, loading, refreshing, errors, lastUpdated, autoRefreshMs, refresh };
}
