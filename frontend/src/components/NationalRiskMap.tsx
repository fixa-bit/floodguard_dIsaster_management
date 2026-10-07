import { AlertTriangle, Building2, CloudRain, Crosshair, Database, Gauge, Layers3, MapPinned, MessageSquareText, RadioTower, Waves, X } from "lucide-react";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, ImageSource, Map as MapLibreMap, MapLayerMouseEvent, StyleSpecification } from "maplibre-gl";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { FeatureCollection, Geometry, Point, Polygon } from "geojson";

import { LOCATIONS, MAP_STYLE_URL, type LocationId } from "../config";
import jammuKashmirContextRaw from "../data/pakistan/jammu_kashmir_context.geojson?raw";
import lineOfControlRaw from "../data/pakistan/line_of_control.geojson?raw";
import pakistanAdmin1Raw from "../data/pakistan/pakistan_admin1.geojson?raw";
import undeterminedBoundaryRaw from "../data/pakistan/undetermined_boundary.geojson?raw";
import workingBoundaryRaw from "../data/pakistan/working_boundary.geojson?raw";
import type { CitizenReport, DistrictRiskFeature, Incident, NationalRiskCollection, ResourceGroups, RiverResponse, RiverMonitoringResponse, WaterIntelligenceCollection, WaterIntelligenceFeature, WeatherResponse } from "../types/api";
import { StatusBadge } from "./StatusBadge";
import { api } from "../services/api";
import { RiverStationInspector } from "./RiverStationInspector";
import { rainfallImageCoordinates, renderRainfallRaster } from "./rainfallRaster";

maplibregl.setWorkerUrl(maplibreWorkerUrl);

interface NationalRiskMapProps {
  nationalRisk: NationalRiskCollection | null;
  waterIntelligence: WaterIntelligenceCollection | null;
  locationWeather: WeatherResponse[];
  locationRivers: RiverResponse[];
  incidents: Incident[];
  reports: CitizenReport[];
  resources: ResourceGroups;
  selectedLocation: LocationId;
  onLocationChange: (location: LocationId) => void;
  expanded?: boolean;
  initialRainfallEnabled?: boolean;
  mapOverlay?: ReactNode;
}

const baseStyle: StyleSpecification = {
  version: 8,
  sources: {
    "global-satellite-basemap": {
      type: "raster",
      tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
      tileSize: 256,
      attribution: "Imagery &copy; Esri, Maxar, Earthstar Geographics, and GIS user community",
    },
    "global-reference-labels": {
      type: "raster",
      tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}"],
      tileSize: 256,
      attribution: "Reference labels &copy; Esri",
    },
  },
  layers: [
    { id: "background", type: "background", paint: { "background-color": "#07171b" } },
    {
      id: "global-satellite-basemap",
      type: "raster",
      source: "global-satellite-basemap",
      paint: { "raster-opacity": 0.94, "raster-saturation": 0.18, "raster-contrast": 0.08 },
    },
    {
      id: "global-reference-labels",
      type: "raster",
      source: "global-reference-labels",
      paint: { "raster-opacity": 0.08 },
    },
  ],
};

const emptyCollection: FeatureCollection = { type: "FeatureCollection", features: [] };
const pakistanFitBounds: [[number, number], [number, number]] = [[45.8, 14.2], [93.8, 43.8]];
const pakistanFitPadding = { top: 58, right: 62, bottom: 68, left: 62 };
const pakistanFullExtentMaxZoom = 1.98;
const parseFeatureCollection = <T extends Geometry = Geometry>(raw: string) => JSON.parse(raw) as FeatureCollection<T>;
const jammuKashmirContext = parseFeatureCollection<Polygon>(jammuKashmirContextRaw);
const pakistanOperationalBase = parseFeatureCollection(pakistanAdmin1Raw);
const pakistanLocOverlay = parseFeatureCollection(lineOfControlRaw);
const pakistanWorkingBoundary = parseFeatureCollection(workingBoundaryRaw);
const pakistanUndeterminedBoundary = parseFeatureCollection(undeterminedBoundaryRaw);
const pakistanPoliticalLabels: FeatureCollection<Point> = {
  type: "FeatureCollection",
  features: [
    { type: "Feature", geometry: { type: "Point", coordinates: [64.6, 27.9] }, properties: { name: "BALOCHISTAN" } },
    { type: "Feature", geometry: { type: "Point", coordinates: [67.8, 25.7] }, properties: { name: "SINDH" } },
    { type: "Feature", geometry: { type: "Point", coordinates: [72.8, 30.7] }, properties: { name: "PUNJAB" } },
    { type: "Feature", geometry: { type: "Point", coordinates: [71.8, 34.2] }, properties: { name: "KHYBER PAKHTUNKHWA" } },
    { type: "Feature", geometry: { type: "Point", coordinates: [75.2, 35.95] }, properties: { name: "GILGIT-BALTISTAN" } },
    { type: "Feature", geometry: { type: "Point", coordinates: [74.35, 33.95] }, properties: { name: "AJ&K" } },
    { type: "Feature", geometry: { type: "Point", coordinates: [64.0, 33.5] }, properties: { name: "AFGHANISTAN" } },
    { type: "Feature", geometry: { type: "Point", coordinates: [60.6, 27.2] }, properties: { name: "IRAN" } },
    { type: "Feature", geometry: { type: "Point", coordinates: [78.2, 30.4] }, properties: { name: "INDIA" } },
    { type: "Feature", geometry: { type: "Point", coordinates: [78.2, 38.0] }, properties: { name: "CHINA" } },
    { type: "Feature", geometry: { type: "Point", coordinates: [64.2, 22.3] }, properties: { name: "ARABIAN SEA" } },
  ],
};

type RainfallWindowId = "last_1h" | "last_3h" | "last_6h" | "last_24h" | "next_24h" | "next_72h";

const rainfallWindowOptions: Array<{ id: RainfallWindowId; label: string; sourceLabel: string }> = [
  { id: "last_1h", label: "Last 1 hour", sourceLabel: "Estimated recent accumulation" },
  { id: "last_3h", label: "Last 3 hours", sourceLabel: "Estimated 3h accumulation" },
  { id: "last_6h", label: "Last 6 hours", sourceLabel: "Observed 6h accumulation" },
  { id: "last_24h", label: "Last 24 hours", sourceLabel: "Observed 24h accumulation" },
  { id: "next_24h", label: "Next 24 hours", sourceLabel: "Forecast 24h accumulation" },
  { id: "next_72h", label: "Next 72 hours", sourceLabel: "Forecast 72h projection" },
];

function rainfallValue(weather: WeatherResponse, windowId: RainfallWindowId) {
  switch (windowId) {
    case "last_1h":
      return weather.rainfall_last_1h_mm;
    case "last_3h":
      return Math.max(weather.rainfall_last_1h_mm, weather.rainfall_last_6h_mm * 0.58);
    case "last_6h":
      return weather.rainfall_last_6h_mm;
    case "last_24h":
      return weather.rainfall_last_24h_mm;
    case "next_24h":
      return weather.forecast_rainfall_next_24h_mm;
    case "next_72h":
      return weather.forecast_rainfall_next_24h_mm * 2.35;
    default:
      return 0;
  }
}

function districtRainfallValue(feature: DistrictRiskFeature, windowId: RainfallWindowId) {
  const rainfall6h = feature.properties.rainfall_6h_mm;
  const rainfall24h = feature.properties.rainfall_24h_mm;
  const forecast24h = feature.properties.forecast_rainfall_24h_mm;
  switch (windowId) {
    case "last_1h":
      return rainfall6h === undefined ? null : rainfall6h / 6;
    case "last_3h":
      return rainfall6h === undefined ? null : rainfall6h * 0.55;
    case "last_6h":
      return rainfall6h ?? null;
    case "last_24h":
      return rainfall24h ?? null;
    case "next_24h":
      return forecast24h ?? null;
    case "next_72h":
      return forecast24h === undefined ? null : forecast24h * 2.35;
    default:
      return null;
  }
}

function buildRainfallHeatmapData(
  locationWeather: WeatherResponse[],
  nationalRisk: NationalRiskCollection | null,
  windowId: RainfallWindowId,
) {
  const weatherAnchors = locationWeather.flatMap((weather) => {
    const location = locationCoordinates(weather.location_id);
    return location ? [{ longitude: location.longitude, latitude: location.latitude, value: rainfallValue(weather, windowId), weight: 1.8 }] : [];
  });
  const districtAnchors = (nationalRisk?.features ?? []).flatMap((feature) => {
    const value = districtRainfallValue(feature, windowId);
    return value === null ? [] : [{ longitude: feature.properties.longitude, latitude: feature.properties.latitude, value, weight: 1 }];
  });
  return renderRainfallRaster([...weatherAnchors, ...districtAnchors], pakistanOperationalBase);
}
function addIcon(map: MapLibreMap, name: string, draw: (context: CanvasRenderingContext2D) => void) {
  if (map.hasImage(name)) return;
  const canvas = document.createElement("canvas");
  canvas.width = 32;
  canvas.height = 32;
  const context = canvas.getContext("2d");
  if (!context) return;
  draw(context);
  map.addImage(name, context.getImageData(0, 0, canvas.width, canvas.height), { pixelRatio: 2 });
}

function addWaterIcons(map: MapLibreMap) {
  addIcon(map, "water-dot", (context) => {
    context.fillStyle = "#38bdf8";
    context.strokeStyle = "#effcff";
    context.lineWidth = 3;
    context.beginPath();
    context.arc(16, 16, 7, 0, Math.PI * 2);
    context.fill();
    context.stroke();
  });
  addIcon(map, "dam-icon", (context) => {
    context.fillStyle = "#0ea5e9";
    context.strokeStyle = "#ffffff";
    context.lineWidth = 2;
    context.beginPath();
    context.moveTo(7, 21);
    context.lineTo(10, 10);
    context.lineTo(14, 21);
    context.lineTo(18, 10);
    context.lineTo(22, 21);
    context.lineTo(25, 10);
    context.lineTo(25, 24);
    context.lineTo(7, 24);
    context.closePath();
    context.fill();
    context.stroke();
  });
  addIcon(map, "gauge-ring", (context) => {
    context.fillStyle = "#e0f7ff";
    context.strokeStyle = "#38d5ff";
    context.lineWidth = 5;
    context.beginPath();
    context.arc(16, 16, 9, 0, Math.PI * 2);
    context.fill();
    context.stroke();
  });
  addIcon(map, "model-diamond", (context) => {
    context.fillStyle = "#8b5cf6";
    context.strokeStyle = "#ffffff";
    context.lineWidth = 3;
    context.beginPath();
    context.moveTo(16, 5);
    context.lineTo(27, 16);
    context.lineTo(16, 27);
    context.lineTo(5, 16);
    context.closePath();
    context.fill();
    context.stroke();
  });
}

function pointCollection(features: Array<{ longitude: number; latitude: number; properties: Record<string, unknown> }>): FeatureCollection<Point> {
  return {
    type: "FeatureCollection",
    features: features.map((feature) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [feature.longitude, feature.latitude] },
      properties: feature.properties,
    })),
  };
}

function locationCoordinates(locationId: string) {
  return LOCATIONS.find((location) => location.id === locationId);
}

function fitPakistanExtent(map: MapLibreMap, duration = 0) {
  map.resize();
  const camera = map.cameraForBounds(pakistanFitBounds, { padding: pakistanFitPadding });
  if (!camera?.center || camera.zoom === undefined) return;

  map.easeTo({
    center: camera.center,
    zoom: Math.max(map.getMinZoom(), Math.min(camera.zoom - 0.35, pakistanFullExtentMaxZoom)),
    duration,
  });
}

function normalizeWaterName(value: string | null | undefined) {
  return (value ?? "").toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function fitRainfallExtent(map: MapLibreMap, duration = 0) {
  map.resize();
  const mobile = map.getContainer().clientWidth < 700;
  map.fitBounds([[60.6, 23.2], [77.4, 37.4]], {
    padding: { top: mobile ? 240 : 190, bottom: 110, left: mobile ? 16 : 240, right: mobile ? 16 : 50 },
    maxZoom: 5,
    duration,
  });
}

function riverStatusClass(river: RiverResponse | undefined) {
  const status = river?.status.toUpperCase();
  if (!status) return "UNKNOWN";
  if (["DANGER", "FLOOD", "CRITICAL", "ALERT"].includes(status)) return "DANGER";
  if (["WARNING"].includes(status)) return "WARNING";
  const current = river?.discharge_cumecs ?? null;
  const forecast = river?.forecast_discharge_next_24h_cumecs ?? null;
  const p75 = river?.discharge_p75_cumecs ?? null;
  const max = river?.discharge_max_cumecs ?? null;
  const dailyChange = river?.discharge_change_cumecs_per_day ?? 0;
  if (current !== null && max !== null && max > 0 && current >= max * 0.95 && forecast !== null && forecast >= current) return "DANGER";
  if (current !== null && p75 !== null && p75 > 0 && current >= p75 * 1.05) return "WARNING";
  if ((forecast !== null && current !== null && forecast > current * 1.05) || dailyChange > 0) return "RISING";
  if (["RISING"].includes(status)) return "RISING";
  return "NORMAL";
}

function matchRiverTelemetry(feature: WaterIntelligenceFeature, rivers: RiverResponse[]) {
  const waterSystem = normalizeWaterName(feature.properties.water_system);
  const name = normalizeWaterName(feature.properties.name);
  return rivers.find((river) => {
    const riverName = normalizeWaterName(river.river_name);
    return Boolean(riverName) && (waterSystem.includes(riverName) || name.includes(riverName) || riverName.includes(waterSystem));
  });
}

export function NationalRiskMap({ nationalRisk, waterIntelligence, locationWeather, locationRivers, incidents, reports, resources, selectedLocation, onLocationChange, expanded = false, initialRainfallEnabled = false, mapOverlay }: NationalRiskMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const nationalRiskRef = useRef(nationalRisk);
  const waterIntelligenceRef = useRef(waterIntelligence);
  const locationChangeRef = useRef(onLocationChange);
  const suppressDistrictFallbackRef = useRef(false);
  const [selectedDistrict, setSelectedDistrict] = useState<DistrictRiskFeature | null>(null);
  const [selectedWaterFeature, setSelectedWaterFeature] = useState<WaterIntelligenceFeature | null>(null);
  const [layers, setLayers] = useState({ risk: true, water: true, gauges: true, stations: true, incidents: true, reports: true, resources: true });
  const [rainfallHeatmapEnabled, setRainfallHeatmapEnabled] = useState(initialRainfallEnabled);
  const rainfallEnabledRef = useRef(rainfallHeatmapEnabled);
  rainfallEnabledRef.current = rainfallHeatmapEnabled;
  const [rainfallWindow, setRainfallWindow] = useState<RainfallWindowId>("last_24h");
  const [monitoring, setMonitoring] = useState<RiverMonitoringResponse | null>(null);
  const [monitoringError, setMonitoringError] = useState<string | null>(null);
  const [selectedStationId, setSelectedStationId] = useState<string | null>(null);
  const [monitoringRiver, setMonitoringRiver] = useState("All");
  const [refreshRequested, setRefreshRequested] = useState(false);
  const pollingInterval = monitoring?.refreshing || !monitoring?.stations.length ? 5000 : 60000;

  useEffect(() => {
    let active = true;
    const load = () => api.riverMonitoring().then((response) => {
      if (active) { setMonitoring(response); setMonitoringError(null); }
    }).catch((error: Error) => { if (active) setMonitoringError(error.message); });
    void load();
    const timer = window.setInterval(() => { void load(); }, pollingInterval);
    return () => { active = false; window.clearInterval(timer); };
  }, [pollingInterval]);

  async function refreshMonitoring() {
    setRefreshRequested(true);
    try { setMonitoring(await api.refreshRiverMonitoring()); setMonitoringError(null); }
    catch (error) { setMonitoringError(error instanceof Error ? error.message : "Refresh failed"); }
    finally { setRefreshRequested(false); }
  }

  function selectStation(id: string) {
    setSelectedStationId(id);
    setSelectedWaterFeature(null);
    setSelectedDistrict(null);
  }

  nationalRiskRef.current = nationalRisk;
  waterIntelligenceRef.current = waterIntelligence;
  locationChangeRef.current = onLocationChange;

  const operationalData = useMemo(() => ({
    stations: pointCollection(LOCATIONS.map((location) => ({
      longitude: location.longitude,
      latitude: location.latitude,
      properties: { id: location.id, name: location.name, selected: location.id === selectedLocation ? 1 : 0 },
    }))),
    incidents: pointCollection(incidents.flatMap((incident) => {
      const location = locationCoordinates(incident.location_id);
      return location ? [{ longitude: location.longitude, latitude: location.latitude, properties: { id: incident.id, severity: incident.severity } }] : [];
    })),
    reports: pointCollection(reports.map((report) => ({ longitude: report.longitude, latitude: report.latitude, properties: { id: report.id, status: report.verification_status } }))),
    resources: pointCollection([...resources.shelters, ...resources.hospitals, ...resources.contacts].map((resource) => ({ longitude: resource.longitude, latitude: resource.latitude, properties: { id: resource.id, type: resource.resource_type, name: resource.name } }))),
  }), [incidents, reports, resources, selectedLocation]);

  const waterData = useMemo(() => {
    const features = waterIntelligence?.features ?? [];
    return {
      lines: { type: "FeatureCollection", features: features.filter((feature) => feature.geometry.type === "LineString" || feature.geometry.type === "MultiLineString") } as FeatureCollection,
      bodies: { type: "FeatureCollection", features: features.filter((feature) => feature.geometry.type === "Point" && feature.properties.data_class === "gis_feature") } as FeatureCollection<Point>,
      observedStations: { type: "FeatureCollection", features: features.filter((feature) => feature.geometry.type === "Point" && feature.properties.data_class === "observed_station"
        && (monitoringRiver === "All" || monitoring?.chains[monitoringRiver]?.includes(feature.properties.monitoring_station_id ?? ""))).map((feature) => ({
          ...feature, properties: { ...feature.properties,
            flood_category: monitoring?.stations.find((station) => station.id === feature.properties.monitoring_station_id)?.flood_category ?? "Unavailable",
            selected: feature.properties.monitoring_station_id === selectedStationId ? 1 : 0,
          },
        })) } as FeatureCollection<Point>,
      modelPoints: { type: "FeatureCollection", features: features.filter((feature) => feature.geometry.type === "Point" && feature.properties.data_class === "model_forecast") } as FeatureCollection<Point>,
    };
  }, [waterIntelligence, monitoring, monitoringRiver, selectedStationId]);
  const waterDataRef = useRef(waterData);
  waterDataRef.current = waterData;

  const riverStatusLines = useMemo(() => {
    const riverLines = waterData.lines.features.map((feature) => {
      const waterFeature = feature as WaterIntelligenceFeature;
      const river = matchRiverTelemetry(waterFeature, locationRivers);
      return {
        ...waterFeature,
        properties: {
          ...waterFeature.properties,
          live_status: riverStatusClass(river),
          live_river_name: river?.river_name ?? waterFeature.properties.water_system,
          live_discharge_cumecs: river?.discharge_cumecs ?? null,
          live_forecast_cumecs: river?.forecast_discharge_next_24h_cumecs ?? null,
          live_fetched_at: river?.timestamp ?? null,
        },
      };
    });
    return { type: "FeatureCollection", features: riverLines } as FeatureCollection;
  }, [locationRivers, waterData.lines]);
  const rainfallHeatmapData = useMemo(() => buildRainfallHeatmapData(locationWeather, nationalRisk, rainfallWindow), [locationWeather, nationalRisk, rainfallWindow]);
  const selectedRainfallWindow = rainfallWindowOptions.find((option) => option.id === rainfallWindow) ?? rainfallWindowOptions[0];

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: MAP_STYLE_URL || baseStyle,
      center: [69.35, 30.45],
      zoom: expanded ? 3.45 : 3.25,
      minZoom: 0,
      maxZoom: 12,
      attributionControl: false,
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
    map.on("load", () => {
      requestAnimationFrame(() => (rainfallEnabledRef.current ? fitRainfallExtent : fitPakistanExtent)(map));
      window.setTimeout(() => (rainfallEnabledRef.current ? fitRainfallExtent : fitPakistanExtent)(map), 250);
      addWaterIcons(map);
      map.addSource("pakistan-political-labels", { type: "geojson", data: pakistanPoliticalLabels });
      map.addSource("jammu-kashmir-context", { type: "geojson", data: jammuKashmirContext });
      map.addLayer({ id: "jammu-kashmir-context-fill", type: "fill", source: "jammu-kashmir-context", paint: { "fill-color": "#afc0bd", "fill-opacity": 0.055 } });
      map.addLayer({ id: "jammu-kashmir-context-line", type: "line", source: "jammu-kashmir-context", paint: { "line-color": "#e1ece8", "line-width": ["interpolate", ["linear"], ["zoom"], 3, 0.75, 7, 1.25, 10, 1.8], "line-dasharray": [4, 3], "line-opacity": 0.44 } });
      map.addSource("pakistan-operational-base", { type: "geojson", data: pakistanOperationalBase });
      map.addLayer({
        id: "ndma-operational-fill",
        type: "fill",
        source: "pakistan-operational-base",
        paint: {
          "fill-color": "#9fb9b8",
          "fill-opacity": 0.12,
        },
      });
      map.addSource("district-risk", { type: "geojson", data: (nationalRiskRef.current ?? emptyCollection) as FeatureCollection });
      map.addLayer({
        id: "district-risk-fill",
        type: "fill",
        source: "district-risk",
        paint: {
          "fill-color": ["match", ["get", "severity"], "CRITICAL", "#ff244f", "HIGH", "#ff7a1a", "MEDIUM", "#ffd02f", "#2fd07e"],
          "fill-opacity": ["match", ["get", "severity"], "CRITICAL", 0.66, "HIGH", 0.58, "MEDIUM", 0.46, 0.18],
        },
      });
      map.addLayer({ id: "district-risk-line", type: "line", source: "district-risk", paint: { "line-color": "#d7ebe8", "line-width": ["interpolate", ["linear"], ["zoom"], 3, 0.35, 7, 0.62, 10, 1.05], "line-opacity": 0.42 } });
      map.addSource("rainfall-heatmap", { type: "image", url: rainfallHeatmapData.imageUrl, coordinates: rainfallImageCoordinates });
      map.addLayer({
        id: "rainfall-heatmap",
        type: "raster",
        source: "rainfall-heatmap",
        layout: { visibility: "none" },
        paint: {
          "raster-opacity": 0.72,
          "raster-resampling": "linear",
          "raster-fade-duration": 0,
        },
      });
      map.addLayer({ id: "ndma-operational-line", type: "line", source: "pakistan-operational-base", paint: { "line-color": "#f0fffb", "line-width": ["interpolate", ["linear"], ["zoom"], 3, 1.15, 7, 1.95, 10, 2.8], "line-opacity": 0.78 } });
      map.addSource("pakistan-loc-overlay", { type: "geojson", data: pakistanLocOverlay });
      map.addLayer({ id: "pakistan-loc-line", type: "line", source: "pakistan-loc-overlay", paint: { "line-color": "#f8fafc", "line-width": ["interpolate", ["linear"], ["zoom"], 3, 1.45, 7, 2.4, 10, 3.2], "line-dasharray": [5, 4], "line-opacity": 0.9 } });
      map.addSource("pakistan-working-boundary", { type: "geojson", data: pakistanWorkingBoundary });
      map.addLayer({ id: "pakistan-working-boundary-line", type: "line", source: "pakistan-working-boundary", paint: { "line-color": "#7a6d5c", "line-width": ["interpolate", ["linear"], ["zoom"], 3, 1.2, 7, 2, 10, 3], "line-dasharray": [2, 3], "line-opacity": 0.9 } });
      map.addSource("pakistan-undetermined-boundary", { type: "geojson", data: pakistanUndeterminedBoundary });
      map.addLayer({ id: "pakistan-undetermined-boundary-line", type: "line", source: "pakistan-undetermined-boundary", paint: { "line-color": "#8c7b88", "line-width": ["interpolate", ["linear"], ["zoom"], 3, 1.2, 7, 2, 10, 3], "line-dasharray": [1.2, 2.2], "line-opacity": 0.86 } });
      map.addSource("water-lines", { type: "geojson", data: waterData.lines });
      map.addLayer({ id: "water-lines-glow", type: "line", source: "water-lines", paint: { "line-color": "#0ea5e9", "line-width": ["interpolate", ["linear"], ["zoom"], 4, 4.2, 8, 7.2, 12, 11], "line-opacity": 0.26 } });
      map.addLayer({ id: "water-lines", type: "line", source: "water-lines", paint: { "line-color": "#4de7ff", "line-width": ["interpolate", ["linear"], ["zoom"], 4, 1.9, 8, 3.7, 12, 6.4], "line-opacity": 0.94 } });
      map.addSource("river-status-lines", { type: "geojson", data: riverStatusLines });
      map.addLayer({ id: "river-status-lines-glow", type: "line", source: "river-status-lines", paint: { "line-color": ["match", ["get", "live_status"], "DANGER", "#ff244f", "WARNING", "#ff7a1a", "RISING", "#ffd02f", "NORMAL", "#2fd07e", "#4de7ff"], "line-width": ["interpolate", ["linear"], ["zoom"], 4, 6, 8, 9, 12, 13], "line-opacity": 0.22 } });
      map.addLayer({ id: "river-status-lines", type: "line", source: "river-status-lines", paint: { "line-color": ["match", ["get", "live_status"], "DANGER", "#ff244f", "WARNING", "#ff7a1a", "RISING", "#ffd02f", "NORMAL", "#2fd07e", "#4de7ff"], "line-width": ["interpolate", ["linear"], ["zoom"], 4, 2.6, 8, 4.8, 12, 7.2], "line-opacity": 0.96 } });
      map.addSource("water-bodies", { type: "geojson", data: waterData.bodies });
      map.addLayer({ id: "water-bodies", type: "symbol", source: "water-bodies", layout: { "icon-image": ["case", ["in", ["get", "feature_kind"], ["literal", ["dam", "dam_reservoir", "reservoir"]]], "dam-icon", "water-dot"], "icon-size": 1, "icon-allow-overlap": true } });
      map.addSource("observed-water-stations", { type: "geojson", data: waterDataRef.current.observedStations });
      map.addLayer({ id: "observed-water-stations", type: "circle", source: "observed-water-stations", paint: {
        "circle-radius": ["case", ["==", ["get", "selected"], 1], 10, 7],
        "circle-color": ["match", ["get", "flood_category"], "Below low", "#28d983", "Low flood", "#ffc857", "Medium flood", "#ff9b43", "High flood", "#ff4d61", "Very high flood", "#ff4d61", "Exceptionally high flood", "#ff4d61", "#38cbea"],
        "circle-stroke-color": "#ffffff", "circle-stroke-width": 2,
      } });
      map.addSource("model-water-points", { type: "geojson", data: waterData.modelPoints });
      map.addLayer({ id: "model-water-points", type: "symbol", source: "model-water-points", layout: { "icon-image": "model-diamond", "icon-size": 1, "icon-allow-overlap": true } });
      map.addSource("stations", { type: "geojson", data: operationalData.stations });
      map.addLayer({ id: "stations", type: "circle", source: "stations", paint: { "circle-radius": ["case", ["==", ["get", "selected"], 1], 8, 6], "circle-color": ["case", ["==", ["get", "selected"], 1], "#ffdd3f", "#00bcd4"], "circle-stroke-color": "#ffffff", "circle-stroke-width": 2.2 } });
      map.addSource("incidents", { type: "geojson", data: operationalData.incidents });
      map.addLayer({ id: "incidents", type: "circle", source: "incidents", paint: { "circle-radius": 7, "circle-color": "#c83b44", "circle-stroke-color": "#ffffff", "circle-stroke-width": 2 } });
      map.addSource("reports", { type: "geojson", data: operationalData.reports });
      map.addLayer({ id: "reports", type: "circle", source: "reports", paint: { "circle-radius": 5, "circle-color": "#6d57a5", "circle-stroke-color": "#ffffff", "circle-stroke-width": 1.5 } });
      map.addSource("resources", { type: "geojson", data: operationalData.resources });
      map.addLayer({ id: "resources", type: "circle", source: "resources", paint: { "circle-radius": 5, "circle-color": "#16756f", "circle-stroke-color": "#ffffff", "circle-stroke-width": 1.5 } });
      map.addLayer({ id: "pakistan-region-labels", type: "symbol", source: "pakistan-political-labels", layout: { "text-field": ["get", "name"], "text-size": ["interpolate", ["linear"], ["zoom"], 3, 11, 6, 16], "text-letter-spacing": 0.08, "text-allow-overlap": false }, paint: { "text-color": "#38525a", "text-halo-color": "#ffffff", "text-halo-width": 1.5, "text-opacity": 0.82 } });

      map.on("mouseenter", "district-risk-fill", () => { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "district-risk-fill", () => { map.getCanvas().style.cursor = ""; });
      const selectDistrictFeature = (districtId: unknown) => {
        const district = nationalRiskRef.current?.features.find((feature) => feature.properties.district_id === districtId) ?? null;
        if (!district) return false;
        setSelectedDistrict(district);
        setSelectedWaterFeature(null);
        setSelectedStationId(null);
        return true;
      };
      map.on("click", "district-risk-fill", (event: MapLayerMouseEvent) => {
        selectDistrictFeature(event.features?.[0]?.properties?.district_id);
      });
      map.on("click", (event) => {
        if (suppressDistrictFallbackRef.current) {
          suppressDistrictFallbackRef.current = false;
          return;
        }
        const searchRadius = 48;
        const districtHit = map.queryRenderedFeatures([
          [event.point.x - searchRadius, event.point.y - searchRadius],
          [event.point.x + searchRadius, event.point.y + searchRadius],
        ], { layers: ["district-risk-fill"] })[0];
        selectDistrictFeature(districtHit?.properties?.district_id);
      });
      for (const layerId of ["water-lines", "river-status-lines", "water-bodies", "observed-water-stations", "model-water-points"] as const) {
        map.on("mouseenter", layerId, () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", layerId, () => { map.getCanvas().style.cursor = ""; });
        map.on("click", layerId, (event: MapLayerMouseEvent) => {
          if (layerId !== "observed-water-stations" && map.queryRenderedFeatures(event.point, { layers: ["observed-water-stations"] }).length) return;
          const hit = layerId === "observed-water-stations" ? [...(event.features ?? [])].sort((a, b) => {
            const aPoint = map.project((a.geometry as Point).coordinates as [number, number]);
            const bPoint = map.project((b.geometry as Point).coordinates as [number, number]);
            return Math.hypot(aPoint.x - event.point.x, aPoint.y - event.point.y) - Math.hypot(bPoint.x - event.point.x, bPoint.y - event.point.y);
          })[0] : event.features?.[0];
          const monitoringId = hit?.properties?.monitoring_station_id as string | undefined;
          if (monitoringId) {
            suppressDistrictFallbackRef.current = true;
            setSelectedStationId(monitoringId);
            setSelectedWaterFeature(null);
            setSelectedDistrict(null);
            return;
          }
          const id = hit?.id ?? hit?.properties?.id;
          const feature = waterIntelligenceRef.current?.features.find((item) => item.id === id) ?? null;
          suppressDistrictFallbackRef.current = feature !== null;
          setSelectedStationId(null);
          setSelectedWaterFeature(feature);
          setSelectedDistrict(null);
        });
      }
      map.on("click", "stations", (event: MapLayerMouseEvent) => {
        const id = event.features?.[0]?.properties?.id as LocationId | undefined;
        if (id) locationChangeRef.current(id);
      });
      map.on("sourcedata", (event) => {
        if (event.sourceId === "rainfall-heatmap" && event.isSourceLoaded && containerRef.current) {
          containerRef.current.dataset.rainfallReady = "true";
        }
      });
      map.on("idle", () => {
        const sourceDistricts = map.querySourceFeatures("district-risk").length;
        const renderedDistricts = map.queryRenderedFeatures({ layers: ["district-risk-fill"] }).length;
        if (containerRef.current) {
          containerRef.current.dataset.sourceFeatures = String(sourceDistricts);
          containerRef.current.dataset.renderedFeatures = String(renderedDistricts);
          containerRef.current.dataset.rainfallVisibility = String(map.getLayoutProperty("rainfall-heatmap", "visibility"));
          containerRef.current.dataset.rainfallReady = String(map.isSourceLoaded("rainfall-heatmap"));
          containerRef.current.dataset.monitoringStations = JSON.stringify(map.queryRenderedFeatures({ layers: ["observed-water-stations"] })
            .filter((feature) => feature.properties.monitoring_station_id && feature.geometry.type === "Point")
            .map((feature) => {
              const point = map.project((feature.geometry as Point).coordinates as [number, number]);
              return { id: feature.properties.monitoring_station_id, x: point.x, y: point.y };
            }));
        }
      });
    });
    const resizeObserver = new ResizeObserver(() => {
      if (rainfallEnabledRef.current) fitRainfallExtent(map);
      else if (map.loaded()) fitPakistanExtent(map);
      else map.resize();
    });
    resizeObserver.observe(containerRef.current);
    mapRef.current = map;
    return () => { resizeObserver.disconnect(); map.remove(); mapRef.current = null; };
  }, [expanded]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const updateSources = () => {
      if (!map.getSource("rainfall-heatmap")) { map.once("load", updateSources); return; }
    (map.getSource("district-risk") as GeoJSONSource | undefined)?.setData((nationalRisk ?? emptyCollection) as FeatureCollection);
    (map.getSource("rainfall-heatmap") as ImageSource | undefined)?.updateImage({ url: rainfallHeatmapData.imageUrl });
    if (containerRef.current) containerRef.current.dataset.rainfallCells = String(rainfallHeatmapData.cellCount);
    (map.getSource("water-lines") as GeoJSONSource | undefined)?.setData(waterData.lines);
    (map.getSource("river-status-lines") as GeoJSONSource | undefined)?.setData(riverStatusLines);
    (map.getSource("water-bodies") as GeoJSONSource | undefined)?.setData(waterData.bodies);
    (map.getSource("observed-water-stations") as GeoJSONSource | undefined)?.setData(waterData.observedStations);
    (map.getSource("model-water-points") as GeoJSONSource | undefined)?.setData(waterData.modelPoints);
    (map.getSource("stations") as GeoJSONSource | undefined)?.setData(operationalData.stations);
    (map.getSource("incidents") as GeoJSONSource | undefined)?.setData(operationalData.incidents);
    (map.getSource("reports") as GeoJSONSource | undefined)?.setData(operationalData.reports);
    (map.getSource("resources") as GeoJSONSource | undefined)?.setData(operationalData.resources);
    };
    updateSources();
    return () => { map.off("load", updateSources); };
  }, [nationalRisk, operationalData, rainfallHeatmapData, riverStatusLines, waterData]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const updateVisibility = () => {
      if (!map.getLayer("rainfall-heatmap")) { map.once("load", updateVisibility); return; }
    const visibility = (visible: boolean) => visible ? "visible" : "none";
    for (const id of ["jammu-kashmir-context-fill", "jammu-kashmir-context-line", "ndma-operational-fill", "ndma-operational-line", "district-risk-fill", "district-risk-line", "pakistan-loc-line", "pakistan-working-boundary-line", "pakistan-undetermined-boundary-line"]) map.setLayoutProperty(id, "visibility", visibility(layers.risk));
    const rainfallWasVisible = map.getLayoutProperty("rainfall-heatmap", "visibility") === "visible";
    map.setLayoutProperty("rainfall-heatmap", "visibility", visibility(rainfallHeatmapEnabled));
    if (containerRef.current) containerRef.current.dataset.rainfallVisibility = visibility(rainfallHeatmapEnabled);
    map.setPaintProperty("district-risk-fill", "fill-opacity", rainfallHeatmapEnabled ? 0 : ["match", ["get", "severity"], "CRITICAL", 0.66, "HIGH", 0.58, "MEDIUM", 0.46, 0.18]);
    if (rainfallHeatmapEnabled && !rainfallWasVisible) fitRainfallExtent(map, 350);
    for (const id of ["water-lines-glow", "water-lines", "river-status-lines-glow", "river-status-lines", "water-bodies", "model-water-points"]) map.setLayoutProperty(id, "visibility", visibility(layers.water));
    map.setLayoutProperty("observed-water-stations", "visibility", visibility(layers.gauges));
    for (const id of ["stations", "incidents", "reports", "resources"] as const) map.setLayoutProperty(id, "visibility", visibility(layers[id]));
    };
    updateVisibility();
    return () => { map.off("load", updateVisibility); };
  }, [layers, rainfallHeatmapEnabled]);

  const metadata = nationalRisk?.metadata;
  const waterMetadata = waterIntelligence?.metadata;
  const selectedWaterKind = selectedWaterFeature?.properties.data_class.replace("_", " ");
  return (
    <section className={`national-map-panel ${expanded ? "national-map-expanded" : ""}`}>
      <header className="map-panel-header">
        <div><span><MapPinned size={18} /></span><div><h2>Pakistan National Flood Risk &amp; Operations Map</h2><p>{metadata ? `${metadata.returned_feature_count} districts · observed ${new Date(metadata.observed_at).toLocaleString()}` : "Loading national coverage"}</p></div></div>
        <div className="map-header-meta"><StatusBadge value={metadata?.data_mode ?? "LOADING"} /><span><Database size={13} /> {metadata?.cache_status ?? "waiting"}</span></div>
      </header>
      <div className={`river-monitoring-layout ${selectedStationId ? "has-station" : ""}`}>
      <div className="map-workspace">
        <div ref={containerRef} className="national-map" aria-label="Interactive Pakistan district flood risk map" />
        {mapOverlay && <div className="map-command-overlay">{mapOverlay}</div>}
        <div className="map-layer-control">
          <div className="feature-visualization-control">
            <strong><CloudRain size={14} /> Feature visualization</strong>
            <label><input type="checkbox" checked={rainfallHeatmapEnabled} onChange={() => setRainfallHeatmapEnabled((current) => !current)} /><span>Rainfall heatmap</span></label>
            <div className="rainfall-window-grid" aria-label="Rainfall heatmap time window">
              {rainfallWindowOptions.map((option) => (
                <button key={option.id} type="button" aria-pressed={rainfallHeatmapEnabled && rainfallWindow === option.id} className={rainfallHeatmapEnabled && rainfallWindow === option.id ? "active" : ""} onClick={() => { setRainfallWindow(option.id); setRainfallHeatmapEnabled(true); }}>
                  {option.label}
                </button>
              ))}
            </div>
            <span className="rainfall-source-note">Interpolated weather data / {selectedRainfallWindow.sourceLabel}</span>
            {rainfallHeatmapEnabled && rainfallHeatmapData.cellCount === 0 && <span className="rainfall-source-note" role="status">{locationWeather.length || nationalRisk?.features.length ? "No rainfall detected for this period." : "Rainfall data unavailable."}</span>}
          </div>
          <details className="operational-layer-options">
          <summary><strong><Layers3 size={14} /> Operational layers</strong></summary>
          {([
            ["risk", "District screening"], ["water", "Water intelligence"], ["gauges", "River monitoring"], ["stations", "Risk locations"], ["incidents", "Incidents"], ["reports", "Citizen reports"], ["resources", "Response resources"],
          ] as const).map(([id, label]) => <label key={id}><input type="checkbox" checked={layers[id]} onChange={() => setLayers((current) => ({ ...current, [id]: !current[id] }))} /><span>{label}</span></label>)}
          <label className="river-network-select"><span>River</span><select aria-label="Monitoring river" value={monitoringRiver} onChange={(event) => setMonitoringRiver(event.target.value)}><option>All</option>{["Indus", "Ravi", "Chenab", "Sutlej"].map((river) => <option key={river}>{river}</option>)}</select></label>
          <label className="river-network-select"><span>Station</span><select aria-label="Monitoring station" value={selectedStationId ?? ""} onChange={(event) => { if (event.target.value) selectStation(event.target.value); }}><option value="">Select station</option>{Object.entries(monitoring?.chains ?? {}).filter(([river]) => monitoringRiver === "All" || monitoringRiver === river).map(([river, ids]) => <optgroup key={river} label={river}>{ids.map((id) => <option value={id} key={`${river}-${id}`}>{monitoring?.stations.find((station) => station.id === id)?.name ?? id}</option>)}</optgroup>)}</select></label>
          </details>
          <div className="map-control-notices">
            {metadata?.data_mode === "simulation" && <div className="map-simulation-label"><AlertTriangle size={15} /><strong>SIMULATED NATIONAL LAYER</strong></div>}
            {waterMetadata?.map_notice && <div className="map-water-notice"><AlertTriangle size={14} /><span>{waterMetadata.map_notice}</span></div>}
            <details className="map-boundary-details"><summary>Map boundaries</summary><div className="map-boundary-notice"><MapPinned size={14} /><span>Pakistan ADM1 base shows GB and AJ&K as operational areas; wider Jammu & Kashmir context is subdued below them with LoC as a separate line.</span></div></details>
            {waterMetadata && <div className="water-intelligence-summary"><Waves size={14} /><strong>Water intelligence</strong><span>{waterMetadata.water_feature_count} GIS features</span><span>{waterMetadata.observed_station_count} stations</span><span>{waterMetadata.model_forecast_count} model points</span></div>}
          </div>
        </div>
        <button className="map-home-button" type="button" title="Show regional Pakistan overview" aria-label="Show regional Pakistan overview" onClick={() => { if (mapRef.current) (rainfallHeatmapEnabled ? fitRainfallExtent : fitPakistanExtent)(mapRef.current, 350); }}><Crosshair size={15} /></button>
        <div className="map-legend">
          {rainfallHeatmapEnabled ? <>
            <strong>Rainfall / {selectedRainfallWindow.label}</strong>
            <span className="rainfall-ramp" aria-label="Rainfall accumulation in millimeters"><span><i />0.1</span><span><i />10</span><span><i />25</span><span><i />50</span><span><i />100+ mm</span></span>
          </> : <>
            <strong>Screening severity</strong><span><i className="legend-operational" /> ADM1 base</span><span><i className="legend-district" /> District</span><span><i className="legend-loc" /> LoC</span><span><i className="legend-special-boundary" /> special</span><span><i className="legend-low" /> Low</span><span><i className="legend-medium" /> Medium</span><span><i className="legend-high" /> High</span><span><i className="legend-critical" /> Critical</span><span><i className="legend-river-normal" /> Normal river</span><span><i className="legend-river-rising" /> Rising</span><span><i className="legend-river-danger" /> Flood/Danger</span><span><i className="legend-gauge" /> Gauge metadata</span><span><i className="legend-model" /> Model point</span>
          </>}
        </div>
        {selectedDistrict && <aside className="district-inspector">
          <button aria-label="Close district details" onClick={() => setSelectedDistrict(null)}><X size={17} /></button>
          <span className="inspector-eyebrow">District screening</span>
          <h3>{selectedDistrict.properties.district_name}</h3>
          <div className="district-score"><strong>{Math.round(selectedDistrict.properties.risk_probability * 100)}%</strong><StatusBadge value={selectedDistrict.properties.severity} /></div>
          <dl>
            <div><dt>Status</dt><dd>{selectedDistrict.properties.status}</dd></div>
            <div><dt>Rainfall / 24h</dt><dd>{selectedDistrict.properties.rainfall_24h_mm === undefined ? "Unavailable" : `${selectedDistrict.properties.rainfall_24h_mm.toFixed(1)} mm`}</dd></div>
            <div><dt>Forecast / 24h</dt><dd>{selectedDistrict.properties.forecast_rainfall_24h_mm === undefined ? "Unavailable" : `${selectedDistrict.properties.forecast_rainfall_24h_mm.toFixed(1)} mm`}</dd></div>
            <div><dt>Soil moisture</dt><dd>{selectedDistrict.properties.soil_moisture_percent === undefined ? "Unavailable" : `${selectedDistrict.properties.soil_moisture_percent.toFixed(1)}%`}</dd></div>
            <div><dt>Confidence</dt><dd>{Math.round(selectedDistrict.properties.confidence * 100)}%</dd></div>
          </dl>
          <p>Weather screening for national prioritization. Open a monitored station for river-aware XGBoost prediction.</p>
        </aside>}
        {selectedWaterFeature && <aside className="district-inspector water-inspector">
          <button aria-label="Close water feature details" onClick={() => setSelectedWaterFeature(null)}><X size={17} /></button>
          <span className="inspector-eyebrow">{selectedWaterKind}</span>
          <h3>{selectedWaterFeature.properties.name}</h3>
          <div className="district-score"><strong><Gauge size={24} /> {selectedWaterFeature.properties.water_system}</strong><StatusBadge value={selectedWaterFeature.properties.data_status} /></div>
          <dl>
            <div><dt>Feature type</dt><dd>{selectedWaterFeature.properties.feature_kind.replace("_", " ")}</dd></div>
            <div><dt>Telemetry</dt><dd>{selectedWaterFeature.properties.telemetry_status.replaceAll("_", " ")}</dd></div>
            <div><dt>Coordinate quality</dt><dd>{selectedWaterFeature.properties.coordinate_quality ?? selectedWaterFeature.properties.geometry_quality ?? "unmarked"}</dd></div>
            <div><dt>Geometry source</dt><dd>{selectedWaterFeature.properties.geometry_source ?? selectedWaterFeature.properties.source ?? "curated"}</dd></div>
            <div><dt>Observed level</dt><dd>{selectedWaterFeature.properties.observed_level_m == null ? "Not ingested" : `${selectedWaterFeature.properties.observed_level_m.toFixed(2)} m`}</dd></div>
            <div><dt>Observed discharge</dt><dd>{selectedWaterFeature.properties.observed_discharge_cumecs == null ? "Not ingested" : `${selectedWaterFeature.properties.observed_discharge_cumecs.toFixed(0)} cumecs`}</dd></div>
            <div><dt>Forecast value</dt><dd>{selectedWaterFeature.properties.details_endpoint ? "Available via river endpoint" : "Not applicable"}</dd></div>
          </dl>
          <p>{selectedWaterFeature.properties.description}</p>
        </aside>}
      </div>
      {selectedStationId && <RiverStationInspector stationId={selectedStationId} data={monitoring} error={monitoringError} refreshing={refreshRequested || Boolean(monitoring?.refreshing)} onRefresh={() => void refreshMonitoring()} onClose={() => setSelectedStationId(null)} onSelect={selectStation} />}
      </div>
      <footer className="map-provenance">
        <span><RadioTower size={14} /> Weather screening: Open-Meteo</span><span><CloudRain size={14} /> Rainfall heatmap: {selectedRainfallWindow.sourceLabel}</span><span><Waves size={14} /> Water: GIS features, station metadata, and modeled points are separated</span><span><Building2 size={14} /> Boundaries: Pakistan boundary adapter + OCHA/WFP ITOS LoC overlay</span><span><MessageSquareText size={14} /> Click a district or water point for evidence</span>
      </footer>
    </section>
  );
}

