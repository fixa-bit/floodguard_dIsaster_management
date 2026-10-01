import { API_BASE_URL } from "../config";
import type {
  AutomationContext,
  CitizenReport,
  DashboardSummary,
  Incident,
  NationalRiskCollection,
  Resource,
  RiskResponse,
  RiverResponse,
  SimulationStatus,
  SystemEvent,
  SystemStatus,
  WaterIntelligenceCollection,
  WeatherResponse,
} from "../types/api";

interface ErrorPayload {
  error?: { code?: string; message?: string };
  detail?: string;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options?.headers,
      },
    });
  } catch {
    throw new ApiError(0, "BACKEND_UNAVAILABLE", "Cannot reach the FloodGuard backend");
  }

  if (!response.ok) {
    let payload: ErrorPayload = {};
    try {
      payload = (await response.json()) as ErrorPayload;
    } catch {
      // Keep the status-based message below.
    }
    const providerMessage = response.status === 502 ? "Live data provider is temporarily unavailable" : undefined;
    throw new ApiError(
      response.status,
      payload.error?.code ?? `HTTP_${response.status}`,
      payload.error?.message ?? payload.detail ?? providerMessage ?? "Request failed",
    );
  }

  return (await response.json()) as T;
}

export const api = {
  dashboard: () => apiFetch<DashboardSummary>("/dashboard/summary"),
  risk: (locationId: string) => apiFetch<RiskResponse>(`/flood/risk?location_id=${locationId}`),
  weather: (locationId: string) => apiFetch<WeatherResponse>(`/weather/current?location_id=${locationId}`),
  river: (locationId: string) => apiFetch<RiverResponse>(`/river/current?location_id=${locationId}`),
  incidents: () => apiFetch<Incident[]>("/incidents"),
  citizenReports: () => apiFetch<CitizenReport[]>("/citizen-reports"),
  events: () => apiFetch<SystemEvent[]>("/events?limit=40"),
  systemStatus: () => apiFetch<SystemStatus>("/system/status"),
  simulationStatus: () => apiFetch<SimulationStatus>("/simulation/status"),
  automation: (locationId: string) => apiFetch<AutomationContext>(`/automation/context?location_id=${locationId}`),
  shelters: () => apiFetch<Resource[]>("/resources/shelters"),
  hospitals: () => apiFetch<Resource[]>("/resources/hospitals"),
  contacts: () => apiFetch<Resource[]>("/resources/emergency-contacts"),
  nationalRisk: () => apiFetch<NationalRiskCollection>("/gis/national-risk"),
  waterIntelligence: () => apiFetch<WaterIntelligenceCollection>("/gis/water-intelligence"),
  startSimulation: (scenario: string, locationId: string) =>
    apiFetch<SimulationStatus>("/simulation/start", {
      method: "POST",
      body: JSON.stringify({ scenario, location_id: locationId }),
    }),
  advanceSimulation: () => apiFetch<SimulationStatus>("/simulation/advance", { method: "POST" }),
  resetSimulation: () => apiFetch<SimulationStatus>("/simulation/reset", { method: "POST" }),
};
