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
  normal_level_m: number | null;
  warning_level_m: number | null;
  danger_level_m: number | null;
  rate_of_rise_m_per_hour: number | null;
  discharge_cumecs: number | null;
  discharge_change_cumecs_per_day: number | null;
  forecast_discharge_next_24h_cumecs: number | null;
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
  reported_water_depth_cm: number | null;
  source: string;
  verification_status: string;
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
