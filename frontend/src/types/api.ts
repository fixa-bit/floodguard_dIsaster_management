export type Severity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type Trend = "FALLING" | "STABLE" | "RISING" | "RAPIDLY_RISING";

export interface DashboardSummary {
  active_incidents: number;
  critical_incidents: number;
  predicted_floods: number;
  confirmed_floods: number;
  pending_citizen_reports: number;
  highest_risk_probability: number;
  monitoring_mode: string;
  system_mode: string;
}

export interface RiskResponse {
  location_id: string;
  location_name: string;
  timestamp: string;
  scenario: string;
  flood_probability: number;
  severity: Severity;
  status: string;
  confidence: number;
  factors: string[];
  explanation: string;
  monitoring_mode: string;
  monitoring_interval_minutes: number;
  trend: Trend;
  probability_change: number;
  model: string;
  model_type: string;
  top_risk_factors: string[];
  data_sources: Record<string, string>;
}

export interface ModelForecastPoint {
  id: number;
  model_case: string;
  target_id: string;
  target_name: string;
  issued_at: string;
  valid_at: string;
  horizon_hours: number;
  value: number;
  value_unit: string;
  probability: number | null;
  risk_class: string;
  model_name: string;
  point_metadata: Record<string, unknown>;
  created_at: string;
}

export interface WeatherResponse {
  location_id: string;
  location_name: string;
  timestamp: string;
  source: string;
  scenario: string;
  rainfall_current_mm: number;
  rainfall_last_1h_mm: number;
  rainfall_last_6h_mm: number;
  rainfall_last_24h_mm: number;
  forecast_rainfall_next_6h_mm: number;
  forecast_rainfall_next_24h_mm: number;
  temperature_c: number;
  humidity_percent: number;
  soil_moisture_percent: number;
}

export interface RiverResponse {
  location_id: string;
  location_name: string;
  timestamp: string;
  source: string;
  scenario: string;
  river_name: string;
  station_name: string;
  river_level_m: number | null;
  observed_level_value: number | null;
  observed_level_unit: string | null;
  official_recording_time: string | null;
  data_note: string | null;
  normal_level_m: number | null;
  warning_level_m: number | null;
  danger_level_m: number | null;
  rate_of_rise_m_per_hour: number | null;
  discharge_cumecs: number | null;
  discharge_change_cumecs_per_day: number | null;
  forecast_discharge_next_24h_cumecs: number | null;
  discharge_mean_cumecs: number | null;
  discharge_median_cumecs: number | null;
  discharge_min_cumecs: number | null;
  discharge_max_cumecs: number | null;
  discharge_p25_cumecs: number | null;
  discharge_p75_cumecs: number | null;
  status: string;
}

export interface Incident {
  id: number;
  location_id: string;
  type: string;
  severity: Severity;
  status: string;
  confidence: number;
  description: string;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface CitizenReport {
  id: number;
  location_id: string;
  latitude: number;
  longitude: number;
  description: string;
  image_url: string | null;
  video_url: string | null;
  image_latitude: number | null;
  image_longitude: number | null;
  reported_water_depth_cm: number | null;
  source: string;
  verification_status: string;
  report_status: string;
  is_important: boolean;
  important_marked_at: string | null;
  closed_at: string | null;
  timestamp: string;
}

export interface SystemEvent {
  id: number;
  timestamp: string;
  event_type: string;
  location_id: string | null;
  message: string;
  event_metadata: Record<string, unknown>;
}

export interface SystemStatus {
  data_mode: string;
  active_scenario: string;
  monitoring_mode: string;
  monitoring_interval_minutes: number;
  backend_status: string;
  simulation_enabled: boolean;
  rule_based_fallback_enabled: boolean;
  ml_model_enabled: boolean;
}

export interface SimulationStatus {
  simulation_time: string;
  scenario: string;
  location_id: string;
  monitoring_mode: string;
  monitoring_interval_minutes: number;
}

export interface Resource {
  id: string;
  name: string;
  location_id: string;
  latitude: number;
  longitude: number;
  address: string;
  phone: string | null;
  capacity: number | null;
  resource_type: string;
}

export interface AutomationContext {
  location_id: string;
  risk_probability: number;
  severity: Severity;
  incident_status: string;
  monitoring_interval_minutes: number;
  requires_verification: boolean;
  requires_alert: boolean;
}

export interface ResourceGroups {
  shelters: Resource[];
  hospitals: Resource[];
  contacts: Resource[];
}

export interface DistrictRiskProperties {
  display_boundary_source?: string;
  display_geometry_match?: boolean;
  district_id: string;
  district_name: string;
  admin_level: string;
  longitude: number;
  latitude: number;
  risk_probability: number;
  severity: Severity;
  status: string;
  confidence: number;
  risk_basis: string;
  model: string;
  model_type: string;
  source: string;
  scenario: string;
  top_risk_factors: string[];
  rainfall_6h_mm?: number;
  rainfall_24h_mm?: number;
  forecast_rainfall_24h_mm?: number;
  temperature_c?: number;
  humidity_percent?: number;
  soil_moisture_percent?: number;
}

export interface DistrictRiskFeature {
  type: "Feature";
  id: string;
  geometry: { type: "Polygon" | "MultiPolygon"; coordinates: unknown };
  properties: DistrictRiskProperties;
}

export interface NationalRiskCollection {
  type: "FeatureCollection";
  metadata: {
    coverage: string;
    feature_count: number;
    returned_feature_count: number;
    generated_at: string;
    observed_at: string;
    data_mode: string;
    scenario: string;
    risk_basis: string;
    methodology: string;
    boundary_source: string;
    cache_status: string;
    warning?: string;
  };
  features: DistrictRiskFeature[];
}

export type WaterDataClass = "gis_feature" | "observed_station" | "model_forecast";

export interface WaterIntelligenceProperties {
  name: string;
  water_system: string;
  feature_kind: string;
  data_class: WaterDataClass;
  data_status: string;
  telemetry_status: string;
  description: string;
  coordinate_quality?: "official" | "derived" | "approximate";
  geometry_source?: string;
  geometry_quality?: "official" | "derived" | "approximate";
  source?: string;
  location_id?: string;
  scenario?: string;
  details_endpoint?: string;
  monitoring_station_id?: string | null;
  observed_level_m?: number | null;
  observed_discharge_cumecs?: number | null;
  forecast_discharge_cumecs?: number | null;
}

export interface WaterIntelligenceFeature {
  type: "Feature";
  id: string;
  geometry: { type: "Point" | "LineString" | "MultiLineString"; coordinates: unknown };
  properties: WaterIntelligenceProperties;
}

export interface WaterIntelligenceCollection {
  type: "FeatureCollection";
  metadata: {
    coverage: string;
    feature_count: number;
    returned_feature_count: number;
    water_feature_count: number;
    observed_station_count: number;
    model_forecast_count: number;
    generated_at: string;
    data_mode: string;
    scenario: string;
    methodology: string;
    source_summary: string;
    map_notice: string;
    public_live_reading_note: string;
    forecast_provider: string;
  };
  features: WaterIntelligenceFeature[];
}

export interface HydroSeriesPoint {
  time: string;
  value: number | null;
  phase: "past" | "forecast" | string;
  low?: number | null;
  high?: number | null;
}

export interface RainfallPoint {
  date: string;
  precipitation_mm: number | null;
  probability_percent: number | null;
  phase: "past" | "forecast" | string;
}

export interface ProviderForecast {
  provider: string;
  source: string;
  status: string;
  river_id: number | null;
  generated_at: string | null;
  current_cumecs: number | null;
  peak_forecast_cumecs: number | null;
  peak_forecast_time: string | null;
  recent_trend_cumecs: number | null;
  series: HydroSeriesPoint[];
  retrospective: HydroSeriesPoint[];
  note: string | null;
}

export interface FloodTypeSignal {
  type: string;
  severity: Severity;
  probability: number;
  basis: string;
  lead_time: string;
}

export interface UpstreamStationForecast {
  id: string;
  name: string;
  river: string;
  basin: string;
  latitude: number;
  longitude: number;
  why_selected: string;
  source_focus: string;
  facts: string[];
  providers: ProviderForecast[];
  rainfall: RainfallPoint[];
  flood_types: FloodTypeSignal[];
  stats: Record<string, number | string | null>;
}

export interface UpstreamForecastResponse {
  generated_at: string;
  stations: UpstreamStationForecast[];
  notes: string[];
  cached_at: string | null;
  last_attempt_at: string | null;
  next_refresh_at: string | null;
  refresh_interval_minutes: number;
  refreshing: boolean;
  refresh_error: string | null;
}

export interface RiverMonitoringStation extends UpstreamStationForecast {
  current_discharge_cumecs: number | null;
  current_source: string;
  observed_at: string | null;
  forecast_discharge_cumecs: number | null;
  forecast_valid_at: string | null;
  change_24h_cumecs: number | null;
  change_source: string;
  flood_category: string;
  official_forecast_text: string | null;
  expected_peak_at: string | null;
  expected_peak_cumecs: number | null;
  upstream_station_ids: string[];
}

export interface RiverMonitoringResponse extends Omit<UpstreamForecastResponse, "stations"> {
  stations: RiverMonitoringStation[];
  chains: Record<string, string[]>;
}

export interface RegionalRainfallCollection {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    geometry: { type: "Point"; coordinates: [number, number] };
    properties: { accumulations_mm: Record<string, number | null> };
  }>;
  coverage: import("geojson").FeatureCollection;
  metadata: { source: string; generated_at: string; cache_status: string; missing_samples: number; warning: string | null };
}
export type GoogleFloodSeverity = "EXTREME" | "SEVERE" | "ABOVE_NORMAL" | "NO_FLOODING" | "UNKNOWN";

export interface GoogleFloodFeature {
  type: "Feature";
  id: string;
  geometry: { type: "Point"; coordinates: [number, number] };
  properties: {
    id: string;
    name: string;
    river: string;
    country_code: string;
    severity: GoogleFloodSeverity;
    severity_label: string;
    issued_at: string | null;
    forecast_start: string | null;
    forecast_end: string | null;
    trend: string;
    source: string;
    quality_verified: boolean;
    source_url: string;
  };
}

export interface GoogleFloodCollection {
  type: "FeatureCollection";
  features: GoogleFloodFeature[];
  metadata: {
    status: "live" | "stale" | "not_configured" | "unavailable";
    message: string | null;
    fetched_at: string | null;
    source: string;
    license: string;
    source_url: string;
  };
}
