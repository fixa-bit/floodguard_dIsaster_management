import { API_BASE_URL } from "../config";
import { markStale, readLastGood, saveLastGood } from "./lastGoodCache";
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
  MaralaMonthlyModelData,
  MaralaStationForecastData,
  RiverineExtendedForecastData,
  RiverineOutlookData,
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

// Requests whose saved copy would be misleading if replayed (job progress polls).
const NO_FALLBACK = [/^\/generated-reports\/jobs\//, /^\/population\/analyses\//];

// Endpoints that answer 200 with an empty or "unavailable" body when their live
// provider is down. That body must not replace the last good copy.
const USABLE: Array<[RegExp, (payload: any) => boolean]> = [
  [/^\/gis\/google-flood-hub/, (payload) => payload?.metadata?.status !== "unavailable"],
  [/^\/river\/(monitoring|upstream-forecasts)$/, (payload) => Array.isArray(payload?.stations) && payload.stations.length > 0],
];

const LABELS: Array<[RegExp, string]> = [
  [/^\/dashboard\/summary/, "Dashboard summary"], [/^\/flood\/risk/, "Flood risk"],
  [/^\/flood\/model-forecasts/, "Model forecasts"], [/^\/weather\/current/, "Weather"],
  [/^\/river\/current/, "River gauge"], [/^\/river\/upstream-forecasts/, "Upstream forecasts"],
  [/^\/river\/monitoring\/[^/]+\/official-history/, "Official station history"],
  [/^\/river\/monitoring\/[^/]+\/history/, "Station history"], [/^\/river\/monitoring/, "River monitoring"],
  [/^\/gis\/national-risk/, "National risk map"], [/^\/gis\/rainfall/, "Rainfall"],
  [/^\/gis\/google-flood-hub/, "Google Flood Hub"], [/^\/gis\/water-intelligence/, "Water intelligence"],
  [/^\/stations\/[^/]+\/hydrograph/, "Hydrograph"], [/^\/predictive\/riverine-extended-forecast/, "Extended riverine forecast"], [/^\/predictive\/riverine-outlook/, "Riverine outlook"],[/^\/predictive\/marala-monthly/, "Marala monthly model"],
  [/^\/predictive\/marala-station-forecast/, "Marala station forecast"], [/^\/incidents/, "Incidents"],
  [/^\/citizen-reports/, "Citizen reports"], [/^\/events/, "System events"], [/^\/alerts/, "Alerts"],
  [/^\/system\/status/, "System status"], [/^\/simulation/, "Simulation"], [/^\/resources\/shelters/, "Shelters"],
  [/^\/resources\/hospitals/, "Hospitals"], [/^\/resources\/emergency-contacts/, "Emergency contacts"],
  [/^\/generated-reports/, "Reports"], [/^\/alarm-automation/, "Alerts & Alarms"], [/^\/population|^\/exposure/, "Population analysis"],
];

function fallbackEligible(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 0 || error.status === 408 || error.status === 429 || error.status >= 500);
}

/** GET requests fall back to their last successful response when the backend or its live provider fails. */
export async function apiFetch<T>(path: string, options?: RequestInit, baseUrl = API_BASE_URL, timeoutMs?: number): Promise<T> {
  const method = (options?.method ?? "GET").toUpperCase();
  if (method !== "GET" || NO_FALLBACK.some((pattern) => pattern.test(path))) return requestJson<T>(path, options, baseUrl, timeoutMs);
  const key = `${baseUrl}${path}`;
  const location = /[?&]location_id=([^&]+)/.exec(path)?.[1];
  const label = `${LABELS.find(([pattern]) => pattern.test(path))?.[1] ?? path.split("?")[0]}${location ? ` (${decodeURIComponent(location)})` : ""}`;
  const serveSaved = async (error: unknown): Promise<T> => {
    const saved = await readLastGood(key);
    if (!saved) throw error;
    markStale(key, label, saved.savedAt);
    return saved.data as T;
  };
  let payload: T;
  try {
    payload = await requestJson<T>(path, options, baseUrl, timeoutMs);
  } catch (error) {
    // A request the caller cancelled is not an outage.
    if (options?.signal?.aborted || !fallbackEligible(error)) throw error;
    return serveSaved(error);
  }
  const usable = USABLE.find(([pattern]) => pattern.test(path))?.[1];
  if (usable && !usable(payload)) {
    try { return await serveSaved(null); } catch { return payload; }
  }
  saveLastGood(key, payload);
  return payload;
}

async function requestJson<T>(path: string, options?: RequestInit, baseUrl = API_BASE_URL, timeoutMs?: number): Promise<T> {
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
  sarWaterExample: async (example: "historical" | "permanent" = "historical"): Promise<SarWaterOverlay> => {
    const response = await fetch(`${import.meta.env.BASE_URL}examples/${example === "permanent" ? "sar-pakistan-permanent" : "sar-pakistan"}.json`);
    if (!response.ok) throw new Error("The historical flood example could not be loaded.");
    return response.json() as Promise<SarWaterOverlay>;
  },
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
  maralaMonthlyModelData: () => apiFetch<MaralaMonthlyModelData>("/predictive/marala-monthly"),
  maralaStationForecast: () => apiFetch<MaralaStationForecastData>("/predictive/marala-station-forecast"),
  riverineExtendedForecast: () => apiFetch<RiverineExtendedForecastData>("/predictive/riverine-extended-forecast"),
  riverineOutlook: (stationId: string) => apiFetch<RiverineOutlookData>(`/predictive/riverine-outlook/${encodeURIComponent(stationId)}`),
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
