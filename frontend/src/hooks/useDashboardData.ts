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
  MonitoringSimulationResult,
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
  alerts: SystemEvent[];
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
  alerts: [],
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

function settledValue<T>(result: PromiseSettledResult<T | undefined>, previous: T): T {
  return result.status === "fulfilled" && result.value !== undefined ? result.value : previous;
}

export function useDashboardData(locationId: string, includeLiveData = true) {
  const [data, setData] = useState<DashboardData>(initialData);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [autoRefreshMs, setAutoRefreshMs] = useState(NORMAL_RIVER_REFRESH_MS);
  const requestId = useRef(0);
  const operationsVersion = useRef(0);

  const refresh = useCallback(async (initial = false) => {
    const currentRequest = ++requestId.current;
    const currentOperationsVersion = operationsVersion.current;
    if (initial) setLoading(true);
    else setRefreshing(true);
    setErrors([]);

    // Share the selected location's requests with the national overview instead
    // of asking the same providers twice during every refresh.
    const weatherRequests = includeLiveData ? LOCATIONS.map((location) => api.weather(location.id)) : [];
    const riverRequests = includeLiveData ? LOCATIONS.map((location) => api.river(location.id)) : [];
    const locationIndex = LOCATIONS.findIndex((location) => location.id === locationId);
    const selectedWeather = includeLiveData ? weatherRequests[locationIndex] ?? api.weather(locationId) : Promise.resolve(undefined);
    const selectedRiver = includeLiveData ? riverRequests[locationIndex] ?? api.river(locationId) : Promise.resolve(undefined);

    const [requests, locationWeatherRequests, locationRiverRequests] = await Promise.all([
      Promise.allSettled([
        api.dashboard(),
        includeLiveData ? api.risk(locationId) : Promise.resolve(undefined),
        includeLiveData ? api.modelForecasts() : Promise.resolve(undefined),
        selectedWeather,
        selectedRiver,
        api.incidents(),
        api.citizenReports(),
        api.events(),
        api.systemStatus(),
        api.simulationStatus(),
        api.shelters(),
        api.hospitals(),
        api.contacts(),
        includeLiveData ? api.nationalRisk() : Promise.resolve(undefined),
        includeLiveData ? api.waterIntelligence() : Promise.resolve(undefined),
        api.alerts(),
      ] as const),
      Promise.allSettled(weatherRequests),
      Promise.allSettled(riverRequests),
    ]);

    if (currentRequest !== requestId.current) return;

    const requestLabels = ["Dashboard summary", "Flood risk", "Model forecasts", `Weather (${locationId})`, `River (${locationId})`, "Incidents", "Citizen reports", "System events", "System status", "Simulation status", "Shelters", "Hospitals", "Emergency contacts", "National risk map", "Water intelligence", "Alerts"];
    const failures = requests.flatMap((result, index) => result.status === "rejected" ? [`${requestLabels[index]}: ${errorMessage(result.reason)}`] : []);
    locationWeatherRequests.forEach((result, index) => {
      if (index !== locationIndex && result.status === "rejected") failures.push(`Weather (${LOCATIONS[index].name}): ${errorMessage(result.reason)}`);
    });
    locationRiverRequests.forEach((result, index) => {
      if (index !== locationIndex && result.status === "rejected") failures.push(`River (${LOCATIONS[index].name}): ${errorMessage(result.reason)}`);
    });
    const locationWeather = locationWeatherRequests
      .filter((result): result is PromiseFulfilledResult<WeatherResponse> => result.status === "fulfilled")
      .map((result) => result.value);
    const locationRivers = locationRiverRequests
      .filter((result): result is PromiseFulfilledResult<RiverResponse> => result.status === "fulfilled")
      .map((result) => result.value);

    setData((previous) => ({
      summary: currentOperationsVersion === operationsVersion.current && requests[0].status === "fulfilled" ? requests[0].value : previous.summary,
      risk: settledValue(requests[1], previous.risk),
      modelForecasts: settledValue(requests[2], previous.modelForecasts),
      weather: settledValue(requests[3], previous.weather),
      river: settledValue(requests[4], previous.river),
      locationWeather: locationWeather.length > 0 ? locationWeather : previous.locationWeather,
      locationRivers: locationRivers.length > 0 ? locationRivers : previous.locationRivers,
      incidents: currentOperationsVersion === operationsVersion.current && requests[5].status === "fulfilled" ? requests[5].value : previous.incidents,
      reports: requests[6].status === "fulfilled" ? requests[6].value : previous.reports,
      events: currentOperationsVersion === operationsVersion.current && requests[7].status === "fulfilled" ? requests[7].value : previous.events,
      alerts: currentOperationsVersion === operationsVersion.current && requests[15].status === "fulfilled" ? requests[15].value : previous.alerts,
      system: requests[8].status === "fulfilled" ? requests[8].value : previous.system,
      simulation: requests[9].status === "fulfilled" ? requests[9].value : previous.simulation,
      nationalRisk: settledValue(requests[13], previous.nationalRisk),
      waterIntelligence: settledValue(requests[14], previous.waterIntelligence),
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
  }, [locationId, includeLiveData]);

  const refreshOperations = useCallback(async (simulation?: MonitoringSimulationResult) => {
    const version = ++operationsVersion.current;
    if (simulation) setData((previous) => ({
      ...previous,
      alerts: [...simulation.alerts, ...previous.alerts.filter((alert) => !simulation.alerts.some((added) => added.id === alert.id))],
      incidents: [...simulation.incidents, ...previous.incidents.filter((incident) => !simulation.incidents.some((added) => added.id === incident.id))],
    }));
    const [alerts, incidents, events, summary] = await Promise.allSettled([
      api.alerts(), api.incidents(), api.events(), api.dashboard(),
    ] as const);
    if (version !== operationsVersion.current) return;
    setData((previous) => ({
      ...previous,
      alerts: alerts.status === "fulfilled" ? alerts.value : previous.alerts,
      incidents: incidents.status === "fulfilled" ? incidents.value : previous.incidents,
      events: events.status === "fulfilled" ? events.value : previous.events,
      summary: summary.status === "fulfilled" ? summary.value : previous.summary,
    }));
  }, []);

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

  return { data, loading, refreshing, errors, lastUpdated, autoRefreshMs, refresh, refreshOperations };
}
