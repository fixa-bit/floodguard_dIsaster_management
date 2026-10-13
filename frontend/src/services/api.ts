import { API_BASE_URL } from "../config";
import type {
  ExperimentalHydrograph,
  GaugeKind,
  OfficialStationHistory,
  GoogleFloodCollection,
  AutomationContext,
  CitizenReport,
  DashboardSummary,
  Incident,
  ModelForecastPoint,
  NationalRiskCollection,
  RegionalRainfallCollection,
  Resource,
  RiskResponse,
  RiverResponse,
  SimulationStatus,
  SimulationStation,
  MonitoringSimulationRequest,
  MonitoringSimulationResult,
  SystemEvent,
  SystemStatus,
  UpstreamForecastResponse,
  RiverMonitoringResponse,
  WaterIntelligenceCollection,
  WeatherResponse,
  SarInputRole,
  SarWaterOverlay,
} from "../types/api";

interface ErrorPayload {
  error?: { code?: string; message?: string };
  detail?: string | { loc?: (string | number)[]; msg?: string }[];
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

export async function apiFetch<T>(path: string, options?: RequestInit, baseUrl = API_BASE_URL, timeoutMs?: number): Promise<T> {
  let response: Response;
  const controller = new AbortController();
  const cancel = () => controller.abort();
  options?.signal?.addEventListener("abort", cancel, { once: true });
  if (options?.signal?.aborted) controller.abort();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs ?? (options?.body instanceof FormData ? 120000 : 30000));
  try {
    response = await fetch(`${baseUrl}${path}`, {
      ...options,
      signal: controller.signal,
      headers: {
        ...(options?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...options?.headers,
      },
    });
  } catch (error) {
    const message = error instanceof DOMException && error.name === "AbortError"
      ? "FloodGuard backend request timed out"
      : "Cannot reach the FloodGuard backend";
    throw new ApiError(0, "BACKEND_UNAVAILABLE", message);
  } finally {
    window.clearTimeout(timeout);
    options?.signal?.removeEventListener("abort", cancel);
  }

  if (!response.ok) {
    let payload: ErrorPayload = {};
    try {
      payload = (await response.json()) as ErrorPayload;
    } catch {
      // Keep the status-based message below.
    }
    const providerMessage = response.status === 502 ? "Live data provider is temporarily unavailable" : undefined;
    const detail = typeof payload.detail === "string" ? payload.detail : payload.detail
      ?.map((issue) => `${issue.loc?.filter((part) => part !== "body").join(".") || "Testing data"}: ${issue.msg ?? "Invalid value"}`).join("; ");
    throw new ApiError(
      response.status,
      payload.error?.code ?? `HTTP_${response.status}`,
      payload.error?.message ?? detail ?? providerMessage ?? "Request failed",
    );
  }

  return (await response.json()) as T;
}

export const api = {
  sarWaterExtentAtLocation: (latitude: number, longitude: number) =>
    apiFetch<SarWaterOverlay>(`/flood/water-extent/location?latitude=${latitude}&longitude=${longitude}`, undefined, undefined, 120000),
  sarWaterExtent: (files: Record<SarInputRole, File>) => {
    const form = new FormData();
    for (const [role, file] of Object.entries(files)) form.append(role, file);
    return apiFetch<SarWaterOverlay>("/flood/water-extent", { method: "POST", body: form });
  },
  experimentalHydrograph: (id: string, days: 5 | 30, signal: AbortSignal) => apiFetch<ExperimentalHydrograph>(`/stations/${encodeURIComponent(id)}/hydrograph?days=${days}`, { signal }, API_BASE_URL.replace(/\/v1\/?$/, "")),
  dashboard: () => apiFetch<DashboardSummary>("/dashboard/summary"),
  risk: (locationId: string) => apiFetch<RiskResponse>(`/flood/risk?location_id=${locationId}`),
  modelForecasts: () => apiFetch<ModelForecastPoint[]>("/flood/model-forecasts"),
  weather: (locationId: string) => apiFetch<WeatherResponse>(`/weather/current?location_id=${locationId}`),
  river: (locationId: string) => apiFetch<RiverResponse>(`/river/current?location_id=${locationId}`),
  upstreamForecasts: () => apiFetch<UpstreamForecastResponse>("/river/upstream-forecasts"),
  refreshUpstreamForecasts: () => apiFetch<UpstreamForecastResponse>("/river/upstream-forecasts/refresh", { method: "POST" }),
  riverMonitoring: () => apiFetch<RiverMonitoringResponse>("/river/monitoring"),
  stationHistory: (id: string, signal: AbortSignal) => apiFetch<{ station_id: string; source: string; samples: Array<{ time: string; value: number }> }>(`/river/monitoring/${encodeURIComponent(id)}/history`, { signal }),
  officialStationHistory: (id: string, gauge: GaugeKind, signal: AbortSignal) => apiFetch<OfficialStationHistory>(`/river/monitoring/${encodeURIComponent(id)}/official-history?gauge=${gauge}`, { signal }),
  refreshRiverMonitoring: () => apiFetch<RiverMonitoringResponse>("/river/monitoring/refresh", { method: "POST" }),
  incidents: () => apiFetch<Incident[]>("/incidents"),
  citizenReports: () => apiFetch<CitizenReport[]>("/citizen-reports"),
  createCitizenReport: (payload: {
    location_id: string;
    latitude: number;
    longitude: number;
    description: string;
    image_url?: string | null;
    video_url?: string | null;
    image_latitude?: number | null;
    image_longitude?: number | null;
    reported_water_depth_cm?: number | null;
    source?: string;
  }) =>
    apiFetch<CitizenReport>("/citizen-reports", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  toggleCitizenReportImportant: (reportId: number) => apiFetch<CitizenReport>(`/citizen-reports/${reportId}/important`, { method: "PATCH" }),
  closeCitizenReport: (reportId: number) => apiFetch<CitizenReport>(`/citizen-reports/${reportId}/close`, { method: "PATCH" }),
  events: () => apiFetch<SystemEvent[]>("/events?limit=40"),
  systemStatus: () => apiFetch<SystemStatus>("/system/status"),
  simulationStatus: () => apiFetch<SimulationStatus>("/simulation/status"),
  simulationStations: () => apiFetch<SimulationStation[]>("/simulation/monitoring/stations"),
  playMonitoringSimulation: (payload: MonitoringSimulationRequest) => apiFetch<MonitoringSimulationResult>("/simulation/monitoring/play", { method: "POST", body: JSON.stringify(payload) }),
  alerts: () => apiFetch<SystemEvent[]>("/alerts"),
  approveSimulatedAlert: (alertId: number) => apiFetch<SystemEvent>(`/alerts/${alertId}/approve`, { method: "POST" }),
  automation: (locationId: string) => apiFetch<AutomationContext>(`/automation/context?location_id=${locationId}`),
  shelters: () => apiFetch<Resource[]>("/resources/shelters"),
  hospitals: () => apiFetch<Resource[]>("/resources/hospitals"),
  contacts: () => apiFetch<Resource[]>("/resources/emergency-contacts"),
  nationalRisk: () => apiFetch<NationalRiskCollection>("/gis/national-risk"),
  rainfall: () => apiFetch<RegionalRainfallCollection>("/gis/rainfall"),
  googleFloodHub: () => apiFetch<GoogleFloodCollection>("/gis/google-flood-hub"),
  waterIntelligence: () => apiFetch<WaterIntelligenceCollection>("/gis/water-intelligence"),
  startSimulation: (scenario: string, locationId: string) =>
    apiFetch<SimulationStatus>("/simulation/start", {
      method: "POST",
      body: JSON.stringify({ scenario, location_id: locationId }),
    }),
  advanceSimulation: () => apiFetch<SimulationStatus>("/simulation/advance", { method: "POST" }),
  resetSimulation: () => apiFetch<SimulationStatus>("/simulation/reset", { method: "POST" }),
};
