import { useCallback, useEffect, useRef, useState } from "react";

import { REFRESH_INTERVAL_MS } from "../config";
import { ApiError, api } from "../services/api";
import type {
  CitizenReport,
  DashboardSummary,
  Incident,
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
  weather: WeatherResponse | null;
  river: RiverResponse | null;
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
  weather: null,
  river: null,
  incidents: [],
  reports: [],
  events: [],
  system: null,
  simulation: null,
  nationalRisk: null,
  waterIntelligence: null,
  resources: { shelters: [], hospitals: [], contacts: [] },
};

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
  const requestId = useRef(0);

  const refresh = useCallback(async (initial = false) => {
    const currentRequest = ++requestId.current;
    if (initial) setLoading(true);
    else setRefreshing(true);

    const requests = await Promise.allSettled([
      api.dashboard(),
      api.risk(locationId),
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
    ] as const);

    if (currentRequest !== requestId.current) return;

    const failures = requests
      .filter((result): result is PromiseRejectedResult => result.status === "rejected")
      .map((result) => errorMessage(result.reason));

    setData((previous) => ({
      summary: requests[0].status === "fulfilled" ? requests[0].value : previous.summary,
      risk: requests[1].status === "fulfilled" ? requests[1].value : previous.risk,
      weather: requests[2].status === "fulfilled" ? requests[2].value : previous.weather,
      river: requests[3].status === "fulfilled" ? requests[3].value : previous.river,
      incidents: requests[4].status === "fulfilled" ? requests[4].value : previous.incidents,
      reports: requests[5].status === "fulfilled" ? requests[5].value : previous.reports,
      events: requests[6].status === "fulfilled" ? requests[6].value : previous.events,
      system: requests[7].status === "fulfilled" ? requests[7].value : previous.system,
      simulation: requests[8].status === "fulfilled" ? requests[8].value : previous.simulation,
      nationalRisk: requests[12].status === "fulfilled" ? requests[12].value : previous.nationalRisk,
      waterIntelligence: requests[13].status === "fulfilled" ? requests[13].value : previous.waterIntelligence,
      resources: {
        shelters: requests[9].status === "fulfilled" ? requests[9].value : previous.resources.shelters,
        hospitals: requests[10].status === "fulfilled" ? requests[10].value : previous.resources.hospitals,
        contacts: requests[11].status === "fulfilled" ? requests[11].value : previous.resources.contacts,
      },
    }));
    setErrors([...new Set(failures)]);
    setLastUpdated(new Date());
    setLoading(false);
    setRefreshing(false);
  }, [locationId]);

  useEffect(() => {
    void refresh(true);
    const timer = window.setInterval(() => void refresh(false), REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  return { data, loading, refreshing, errors, lastUpdated, refresh };
}
