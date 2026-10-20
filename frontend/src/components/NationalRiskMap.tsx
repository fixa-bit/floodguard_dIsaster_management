import { AlertTriangle, Building2, ChevronDown, ChevronUp, CloudRain, Crosshair, Dam, Database, Fence, Gauge, Layers3, LoaderCircle, MapPinned, Merge, MessageSquareText, MousePointer2, RadioTower, Waves, X } from "lucide-react";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, ImageSource, Map as MapLibreMap, MapLayerMouseEvent, MapMouseEvent, StyleSpecification } from "maplibre-gl";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { useEffect, useMemo, useRef, useState } from "react";
import { usePopulationLayers } from './usePopulationLayers';
import { useMapBasemap, type MapBasemap } from "./useMapBasemap";
import { StationTerrainStudio } from "./StationTerrainStudio";
import type { PopulationOverlay } from '../services/population';
import { bbox } from "@turf/bbox";
import { booleanPointInPolygon } from "@turf/boolean-point-in-polygon";
import type { ReactNode } from "react";
import type { Feature, FeatureCollection, Geometry, MultiPolygon, Point, Polygon } from "geojson";

import { LOCATIONS, MAP_STYLE_URL, type LocationId } from "../config";
import jammuKashmirContextRaw from "../data/pakistan/district_kashmir_outline.geojson?raw";
import previousKashmirContextRaw from "../data/pakistan/jammu_kashmir_context.geojson?raw";
import lineOfControlRaw from "../data/pakistan/line_of_control.geojson?raw";
import catchmentAreasRaw from "../data/pakistan/catchment_areas.geojson?raw";
import pakistanAdmin1Raw from "../data/pakistan/district_operational_outline.geojson?raw";
import pakistanDistrictsUrl from "../data/pakistan/pakistan_districts.geojson?compressed";
import kashmirDistrictsUrl from "../data/pakistan/kashmir_districts.geojson?compressed";
import glaciersUrl from "../data/pakistan/glaciers.geojson?compressed";
import glacierIndusBasinRaw from "../data/pakistan/glacier_indus_basin.geojson?raw";
import type { CitizenReport, DistrictRiskFeature, Incident, NationalRiskCollection, ResourceGroups, RiverResponse, RiverMonitoringResponse, SarWaterOverlay, WaterIntelligenceCollection, WaterIntelligenceFeature, WeatherResponse } from "../types/api";
import { StatusBadge } from "./StatusBadge";
import { SarWaterSummary } from "./SarWaterSummary";
import { SarValidationView } from "./SarValidationView";
import { api } from "../services/api";
import type { GoogleFloodCollection, GoogleFloodFeature, RegionalRainfallCollection } from "../types/api";
import { RiverStationInspector } from "./RiverStationInspector";
import { RiverDataSource } from "./RiverDataSource";
import { alignDistrictScreeningGeometry, districtDisplayGeometry, type DistrictBoundaries } from "./districtGeometry";
import { glacierColors, glacierConnectionLabels, glacierFilter, type GlacierCollection, type GlacierFeature, type GlacierView } from "./glaciers";
import { rainfallImageCoordinates, renderRainfallRaster } from "./rainfallRaster";
import { sourceUpdateCount, updateMapSource } from "./mapSourceUpdates";
import { loadMapAsset } from "./mapAssets";
import { scheduleMapWarmup } from "./mapWarmup";
import { coordinateMatch, indexCoordinatePolygons, lookupCoordinatePolygons, parseMapCoordinate, type CoordinateMatch, type MapCoordinate } from "./coordinateLookup";
import { clipToCatchment, correspondingStudyLayers, districtAtCoordinate, type StudyLayer } from "./studyLayers";
import { monitoringCategories, monitoringSites, type MonitoringCategory } from "./monitoringSites";
import { stationCardProperties } from "./stationInfo";
import { useStationHover, type StationInteraction } from "./useStationHover";
import { CUSECS_PER_CUMEC, flowBands, flowColor, flowInUnit, formatFlow, stationQuantity, waterQuantityOptions, type FlowUnit, type WaterQuantity } from "./waterQuantities";

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
  populationOverlay?: PopulationOverlay | null;
}

const baseStyle: StyleSpecification = {
  version: 8,
  glyphs: "https://fonts.openmaptiles.org/{fontstack}/{range}.pbf",
  sources: {
    "global-satellite-basemap": {
      type: "raster",
      tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
      tileSize: 256,
      attribution: "Imagery &copy; Esri, Maxar, Earthstar Geographics, and GIS user community",
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
  ],
};

const boundaryLinePaint: maplibregl.LineLayerSpecification["paint"] = {
  "line-color": "#034326",
  "line-width": ["interpolate", ["linear"], ["zoom"], 3, 2.6, 7, 3.2, 10, 3.8],
  "line-opacity": 1,
  "line-blur": 0,
};

// A narrow casing keeps the dark boundary legible over imagery and rainfall.
const boundaryCasingPaint: maplibregl.LineLayerSpecification["paint"] = {
  "line-color": "#e5f3e9",
  "line-width": ["interpolate", ["linear"], ["zoom"], 3, 4.4, 7, 5, 10, 5.6],
  "line-opacity": 0.85,
  "line-blur": 0,
};

const emptyCollection: FeatureCollection = { type: "FeatureCollection", features: [] };
const emptyRainfallImage = renderRainfallRaster([], emptyCollection);
const mapDiagnosticsEnabled = new URLSearchParams(window.location.search).get("mapDiagnostics") === "1";
const parseFeatureCollection = <T extends Geometry = Geometry>(raw: string) => JSON.parse(raw) as FeatureCollection<T>;
const jammuKashmirContext = parseFeatureCollection<Polygon | MultiPolygon>(jammuKashmirContextRaw);
const previousKashmirContext = parseFeatureCollection<Polygon | MultiPolygon>(previousKashmirContextRaw);
const catchmentAreas = JSON.parse(catchmentAreasRaw) as FeatureCollection<Polygon | MultiPolygon, {
  basin_id: string; name: string; area_km2: number; source: string; level: number;
}>;
const catchmentPalette = ["#38bdf8", "#a78bfa", "#22c55e", "#f97316", "#f43f5e", "#facc15", "#14b8a6"];
const catchmentMapData = { ...catchmentAreas, features: catchmentAreas.features.map((feature, index) => ({
  ...feature, properties: { ...feature.properties, map_color: catchmentPalette[index % catchmentPalette.length] },
})) };
const pakistanOperationalBase = parseFeatureCollection(pakistanAdmin1Raw);
const pakistanOverviewBounds = bbox({ type: "FeatureCollection", features: [...pakistanOperationalBase.features, ...jammuKashmirContext.features, ...previousKashmirContext.features] });
const glacierIndusBasin = parseFeatureCollection<Polygon | MultiPolygon>(glacierIndusBasinRaw);
// Shared ADM1/ADM2 vertices provide fixed checkpoints without snapping either layer.
const borderCheckpoints: FeatureCollection<Point, { number: number; name: string; district: string }> = {
  type: "FeatureCollection",
  features: [
    { type: "Feature", geometry: { type: "Point", coordinates: [61.618321999939724, 25.17613600044473] }, properties: { number: 1, name: "Gwadar", district: "Gwadar" } },
    { type: "Feature", geometry: { type: "Point", coordinates: [66.44224900011932, 30.950541000341104] }, properties: { number: 2, name: "Chaman", district: "Killa Abdullah" } },
    { type: "Feature", geometry: { type: "Point", coordinates: [74.5809550000709, 31.59423500020307] }, properties: { number: 3, name: "Lahore", district: "Lahore" } },
  ],
};
// The district asset also contains an unnamed territory-context polygon.
const namedDistrictFilter: maplibregl.FilterSpecification = ["all", ["has", "district_name"], ["!=", ["get", "district_name"], null], ["!=", ["get", "district_name"], ""]];
const pakistanLocOverlay = parseFeatureCollection(lineOfControlRaw);
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

const floodHubLegend = [
  { severity: "EXTREME", label: "Extreme", color: "#a80000" },
  { severity: "SEVERE", label: "Danger", color: "#ff3d00" },
  { severity: "ABOVE_NORMAL", label: "Warning", color: "#ff9826" },
  { severity: "UNKNOWN", label: "No data", color: "#bdbdbd" },
  { severity: "NO_FLOODING", label: "Normal", color: "#42a568" },
];
const floodHubTime = (value: string | null) => value ? new Date(value).toLocaleString() : "Unavailable";

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
  regional: RegionalRainfallCollection | null,
  coverageOverride?: FeatureCollection,
) {
  if (regional) {
    const anchors = regional.features.flatMap((feature) => {
      const value = feature.properties.accumulations_mm[windowId];
      return value == null ? [] : [{ longitude: feature.geometry.coordinates[0], latitude: feature.geometry.coordinates[1], value, weight: 1 }];
    });
    return renderRainfallRaster(anchors, coverageOverride ?? regional.coverage);
  }
  const weatherAnchors = locationWeather.flatMap((weather) => {
    const location = locationCoordinates(weather.location_id);
    return location ? [{ longitude: location.longitude, latitude: location.latitude, value: rainfallValue(weather, windowId), weight: 1.8 }] : [];
  });
  const districtAnchors = (nationalRisk?.features ?? []).flatMap((feature) => {
    const value = districtRainfallValue(feature, windowId);
    return value === null ? [] : [{ longitude: feature.properties.longitude, latitude: feature.properties.latitude, value, weight: 1 }];
  });
  return renderRainfallRaster([...weatherAnchors, ...districtAnchors], coverageOverride ?? pakistanOperationalBase);
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

function MonitoringSymbol({ category }: { category: MonitoringCategory }) {
  const Icon = { barrages: Fence, upstream: RadioTower, dams: Dam, confluences: Merge }[category];
  return <Icon className="monitoring-symbol" size={18} color="#e5eeee" aria-hidden="true" />;
}

function addWaterIcons(map: MapLibreMap) {
  for (const category of monitoringCategories) addIcon(map, `priority-${category.id}`, (context) => {
    const path = new Path2D();
    if (category.shape === "barrier") {
      path.moveTo(3, 13); path.lineTo(29, 13);
      path.moveTo(3, 22); path.lineTo(29, 22);
      for (const x of [7, 16, 25]) { path.moveTo(x, 27); path.lineTo(x, 7); path.lineTo(x + 2, 4); }
    } else if (category.shape === "tower") {
      path.moveTo(10, 28); path.lineTo(16, 13); path.lineTo(22, 28);
      path.moveTo(12, 24); path.lineTo(20, 24);
      path.moveTo(18, 10); path.arc(16, 10, 2, 0, Math.PI * 2);
      for (const radius of [6, 10]) {
        path.moveTo(16 + radius * Math.cos(-0.8), 10 + radius * Math.sin(-0.8)); path.arc(16, 10, radius, -0.8, 0.8);
        path.moveTo(16 + radius * Math.cos(Math.PI - 0.8), 10 + radius * Math.sin(Math.PI - 0.8)); path.arc(16, 10, radius, Math.PI - 0.8, Math.PI + 0.8);
      }
    } else if (category.shape === "dam") {
      path.moveTo(4, 27); path.lineTo(10, 5); path.lineTo(22, 5); path.lineTo(28, 27); path.closePath();
      for (const x of [13, 19]) { path.moveTo(x, 10); path.lineTo(x, 23); }
      path.moveTo(4, 17); path.lineTo(1, 17); path.moveTo(28, 17); path.lineTo(31, 17);
    } else {
      path.moveTo(5, 5); path.bezierCurveTo(5, 15, 16, 12, 16, 20);
      path.moveTo(27, 5); path.bezierCurveTo(27, 15, 16, 12, 16, 20); path.lineTo(16, 28);
      path.moveTo(11, 23); path.lineTo(16, 28); path.lineTo(21, 23);
    }
    context.lineCap = "round"; context.lineJoin = "round";
    context.strokeStyle = "#10282c"; context.lineWidth = 5; context.stroke(path);
    context.strokeStyle = category.color; context.lineWidth = 2.5; context.stroke(path);
  });
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
  const [west, south, east, north] = pakistanOverviewBounds;
  const mobile = map.getContainer().clientWidth < 700;
  map.fitBounds([[west, south], [east, north]], {
    padding: { top: mobile ? 240 : 190, bottom: 110, left: mobile ? 16 : 240, right: mobile ? 16 : 50 },
    maxZoom: 5,
    duration,
  });
}

function fitCoordinate(map: MapLibreMap, point: MapCoordinate, duration = 800) {
  const mobile = map.getContainer().clientWidth < 700;
  map.flyTo({ center: [point.longitude, point.latitude], zoom: 10, duration,
    padding: { top: mobile ? 220 : 190, bottom: mobile ? 280 : 110, left: mobile ? 16 : 240, right: mobile ? 16 : 330 } });
}

function normalizeWaterName(value: string | null | undefined) {
  return (value ?? "").toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function fitRainfallExtent(map: MapLibreMap, duration = 0) {
  map.resize();
  const mobile = map.getContainer().clientWidth < 700;
  map.fitBounds([[55.5, 22], [83.5, 39]], {
    padding: { top: mobile ? 240 : 190, bottom: 110, left: mobile ? 16 : 240, right: mobile ? 16 : 50 },
    maxZoom: 5,
    duration,
  });
}

function fitGlacierExtent(map: MapLibreMap, duration = 350) {
  map.resize();
  const mobile = map.getContainer().clientWidth < 700;
  map.fitBounds([[60, 23], [84, 39.5]], {
    padding: { top: mobile ? 240 : 190, bottom: 150, left: mobile ? 16 : 240, right: mobile ? 16 : 50 },
    maxZoom: 5, duration,
  });
}

function fitCatchmentExtent(map: MapLibreMap, feature: (typeof catchmentAreas.features)[number], duration = 0) {
  map.resize();
  const [west, south, east, north] = bbox(feature);
  const mobile = map.getContainer().clientWidth < 700;
  map.fitBounds([[west, south], [east, north]], {
    padding: { top: 60, bottom: mobile ? 140 : 110, left: mobile ? 20 : 240, right: 40 },
    maxZoom: 7, duration,
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

export function NationalRiskMap({ nationalRisk, waterIntelligence, locationWeather, locationRivers, incidents, reports, resources, selectedLocation, onLocationChange, expanded = false, initialRainfallEnabled = false, mapOverlay, populationOverlay }: NationalRiskMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const coordinateReadoutRef = useRef<HTMLOutputElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const [basemap, setBasemap] = useState<MapBasemap>("satellite");
  const populationOverlayRef = useRef(populationOverlay);
  populationOverlayRef.current = populationOverlay;
  const stationInteractionRef = useRef<StationInteraction | null>(null);
  const waterIntelligenceRef = useRef(waterIntelligence);
  const locationChangeRef = useRef(onLocationChange);
  const suppressDistrictFallbackRef = useRef(false);
  const [latitudeInput, setLatitudeInput] = useState("");
  const [longitudeInput, setLongitudeInput] = useState("");
  const [coordinateError, setCoordinateError] = useState<string | null>(null);
  const [coordinatePicking, setCoordinatePicking] = useState(false);
  const coordinatePickingRef = useRef(false);
  const pickedEventRef = useRef<Event | null>(null);
  const [selectedCoordinate, setSelectedCoordinate] = useState<MapCoordinate | null>(null);
  const [coordinateDetailsPoint, setCoordinateDetailsPoint] = useState<MapCoordinate | null>(null);
  const selectedCoordinateRef = useRef(selectedCoordinate);
  const coordinateNavigationRef = useRef(true);
  selectedCoordinateRef.current = selectedCoordinate;
  const [visibleCoordinateMatches, setVisibleCoordinateMatches] = useState<CoordinateMatch[]>([]);
  const [selectedDistrict, setSelectedDistrict] = useState<DistrictRiskFeature | null>(null);
  const [selectedCatchment, setSelectedCatchment] = useState<(typeof catchmentAreas.features)[number] | null>(null);
  const [selectedWaterFeature, setSelectedWaterFeature] = useState<WaterIntelligenceFeature | null>(null);
  const [selectedFloodHubFeature, setSelectedFloodHubFeature] = useState<GoogleFloodFeature | null>(null);
  const [floodHub, setFloodHub] = useState<GoogleFloodCollection | null>(null);
  const [floodHubError, setFloodHubError] = useState<string | null>(null);
  const [requestedShowNormalFloodHub, setShowNormalFloodHub] = useState(true);
  const floodHubRef = useRef(floodHub);
  floodHubRef.current = floodHub;
  const [requestedLayers, setLayers] = useState({ boundary: true, glaciers: false, borderTest: false, risk: false, districts: false, floodHub: false, catchments: false, water: false, waterForecasts: false, gauges: false, stations: false, incidents: false, reports: false, resources: false });
  const sarPickRef = useRef(false);
  const sarRequestRef = useRef(0);
  const [sarOverlay, setSarOverlay] = useState<SarWaterOverlay | null>(null);
  const [sarOverlayVisible, setSarOverlayVisible] = useState(true);
  const [sarSelection, setSarSelection] = useState("historical");
  const [sarView, setSarView] = useState<"potential" | "water" | "reference" | "errors" | "event">("potential");
  const [sarPermanentVisible, setSarPermanentVisible] = useState(true);
  const [sarEventBackground, setSarEventBackground] = useState(true);
  const [sarValidationOpen, setSarValidationOpen] = useState(false);
  const [sarBusy, setSarBusy] = useState(false);
  const [sarError, setSarError] = useState<string | null>(null);
  const [monitoringCategoriesOn, setMonitoringCategoriesOn] = useState<MonitoringCategory[]>([]);
  const [studyMonitoringHidden, setStudyMonitoringHidden] = useState<MonitoringCategory[]>([]);
  const [studyEnabled, setStudyEnabled] = useState(false);
  const [studyLayerFlags, setStudyLayerFlags] = useState<Partial<Record<StudyLayer, boolean>>>({});
  const studyActive = studyEnabled && selectedCoordinate !== null;
  const studyCatchment = useMemo(() => !studyActive || !selectedCoordinate ? null : catchmentMapData.features.find((feature) =>
    booleanPointInPolygon([selectedCoordinate.longitude, selectedCoordinate.latitude], feature)) ?? null, [studyActive, selectedCoordinate]);
  const activeStudyLayers: Partial<Record<keyof typeof requestedLayers | "rainfall", boolean>> = useMemo(() => studyActive ? studyLayerFlags : {}, [studyActive, studyLayerFlags]);
  const layers = useMemo(() => !studyActive ? requestedLayers : {
    boundary: requestedLayers.boundary, borderTest: false, districts: false, risk: false, catchments: false, glaciers: false,
    water: false, waterForecasts: false, gauges: false, floodHub: false, stations: false, incidents: false, reports: false, resources: false,
    ...activeStudyLayers,
  }, [requestedLayers, studyActive, activeStudyLayers]);
  const showNormalFloodHub = studyActive || requestedShowNormalFloodHub;
  const [kashmirBoundarySource, setKashmirBoundarySource] = useState<"districts" | "previous">("districts");
  const kashmirBoundaryData = kashmirBoundarySource === "districts" ? jammuKashmirContext : previousKashmirContext;
  const kashmirBoundaryRef = useRef(kashmirBoundaryData);
  kashmirBoundaryRef.current = kashmirBoundaryData;
  const [backgroundReady, setBackgroundReady] = useState(false);
  const [glacierData, setGlacierData] = useState<GlacierCollection | null>(null);
  const [glacierError, setGlacierError] = useState<string | null>(null);
  const [requestedGlacierView, setGlacierView] = useState<GlacierView>("all");
  const glacierView = studyActive ? "all" : requestedGlacierView;
  const [selectedGlacier, setSelectedGlacier] = useState<GlacierFeature | null>(null);
  const glacierDataRef = useRef(glacierData);
  glacierDataRef.current = glacierData;
  const glacierEnabledRef = useRef(layers.glaciers);
  glacierEnabledRef.current = layers.glaciers;
  const glacierFetchEnabled = backgroundReady || layers.glaciers;
  useEffect(() => {
    if (!glacierFetchEnabled) return;
    if (glacierData) return;
    let active = true;
    setGlacierError(null);
    void loadMapAsset<GlacierCollection>(glaciersUrl).then((data) => {
      if (!data.features?.length || !data.metadata) throw new Error("Glacier inventory is incomplete");
      if (active) setGlacierData(data);
    }).catch((error: Error) => { if (active) setGlacierError(error.message); });
    return () => { active = false; };
  }, [glacierFetchEnabled, glacierData]);
  useEffect(() => { if (!layers.glaciers) setSelectedGlacier(null); }, [layers.glaciers]);
  const floodHubFetchEnabled = backgroundReady || layers.floodHub;
  useEffect(() => {
    if (!floodHubFetchEnabled) return;
    let active = true;
    let pending = false;
    const load = async () => {
      if (pending) return;
      pending = true;
      try {
        const response = await api.googleFloodHub();
        if (active) {
          setFloodHub(response);
          setFloodHubError(null);
          setSelectedFloodHubFeature((selected) => selected ? response.features.find((feature) => feature.properties.id === selected.properties.id) ?? null : null);
        }
      } catch (error) {
        if (active) { setFloodHubError(error instanceof Error ? error.message : "Google forecasts unavailable"); setFloodHub(null); setSelectedFloodHubFeature(null); }
      } finally { pending = false; }
    };
    void load();
    const timer = window.setInterval(() => { void load(); }, 60000);
    return () => { active = false; window.clearInterval(timer); };
  }, [floodHubFetchEnabled]);
  useEffect(() => { if (!layers.floodHub) setSelectedFloodHubFeature(null); }, [layers.floodHub]);
  const [districtBoundaries, setDistrictBoundaries] = useState<DistrictBoundaries | null>(null);
  const [districtBoundaryError, setDistrictBoundaryError] = useState<string | null>(null);
  const [kashmirDistricts, setKashmirDistricts] = useState<DistrictBoundaries | null>(null);
  const [kashmirDistrictError, setKashmirDistrictError] = useState<string | null>(null);
  const districtDisplayData = useMemo(() => districtDisplayGeometry(districtBoundaries, kashmirDistricts), [districtBoundaries, kashmirDistricts]);
  const districtDisplayRef = useRef(districtDisplayData);
  districtDisplayRef.current = districtDisplayData;
  const screeningMapData = useMemo(() => alignDistrictScreeningGeometry(nationalRisk, districtBoundaries), [nationalRisk, districtBoundaries]);
  const screeningMapDataRef = useRef(screeningMapData);
  screeningMapDataRef.current = screeningMapData;

  const districtFetchEnabled = backgroundReady || layers.districts || layers.risk;
  useEffect(() => {
    if (!districtFetchEnabled) return;
    let active = true;
    void loadMapAsset<DistrictBoundaries>(pakistanDistrictsUrl).then((data) => { if (active) { setDistrictBoundaries(data); setDistrictBoundaryError(null); } }).catch(() => {
      // Original screening geometry remains available if the display asset cannot be loaded.
      if (active) setDistrictBoundaryError("District display boundaries unavailable.");
    });
    return () => { active = false; };
  }, [districtFetchEnabled]);
  useEffect(() => {
    if (!districtFetchEnabled) return;
    let active = true;
    void loadMapAsset<DistrictBoundaries>(kashmirDistrictsUrl).then((data) => {
      if (active) { setKashmirDistricts(data); setKashmirDistrictError(null); }
    }).catch(() => { if (active) setKashmirDistrictError("Kashmir district boundaries unavailable."); });
    return () => { active = false; };
  }, [districtFetchEnabled]);
  const [requestedRainfall, setRainfallHeatmapEnabled] = useState(initialRainfallEnabled);
  const rainfallHeatmapEnabled = studyActive ? Boolean(activeStudyLayers.rainfall) : requestedRainfall;
  const rainfallEnabledRef = useRef(rainfallHeatmapEnabled);
  rainfallEnabledRef.current = rainfallHeatmapEnabled;
  const [rainfallWindow, setRainfallWindow] = useState<RainfallWindowId>("last_24h");
  const [regionalRainfall, setRegionalRainfall] = useState<RegionalRainfallCollection | null>(null);
  const [rainfallError, setRainfallError] = useState<string | null>(null);

  const rainfallFetchEnabled = backgroundReady || rainfallHeatmapEnabled;
  useEffect(() => {
    if (!rainfallFetchEnabled) return;
    let active = true;
    const load = () => api.rainfall().then((response) => {
      if (active) { setRegionalRainfall(response); setRainfallError(null); }
    }).catch((error: Error) => { if (active) setRainfallError(error.message); });
    void load();
    const timer = window.setInterval(() => { void load(); }, 1800000);
    return () => { active = false; window.clearInterval(timer); };
  }, [rainfallFetchEnabled]);
  const [monitoring, setMonitoring] = useState<RiverMonitoringResponse | null>(null);
  const [monitoringError, setMonitoringError] = useState<string | null>(null);
  const [selectedStationId, setSelectedStationId] = useState<string | null>(null);
  const [requestedMonitoringRiver, setMonitoringRiver] = useState("All");
  const monitoringRiver = studyActive ? "All" : requestedMonitoringRiver;
  const [requestedCatchmentId, setCatchmentId] = useState("");
  const catchmentId = studyActive ? studyCatchment?.properties.basin_id ?? "" : requestedCatchmentId;
  const [waterQuantity, setWaterQuantity] = useState<WaterQuantity>("status");
  const [flowUnit, setFlowUnit] = useState<FlowUnit>("cumecs");
  const [requestedMinimumFlow, setMinimumFlow] = useState(0);
  const minimumFlow = studyActive ? 0 : requestedMinimumFlow;
  const [mapControlsOpen, setMapControlsOpen] = useState(() => window.innerWidth >= 700);
  const [refreshRequested, setRefreshRequested] = useState(false);
  const pollingInterval = monitoring?.refreshing || !monitoring?.stations.length ? 5000 : 60000;

  useEffect(() => {
    const mobile = window.matchMedia("(max-width: 700px)");
    const sync = () => setMapControlsOpen(!mobile.matches);
    sync();
    mobile.addEventListener("change", sync);
    return () => mobile.removeEventListener("change", sync);
  }, []);

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
    setSelectedCatchment(null);
    setSelectedWaterFeature(null);
    setSelectedFloodHubFeature(null);
    setSelectedDistrict(null);
  }

  function selectCatchment(id: string, fit = true) {
    const feature = catchmentAreas.features.find((item) => item.properties.basin_id === id) ?? null;
    setCatchmentId(id);
    setSelectedCatchment(feature);
    setSelectedDistrict(null);
    setSelectedWaterFeature(null);
    setSelectedFloodHubFeature(null);
    setSelectedStationId(null);
    setLayers((current) => ({ ...current, catchments: true }));
    if (fit && mapRef.current && feature) {
      fitCatchmentExtent(mapRef.current, feature, 350);
    } else if (fit && mapRef.current) {
      (rainfallEnabledRef.current ? fitRainfallExtent : fitPakistanExtent)(mapRef.current, 350);
    }
  }
  const selectCatchmentRef = useRef(selectCatchment);
  selectCatchmentRef.current = selectCatchment;
  const activeCatchment = catchmentAreas.features.find((item) => item.properties.basin_id === catchmentId);
  const activeCatchmentRef = useRef(activeCatchment);
  activeCatchmentRef.current = activeCatchment;
  const catchmentStations = useMemo(() => (monitoring?.stations ?? []).filter((station) =>
    !activeCatchment || booleanPointInPolygon([station.longitude, station.latitude], activeCatchment)), [monitoring, activeCatchment]);
  const quantityLabel = waterQuantityOptions.find((option) => option.id === waterQuantity)?.label ?? "Discharge";

  waterIntelligenceRef.current = waterIntelligence;
  locationChangeRef.current = onLocationChange;

  const operationalStations = useMemo(() => pointCollection(LOCATIONS.map((location) => ({
      longitude: location.longitude,
      latitude: location.latitude,
      properties: { id: location.id, name: location.name, selected: location.id === selectedLocation ? 1 : 0 },
    }))), [selectedLocation]);
  const operationalIncidents = useMemo(() => pointCollection(incidents.flatMap((incident) => {
      const location = locationCoordinates(incident.location_id);
      return location ? [{ longitude: location.longitude, latitude: location.latitude, properties: { id: incident.id, severity: incident.severity } }] : [];
    })), [incidents]);
  const operationalReports = useMemo(() => pointCollection(reports.map((report) => ({ longitude: report.longitude, latitude: report.latitude, properties: { id: report.id, status: report.verification_status } }))), [reports]);
  const operationalResources = useMemo(() => pointCollection([...resources.shelters, ...resources.hospitals, ...resources.contacts].map((resource) => ({ longitude: resource.longitude, latitude: resource.latitude, properties: { id: resource.id, type: resource.resource_type, name: resource.name } }))), [resources]);
  const operationalData = useMemo(() => ({ stations: operationalStations, incidents: operationalIncidents, reports: operationalReports, resources: operationalResources }), [operationalStations, operationalIncidents, operationalReports, operationalResources]);

  const waterGeometry = useMemo(() => {
    const features = waterIntelligence?.features ?? [];
    return {
      lines: { type: "FeatureCollection", features: features.filter((feature) => feature.geometry.type === "LineString" || feature.geometry.type === "MultiLineString") } as FeatureCollection,
      bodies: { type: "FeatureCollection", features: features.filter((feature) => feature.geometry.type === "Point" && feature.properties.data_class === "gis_feature") } as FeatureCollection<Point>,
      modelPoints: { type: "FeatureCollection", features: features.filter((feature) => feature.geometry.type === "Point" && feature.properties.data_class === "model_forecast") } as FeatureCollection<Point>,
    };
  }, [waterIntelligence]);
  const waterData = useMemo(() => {
    const features = waterIntelligence?.features ?? [];
    return {
      ...waterGeometry,
      observedStations: { type: "FeatureCollection", features: features.filter((feature) => {
        if (feature.geometry.type !== "Point" || feature.properties.data_class !== "observed_station") return false;
        if (monitoringRiver !== "All" && !monitoring?.chains[monitoringRiver]?.includes(feature.properties.monitoring_station_id ?? "")) return false;
        if (activeCatchment && !booleanPointInPolygon((feature.geometry as Point).coordinates, activeCatchment)) return false;
        const value = stationQuantity(monitoring?.stations.find((station) => station.id === feature.properties.monitoring_station_id), waterQuantity);
        return waterQuantity === "status" || minimumFlow === 0 || (value !== null && value >= minimumFlow);
      }).map((feature) => {
        const station = monitoring?.stations.find((item) => item.id === feature.properties.monitoring_station_id);
        const value = stationQuantity(station, waterQuantity);
        return { ...feature, properties: { ...feature.properties,
          flood_category: station?.flood_category ?? "Unavailable",
          selected: feature.properties.monitoring_station_id === selectedStationId ? 1 : 0,
          flow_value: value, flow_color: flowColor(value),
          flow_label: `${station?.name ?? feature.properties.name}: ${formatFlow(value, flowUnit)}`,
        } };
      }) } as FeatureCollection<Point>,
    };
  }, [waterIntelligence, waterGeometry, monitoring, monitoringRiver, selectedStationId, activeCatchment, waterQuantity, flowUnit, minimumFlow]);
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
  const [preparedRainfall, setPreparedRainfall] = useState<{
    weather: WeatherResponse[]; risk: NationalRiskCollection | null; window: RainfallWindowId;
    regional: RegionalRainfallCollection | null; data: ReturnType<typeof buildRainfallHeatmapData>;
  } | null>(null);
  useEffect(() => {
    if (!backgroundReady) return;
    return scheduleMapWarmup(() => setPreparedRainfall({ weather: locationWeather, risk: nationalRisk,
      window: rainfallWindow, regional: regionalRainfall,
      data: buildRainfallHeatmapData(locationWeather, nationalRisk, rainfallWindow, regionalRainfall) }));
  }, [backgroundReady, locationWeather, nationalRisk, rainfallWindow, regionalRainfall]);
  const rainfallHeatmapData = useMemo(() => {
    if (!studyActive && preparedRainfall?.weather === locationWeather && preparedRainfall.risk === nationalRisk
      && preparedRainfall.window === rainfallWindow && preparedRainfall.regional === regionalRainfall) return preparedRainfall.data;
    const mask = studyActive ? clipToCatchment(regionalRainfall?.coverage ?? pakistanOperationalBase, studyCatchment) : undefined;
    return rainfallHeatmapEnabled ? buildRainfallHeatmapData(locationWeather, nationalRisk, rainfallWindow, regionalRainfall, mask) : emptyRainfallImage;
  }, [preparedRainfall, rainfallHeatmapEnabled, locationWeather, nationalRisk, rainfallWindow, regionalRainfall, studyActive, studyCatchment]);
  const selectedRainfallWindow = rainfallWindowOptions.find((option) => option.id === rainfallWindow) ?? rainfallWindowOptions[0];
  const coordinateLookupEnabled = coordinateDetailsPoint !== null;
  const coordinateIndex = useMemo(() => !coordinateLookupEnabled ? [] : indexCoordinatePolygons([
    { kind: "Region", collection: pakistanOperationalBase, nameKey: "name", fields: [] },
    { kind: "Kashmir context", collection: kashmirBoundaryData, nameKey: "name", fields: [["boundary_type", "Boundary type"]] },
    { kind: "District", collection: districtDisplayData, nameKey: "district_name", fields: [["province", "Region"], ["boundary_year", "Boundary year"]] },
    { kind: "Catchment", collection: catchmentAreas, nameKey: "name", fields: [["basin_id", "Basin ID"], ["area_km2", "Area (km2)"]] },
    { kind: "Glacier", collection: glacierData ?? emptyCollection, nameKey: "name", fields: [["drainage", "Drainage"], ["connection", "Connection"], ["area_km2", "Area (km2)"]] },
  ]), [coordinateLookupEnabled, kashmirBoundaryData, districtDisplayData, glacierData]);
  const coordinateRiskIndex = useMemo(() => !coordinateLookupEnabled ? [] : indexCoordinatePolygons([
    { kind: "Screening area", collection: (screeningMapData ?? emptyCollection) as FeatureCollection, nameKey: "district_name",
      fields: [["risk_probability", "Risk"], ["severity", "Severity"], ["confidence", "Confidence"]] },
  ]), [coordinateLookupEnabled, screeningMapData]);
  const coordinateMatches = useMemo(() => !coordinateDetailsPoint ? [] : [
    ...lookupCoordinatePolygons(coordinateDetailsPoint, coordinateIndex),
    ...lookupCoordinatePolygons(coordinateDetailsPoint, coordinateRiskIndex), ...visibleCoordinateMatches,
  ], [coordinateDetailsPoint, coordinateIndex, coordinateRiskIndex, visibleCoordinateMatches]);

  const studySources = useMemo(() => {
    if (!studyActive || !selectedCoordinate) return null;
    const scope = (collection: FeatureCollection | null) => clipToCatchment(collection, studyCatchment);
    return {
      "district-display": studyCatchment ? districtAtCoordinate(selectedCoordinate, districtDisplayData) : emptyCollection,
      "district-risk": scope(districtAtCoordinate(selectedCoordinate, screeningMapData as FeatureCollection | null)),
      "catchment-areas": { type: "FeatureCollection", features: studyCatchment ? [studyCatchment] : [] } as FeatureCollection,
      "glaciers": scope(glacierData), "glacier-indus-basin": scope(glacierIndusBasin),
      "google-flood-hub": scope(floodHub),
      "water-lines": scope(waterData.lines), "river-status-lines": scope(riverStatusLines),
      "water-bodies": scope(waterData.bodies), "observed-water-stations": scope(waterData.observedStations),
      "model-water-points": scope(waterData.modelPoints),
      "stations": scope(operationalData.stations), "incidents": scope(operationalData.incidents),
      "reports": scope(operationalData.reports), "resources": scope(operationalData.resources),
    };
  }, [studyActive, selectedCoordinate, studyCatchment, districtDisplayData, screeningMapData, glacierData, floodHub,
    waterData, riverStatusLines, operationalData]);
  const studyScopeRef = useRef({ active: studyActive, catchment: studyCatchment });
  studyScopeRef.current = { active: studyActive, catchment: studyCatchment };
  const scopedMonitoringSites = useMemo(() => studyActive
    ? clipToCatchment(monitoringSites, studyCatchment) as typeof monitoringSites
    : activeCatchment ? clipToCatchment(monitoringSites, activeCatchment) as typeof monitoringSites : monitoringSites, [studyActive, studyCatchment, activeCatchment]);
  const enabledMonitoringCategories = useMemo(() => studyActive
    ? monitoringCategories.map(({ id }) => id).filter((id) => !studyMonitoringHidden.includes(id))
    : monitoringCategoriesOn, [studyActive, studyMonitoringHidden, monitoringCategoriesOn]);
  const visibleMonitoringSites = useMemo(() => ({ ...scopedMonitoringSites,
    features: scopedMonitoringSites.features.filter((feature) => enabledMonitoringCategories.includes(feature.properties.category)),
  }), [scopedMonitoringSites, enabledMonitoringCategories]);
  useEffect(() => { if (!studyActive) setStudyMonitoringHidden([]); }, [studyActive]);
  const stationGeographyIndex = useMemo(() => indexCoordinatePolygons([
    { kind: "District", collection: districtDisplayData, nameKey: "district_name", fields: [["province", "Province"]] },
    { kind: "Catchment", collection: catchmentAreas, nameKey: "name", fields: [] },
  ]), [districtDisplayData]);
  const stationPopupSources = useMemo(() => {
    const stations = new Map((monitoring?.stations ?? []).map((station) => [station.id, station]));
    const collections: Record<string, FeatureCollection> = {
      "priority-monitoring": visibleMonitoringSites,
      "observed-water-stations": studySources?.["observed-water-stations"] ?? waterData.observedStations,
      "water-bodies": studySources?.["water-bodies"] ?? waterData.bodies,
      "water-lines": studySources?.["water-lines"] ?? waterData.lines,
      "river-status-lines": studySources?.["river-status-lines"] ?? riverStatusLines,
    };
    const geographyCache = new Map<string, { basin?: string; province?: string; district?: string }>();
    return Object.fromEntries(Object.entries(collections).map(([id, collection]) => [id, { ...collection, features: collection.features.map((feature) => {
      const p = feature.properties ?? {};
      const point = feature.geometry.type === "Point" ? feature.geometry.coordinates : null;
      let geography = point ? geographyCache.get(point.join(",")) : undefined;
      if (point && !geography) {
        const matches = lookupCoordinatePolygons({ longitude: point[0], latitude: point[1] }, stationGeographyIndex);
        const district = matches.find((match) => match.kind === "District");
        geography = { district: district?.name, province: district?.fields[0]?.[1], basin: matches.find((match) => match.kind === "Catchment")?.name };
        geographyCache.set(point.join(","), geography);
      }
      return stationCardProperties(feature, stations.get(p.stationId ?? p.monitoring_station_id), monitoring?.refresh_interval_minutes ?? 60, geography);
    }) }]));
  }, [monitoring, visibleMonitoringSites, studySources, waterData, riverStatusLines, stationGeographyIndex]);

  useEffect(() => {
    if (!studySources) return;
    const flags = correspondingStudyLayers([
      { layer: "districts", collection: studySources["district-display"] },
      { layer: "risk", collection: studySources["district-risk"] },
      { layer: "catchments", collection: studySources["catchment-areas"] },
      { layer: "glaciers", collection: studySources.glaciers },
      { layer: "water", collection: studySources["water-lines"] }, { layer: "water", collection: studySources["water-bodies"] },
      { layer: "waterForecasts", collection: studySources["river-status-lines"] }, { layer: "waterForecasts", collection: studySources["model-water-points"] },
      { layer: "gauges", collection: studySources["observed-water-stations"] }, { layer: "floodHub", collection: studySources["google-flood-hub"] },
      { layer: "stations", collection: studySources.stations }, { layer: "incidents", collection: studySources.incidents },
      { layer: "reports", collection: studySources.reports }, { layer: "resources", collection: studySources.resources },
      { layer: "rainfall", collection: regionalRainfall?.features.some((feature) => Object.values(feature.properties.accumulations_mm).some((value) => value !== null))
        ? clipToCatchment(regionalRainfall.coverage, studyCatchment) : null },
      { layer: "rainfall", collection: clipToCatchment(pointCollection(locationWeather.flatMap((weather) => {
        const location = locationCoordinates(weather.location_id);
        return location ? [{ ...location, properties: {} }] : [];
      })), studyCatchment) },
    ]);
    setStudyLayerFlags((previous) => JSON.stringify(previous) === JSON.stringify(flags) ? previous : flags);
  }, [studySources, studyCatchment, regionalRainfall, locationWeather]);

  function setPickingMode(active: boolean) {
    if (!active) sarPickRef.current = false;
    if (active) stationInteractionRef.current?.close();
    coordinatePickingRef.current = active;
    if (!active && mapRef.current) mapRef.current.getCanvas().style.cursor = "";
    setCoordinatePicking(active);
    setCoordinateError(null);
    if (active) suppressDistrictFallbackRef.current = false;
    if (active && window.innerWidth < 700) setMapControlsOpen(false);
  }

  function selectCoordinate(point: MapCoordinate, navigate = true) {
    const analyzeWater = sarPickRef.current;
    stationInteractionRef.current?.close();
    coordinateNavigationRef.current = navigate;
    setPickingMode(false);
    setSelectedDistrict(null); setSelectedGlacier(null); setSelectedCatchment(null);
    setSelectedWaterFeature(null); setSelectedFloodHubFeature(null); setSelectedStationId(null);
    setCatchmentId(""); setVisibleCoordinateMatches([]); setSelectedCoordinate(point); setCoordinateDetailsPoint(point);
    if (analyzeWater) void runSarInference(point);
    if (window.innerWidth < 700) setMapControlsOpen(false);
  }
  const selectCoordinateRef = useRef(selectCoordinate);
  selectCoordinateRef.current = selectCoordinate;

  function toggleStudyLayers(active: boolean) {
    setStudyEnabled(active);
    if (!active) return;
    setSelectedDistrict(null); setSelectedGlacier(null); setSelectedCatchment(null);
    setSelectedWaterFeature(null); setSelectedFloodHubFeature(null); setSelectedStationId(null);
    setCoordinateDetailsPoint(selectedCoordinate);
  }

  function clearCoordinate(stopMoving = true) {
    if (stopMoving && selectedCoordinateRef.current) mapRef.current?.stop();
    setPickingMode(false);
    selectedCoordinateRef.current = null;
    setSelectedCoordinate(null);
    setStudyEnabled(false); setStudyLayerFlags({});
    setCoordinateDetailsPoint(null);
    setVisibleCoordinateMatches([]);
  }

  useEffect(() => {
    if (!coordinatePicking) return;
    const cancel = (event: KeyboardEvent) => { if (event.key === "Escape") setPickingMode(false); };
    window.addEventListener("keydown", cancel);
    return () => window.removeEventListener("keydown", cancel);
  }, [coordinatePicking]);

  function locateCoordinate() {
    try {
      const point = parseMapCoordinate(latitudeInput, longitudeInput);
      if (!mapRef.current?.getLayer("ndma-operational-line")) throw new Error("Map is still loading. Try again shortly.");
      selectCoordinate(point);
    } catch (error) { setCoordinateError(error instanceof Error ? error.message : "Invalid coordinates."); }
  }

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: MAP_STYLE_URL || baseStyle,
      center: [69.35, 30.45],
      zoom: expanded ? 3.45 : 3.25,
      minZoom: 0,
      maxZoom: 15,
      maxPitch: 70,
      attributionControl: false,
    });
    // A picked click must not also open an overlapping layer's feature inspector.
    const isCoordinateClick = (event: MapMouseEvent) => coordinatePickingRef.current || pickedEventRef.current === event.originalEvent;
    const isPriorityClick = (event: MapMouseEvent) => stationInteractionRef.current?.hit(event) ?? Boolean(map.getLayer("priority-monitoring-points")
      && map.queryRenderedFeatures(event.point, { layers: ["priority-monitoring-points"] }).length);
    let pendingCoordinates: MapMouseEvent | null = null;
    let coordinateFrame: number | null = null;
    const renderCoordinates = () => {
      coordinateFrame = null;
      const event = pendingCoordinates;
      const readout = coordinateReadoutRef.current;
      if (!event || !readout) return;
      readout.textContent = `Lat: ${event.lngLat.lat.toFixed(6)}  Lon: ${event.lngLat.lng.toFixed(6)}`;
      readout.hidden = false;
      readout.style.left = `${Math.max(8, Math.min(event.point.x + 14, map.getContainer().clientWidth - readout.offsetWidth - 8))}px`;
      readout.style.top = `${Math.max(8, Math.min(event.point.y + 18, map.getContainer().clientHeight - readout.offsetHeight - 8))}px`;
    };
    map.on("mousemove", (event) => {
      pendingCoordinates = event;
      if (coordinateFrame === null) coordinateFrame = requestAnimationFrame(renderCoordinates);
    });
    const hideCoordinates = () => {
      if (coordinateFrame !== null) cancelAnimationFrame(coordinateFrame);
      coordinateFrame = null;
      pendingCoordinates = null;
      if (coordinateReadoutRef.current) coordinateReadoutRef.current.hidden = true;
    };
    map.getCanvas().addEventListener("mouseleave", hideCoordinates);
    map.addControl(new maplibregl.NavigationControl({ showCompass: true, visualizePitch: true }), "top-right");
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
    let cancelWarmup = () => {};
    const warmAfterFirstPaint = () => {
      if (containerRef.current) containerRef.current.dataset.boundaryPainted = "true";
      cancelWarmup = scheduleMapWarmup(() => setBackgroundReady(true));
    };
    // Operational vectors should not wait for remote satellite tiles to finish loading.
    map.on("style.load", () => {
      const fitOverview = () => selectedCoordinateRef.current ? fitCoordinate(map, selectedCoordinateRef.current, 0)
        : (rainfallEnabledRef.current ? fitRainfallExtent : glacierEnabledRef.current ? fitGlacierExtent : fitPakistanExtent)(map, 0);
      requestAnimationFrame(fitOverview);
      window.setTimeout(() => {if(!map.getContainer().dataset.terrainStation)fitOverview();}, 250);
      addWaterIcons(map);
      map.addSource("pakistan-political-labels", { type: "geojson", data: pakistanPoliticalLabels });
      map.addSource("jammu-kashmir-context", { type: "geojson", data: kashmirBoundaryRef.current, tolerance: 0 });
      map.addLayer({ id: "jammu-kashmir-context-fill", type: "fill", source: "jammu-kashmir-context", paint: { "fill-color": "#afc0bd", "fill-opacity": 0.055 } });
      map.addSource("pakistan-operational-base", { type: "geojson", data: pakistanOperationalBase, tolerance: 0 });
      map.addLayer({
        id: "ndma-operational-fill",
        type: "fill",
        source: "pakistan-operational-base",
        paint: {
          "fill-color": "#9fb9b8",
          "fill-opacity": 0.12,
        },
      });
      map.addSource("district-risk", { type: "geojson", data: (screeningMapDataRef.current ?? emptyCollection) as FeatureCollection, tolerance: 0.25 });
      map.addSource("district-display", { type: "geojson", data: districtDisplayRef.current, tolerance: 0,
        attribution: '<a href="https://www.geoboundaries.org/">Kashmir districts: geoBoundaries / Pathways Data, 2021 / ODbL 1.0</a>' });
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
      map.addSource("catchment-areas", { type: "geojson", data: emptyCollection, attribution: '<a href="https://www.hydrosheds.org/products/hydrobasins">HydroBASINS / HydroSHEDS</a> (Lehner &amp; Grill, 2013)' });
      map.addLayer({
        id: "catchment-area-fill",
        type: "fill",
        source: "catchment-areas",
        layout: { visibility: "none" },
        paint: {
          "fill-color": ["get", "map_color"],
          "fill-opacity": 0.22,
        },
      });
      map.addLayer({
        id: "catchment-area-line",
        type: "line",
        source: "catchment-areas",
        layout: { visibility: "none" },
        paint: { "line-color": "#f8fafc", "line-width": ["interpolate", ["linear"], ["zoom"], 3, 1.15, 7, 2.1, 10, 3], "line-dasharray": [2, 2], "line-opacity": 0.86 },
      });
      map.addLayer({
        id: "catchment-area-labels",
        type: "symbol",
        source: "catchment-areas",
        minzoom: 4,
        layout: { visibility: "none", "text-field": ["get", "name"], "text-font": ["Open Sans Regular"], "text-size": 11, "text-allow-overlap": false, "text-padding": 4 },
        paint: { "text-color": "#122126", "text-halo-color": "#f8fafc", "text-halo-width": 1.3, "text-opacity": 0.9 },
      });
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
      map.addSource("google-flood-hub", {
        type: "geojson", data: floodHubRef.current ?? emptyCollection,
        attribution: '<a href="https://developers.google.com/flood-forecasting">Google Flood Forecasting</a> / <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>',
      });
      map.addLayer({
        id: "google-flood-hub-points", type: "circle", source: "google-flood-hub",
        layout: { visibility: "none" },
        paint: {
          "circle-color": ["match", ["get", "severity"], "EXTREME", "#a80000", "SEVERE", "#ff3d00", "ABOVE_NORMAL", "#ff9826", "NO_FLOODING", "#42a568", "#bdbdbd"],
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 2, 5, 6, 9, 10, 11],
          "circle-stroke-color": "#ffffff", "circle-stroke-width": 2.5, "circle-opacity": 0.96,
        },
      });
      map.addLayer({
        id: "district-boundaries-purple", type: "line", source: "district-display",
        filter: namedDistrictFilter,
        paint: { "line-color": "#c084fc", "line-width": ["interpolate", ["linear"], ["zoom"], 2, 0.9, 6, 1.5, 10, 2.3], "line-opacity": 0.95 },
      });
      for (const [id, source] of [["ndma-operational-casing", "pakistan-operational-base"], ["jammu-kashmir-context-casing", "jammu-kashmir-context"]]) {
        map.addLayer({ id, type: "line", source, layout: { "line-cap": "round", "line-join": "round" }, paint: boundaryCasingPaint });
      }
      map.addLayer({ id: "jammu-kashmir-context-line", type: "line", source: "jammu-kashmir-context", layout: { "line-cap": "round", "line-join": "round" }, paint: boundaryLinePaint });
      map.addLayer({ id: "ndma-operational-line", type: "line", source: "pakistan-operational-base", layout: { "line-cap": "round", "line-join": "round" }, paint: boundaryLinePaint });
      map.addSource("pakistan-loc-overlay", { type: "geojson", data: pakistanLocOverlay });
      map.addLayer({ id: "pakistan-loc-line", type: "line", source: "pakistan-loc-overlay", layout: { "line-cap": "round", "line-join": "round" }, paint: { ...boundaryLinePaint, "line-color": "#6faeb9" } });
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
      map.addLayer({ id: "water-quantity-labels", type: "symbol", source: "observed-water-stations", layout: {
        visibility: "none", "text-field": ["get", "flow_label"], "text-font": ["Open Sans Regular"],
        "text-size": 11, "text-anchor": "top", "text-offset": [0, 1.1], "text-allow-overlap": false,
      }, paint: { "text-color": "#ffffff", "text-halo-color": "#082126", "text-halo-width": 2 } });
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
      map.addLayer({
        id: "district-name-labels", type: "symbol", source: "district-display",
        filter: namedDistrictFilter,
        layout: { "text-field": ["get", "district_name"], "text-font": ["Open Sans Regular"], "text-size": 12,
          "text-letter-spacing": 0, "text-max-width": 9, "text-padding": 5, "text-allow-overlap": false },
        paint: { "text-color": "#f3e8ff", "text-halo-color": "#35104f", "text-halo-width": 1.5 },
      });
      map.addSource("glacier-indus-basin", { type: "geojson", data: glacierIndusBasin,
        attribution: '<a href="https://www.hydrosheds.org/products/hydrobasins">HydroBASINS / HydroSHEDS</a>' });
      map.addLayer({ id: "glacier-drainage-line", type: "line", source: "glacier-indus-basin", layout: { visibility: "none" },
        paint: { "line-color": "#ffc857", "line-width": 1.3, "line-dasharray": [3, 3], "line-opacity": 0.65 } });
      map.addSource("glaciers", { type: "geojson", data: glacierDataRef.current ?? emptyCollection, tolerance: 0.1,
        attribution: '<a href="https://rgidata.org/">RGI 7.0 / GLIMS</a> (RGI Consortium, 2023)' });
      const glacierColor: maplibregl.ExpressionSpecification = ["match", ["get", "highlight"],
        "external_contributor", glacierColors.external_contributor, "pakistan_contributor", glacierColors.pakistan_contributor,
        "divide_uncertain", glacierColors.divide_uncertain, glacierColors.other_basin];
      map.addLayer({ id: "glacier-fill", type: "fill", source: "glaciers", layout: { visibility: "none" },
        paint: { "fill-color": glacierColor, "fill-opacity": ["case", ["==", ["get", "connection"], "other_basin"], 0.45, 0.88] } });
      map.addLayer({ id: "glacier-line", type: "line", source: "glaciers", layout: { visibility: "none" },
        paint: { "line-color": glacierColor, "line-width": ["interpolate", ["linear"], ["zoom"], 3, 0.7, 8, 1.3], "line-opacity": 1 } });
      map.on("mouseenter", "glacier-fill", () => { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "glacier-fill", () => { map.getCanvas().style.cursor = ""; });
      map.on("click", "glacier-fill", (event: MapLayerMouseEvent) => {
        if (isCoordinateClick(event) || isPriorityClick(event)) return;
        if (map.queryRenderedFeatures(event.point, { layers: ["border-test-points", "google-flood-hub-points", "observed-water-stations", "water-bodies", "model-water-points"] }).length) return;
        const id = event.features?.[0]?.properties?.id;
        const glacier = glacierDataRef.current?.features.find((feature) => feature.properties.id === id) ?? null;
        if (!glacier) return;
        suppressDistrictFallbackRef.current = true;
        setSelectedGlacier(glacier);
        setSelectedDistrict(null); setSelectedCatchment(null); setSelectedWaterFeature(null); setSelectedFloodHubFeature(null); setSelectedStationId(null);
      });
      map.addLayer({
        id: "border-test-outline", type: "line", source: "pakistan-operational-base",
        paint: { "line-color": "#a855f7", "line-width": 3, "line-opacity": 1 },
      });
      map.addSource("border-test-checkpoints", { type: "geojson", data: borderCheckpoints });
      map.addLayer({
        id: "border-test-points", type: "circle", source: "border-test-checkpoints",
        paint: { "circle-color": "#ff2020", "circle-radius": 8, "circle-stroke-color": "#ffffff", "circle-stroke-width": 2 },
      });
      map.addLayer({
        id: "border-test-labels", type: "symbol", source: "border-test-checkpoints",
        layout: { "text-field": ["concat", ["to-string", ["get", "number"]], ". ", ["get", "name"]],
          "text-font": ["Open Sans Regular"], "text-size": 12, "text-anchor": "bottom", "text-offset": [0, -1.2], "text-allow-overlap": true },
        paint: { "text-color": "#ffffff", "text-halo-color": "#5b1010", "text-halo-width": 2 },
      });
      map.moveLayer("google-flood-hub-points", "border-test-outline");
      map.addSource("priority-monitoring", { type: "geojson", data: visibleMonitoringSites });
      map.addLayer({ id: "priority-monitoring-points", type: "symbol", source: "priority-monitoring",
        layout: { "icon-image": ["concat", "priority-", ["get", "category"]], "icon-size": 1.4,
          "icon-allow-overlap": true, "icon-ignore-placement": true } });
      map.addLayer({ id: "priority-monitoring-labels", type: "symbol", source: "priority-monitoring", minzoom: 7,
        layout: { "text-field": ["get", "name"], "text-size": 11, "text-font": ["Open Sans Regular"],
          "text-anchor": "top", "text-offset": [0, 1.6], "text-padding": 4, "text-max-width": 14 },
        paint: { "text-color": "#ffffff", "text-halo-color": "#07171b", "text-halo-width": 2 } });
      map.on("mouseenter", "priority-monitoring-points", () => { if (!coordinatePickingRef.current) map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "priority-monitoring-points", () => { if (!coordinatePickingRef.current) map.getCanvas().style.cursor = ""; });
      const hoverCheckpointPopup = new maplibregl.Popup({ className: "border-checkpoint-popup", closeButton: false, closeOnClick: false });
      const pinnedCheckpointPopup = new maplibregl.Popup({ className: "border-checkpoint-popup" });
      const showCheckpointPopup = (event: MapLayerMouseEvent, popup: maplibregl.Popup) => {
        const checkpoint = borderCheckpoints.features.find((feature) => feature.properties.number === event.features?.[0]?.properties?.number);
        if (!checkpoint) return;
        const [longitude, latitude] = checkpoint.geometry.coordinates;
        popup.setLngLat([longitude, latitude])
          .setText(`${checkpoint.properties.number}. ${checkpoint.properties.name} / ${checkpoint.properties.district}: Latitude ${latitude.toFixed(6)} N, Longitude ${longitude.toFixed(6)} E`)
          .addTo(map);
      };
      map.on("mouseenter", "border-test-points", (event: MapLayerMouseEvent) => {
        if (coordinatePickingRef.current) return;
        map.getCanvas().style.cursor = "pointer";
        pinnedCheckpointPopup.remove();
        showCheckpointPopup(event, hoverCheckpointPopup);
      });
      map.on("mouseleave", "border-test-points", () => {
        map.getCanvas().style.cursor = "";
        hoverCheckpointPopup.remove();
      });
      map.on("click", "border-test-points", (event: MapLayerMouseEvent) => {
        if (isCoordinateClick(event) || isPriorityClick(event)) return;
        hoverCheckpointPopup.remove();
        showCheckpointPopup(event, pinnedCheckpointPopup);
      });

      map.on("mouseenter", "district-risk-fill", () => { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "district-risk-fill", () => { map.getCanvas().style.cursor = ""; });
      const selectDistrictFeature = (districtId: unknown, point: [number, number]) => {
        const features = screeningMapDataRef.current?.features ?? [];
        const district = (districtId == null ? null : features.find((feature) => feature.properties.district_id === districtId))
          ?? features.find((feature) => booleanPointInPolygon(point, feature as Feature<Polygon | MultiPolygon>)) ?? null;
        if (!district) return false;
        setSelectedDistrict(district);
        setSelectedCatchment(null);
        setSelectedWaterFeature(null);
        setSelectedFloodHubFeature(null);
        setSelectedStationId(null);
        return true;
      };
      for (const layerId of ["google-flood-hub-points"] as const) {
        map.on("mouseenter", layerId, () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", layerId, () => { map.getCanvas().style.cursor = ""; });
        map.on("click", layerId, (event: MapLayerMouseEvent) => {
          if (isCoordinateClick(event) || isPriorityClick(event)) return;
          const id = event.features?.[0]?.properties?.id as string | undefined;
          const feature = floodHubRef.current?.features.find((item) => item.properties.id === id) ?? null;
          suppressDistrictFallbackRef.current = feature !== null;
          setSelectedFloodHubFeature(feature);
          setSelectedDistrict(null);
          setSelectedCatchment(null);
          setSelectedWaterFeature(null);
          setSelectedStationId(null);
        });
      }
      map.on("mouseenter", "catchment-area-fill", () => { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "catchment-area-fill", () => { map.getCanvas().style.cursor = ""; });
      map.on("click", "catchment-area-fill", (event: MapLayerMouseEvent) => {
        if (isCoordinateClick(event) || isPriorityClick(event)) return;
        if (map.queryRenderedFeatures(event.point, { layers: ["glacier-fill"] }).length) return;
        if (map.queryRenderedFeatures(event.point, { layers: ["google-flood-hub-points", "water-lines", "river-status-lines", "observed-water-stations", "water-quantity-labels", "water-bodies", "model-water-points"] }).length) return;
        const id = event.features?.[0]?.properties?.basin_id as string | undefined;
        if (!id) return;
        suppressDistrictFallbackRef.current = true;
        selectCatchmentRef.current(id, false);
      });
      map.on("click", (event) => {
        if (coordinatePickingRef.current) {
          pickedEventRef.current = event.originalEvent;
          const longitude = event.lngLat.wrap().lng.toFixed(6);
          const latitude = event.lngLat.lat.toFixed(6);
          setLatitudeInput(latitude); setLongitudeInput(longitude);
          hoverCheckpointPopup.remove(); pinnedCheckpointPopup.remove();
          selectCoordinateRef.current(parseMapCoordinate(latitude, longitude));
          return;
        }
        if (isCoordinateClick(event)) return;
        if (stationInteractionRef.current?.click(event)) { suppressDistrictFallbackRef.current = false; return; }
        const populationLayers = ['population-settlements','population-administrative_exposure','population-population_grid'].filter(id => map.getLayer(id));
        if (populationLayers.length && map.queryRenderedFeatures(event.point, { layers: populationLayers }).length) return;
        setCoordinateDetailsPoint(null);
        if (!map.queryRenderedFeatures(event.point, { layers: ["glacier-fill"] }).length
          || map.queryRenderedFeatures(event.point, { layers: ["border-test-points", "google-flood-hub-points", "observed-water-stations", "water-bodies", "model-water-points"] }).length) setSelectedGlacier(null);
        if (suppressDistrictFallbackRef.current) {
          suppressDistrictFallbackRef.current = false;
          return;
        }
        if (map.queryRenderedFeatures(event.point, { layers: ["border-test-points", "google-flood-hub-points", "catchment-area-fill", "observed-water-stations", "water-quantity-labels", "water-bodies", "model-water-points"] }).length) return;
        const districtHit = map.queryRenderedFeatures(event.point, { layers: ["district-risk-fill"] })[0];
        const longitude = event.lngLat.wrap().lng;
        const point: [number, number] = [longitude, event.lngLat.lat];
        const scope = studyScopeRef.current;
        if (scope.active && (!scope.catchment || !booleanPointInPolygon(point, scope.catchment))) return;
        if (selectDistrictFeature(districtHit?.properties?.district_id, point)) return;
        // Static geography remains inspectable even without a live screening feed.
        if (districtDisplayRef.current.features.some((feature) => booleanPointInPolygon(point, feature as Feature<Polygon | MultiPolygon>))) {
          const inspection = { longitude, latitude: event.lngLat.lat };
          setVisibleCoordinateMatches([]);
          setCoordinateDetailsPoint(inspection);
        }
      });
      for (const layerId of ["water-lines", "river-status-lines", "water-bodies", "observed-water-stations", "water-quantity-labels", "model-water-points"] as const) {
        map.on("mouseenter", layerId, () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", layerId, () => { map.getCanvas().style.cursor = ""; });
        map.on("click", layerId, (event: MapLayerMouseEvent) => {
          if (isCoordinateClick(event) || isPriorityClick(event)) return;
          if ((layerId === "water-lines" || layerId === "river-status-lines") && map.queryRenderedFeatures(event.point, { layers: ["glacier-fill"] }).length) return;
          if (map.queryRenderedFeatures(event.point, { layers: ["google-flood-hub-points"] }).length) return;
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
            setSelectedCatchment(null);
            setSelectedWaterFeature(null);
            setSelectedFloodHubFeature(null);
            setSelectedDistrict(null);
            return;
          }
          const id = hit?.id ?? hit?.properties?.id;
          const feature = waterIntelligenceRef.current?.features.find((item) => item.id === id) ?? null;
          suppressDistrictFallbackRef.current = feature !== null;
          setSelectedStationId(null);
          setSelectedCatchment(null);
          setSelectedWaterFeature(feature);
          setSelectedFloodHubFeature(null);
          setSelectedDistrict(null);
        });
      }
      map.on("click", "stations", (event: MapLayerMouseEvent) => {
        if (isCoordinateClick(event) || isPriorityClick(event)) return;
        if (map.queryRenderedFeatures(event.point, { layers: ["google-flood-hub-points"] }).length) return;
        const id = event.features?.[0]?.properties?.id as LocationId | undefined;
        if (id) locationChangeRef.current(id);
      });
      map.on("sourcedata", (event) => {
        if (event.sourceId === "district-risk" && event.isSourceLoaded && containerRef.current) {
          containerRef.current.dataset.districtsReady = "true";
        }
        if (event.sourceId === "rainfall-heatmap" && event.isSourceLoaded && containerRef.current) {
          containerRef.current.dataset.rainfallReady = "true";
        }
      });
      const updateDistrictClickTargets = () => {
        if (!mapDiagnosticsEnabled || !containerRef.current) return;
        containerRef.current.dataset.borderCheckpoints = JSON.stringify(borderCheckpoints.features.map((feature) => {
          const point = map.project(feature.geometry.coordinates as [number, number]);
          return { ...feature.properties, coordinates: feature.geometry.coordinates, x: point.x, y: point.y };
        }));
        containerRef.current.dataset.districtClickTargets = JSON.stringify((screeningMapDataRef.current?.features ?? [])
          .filter((feature) => ["Killa Saifullah", "Zhob"].includes(feature.properties.district_name))
          .map((feature) => {
            const point = map.project([feature.properties.longitude, feature.properties.latitude]);
            return { id: feature.properties.district_id, name: feature.properties.district_name, x: point.x, y: point.y };
          }));
      };
      map.on("moveend", updateDistrictClickTargets);
      map.on("idle", () => {
        if (!mapDiagnosticsEnabled) return;
        const sourceDistricts = map.querySourceFeatures("district-risk").length;
        const renderedDistricts = map.queryRenderedFeatures({ layers: ["district-risk-fill"] }).length;
        if (containerRef.current) {
          containerRef.current.dataset.priorityMonitoringTargets = JSON.stringify(map.queryRenderedFeatures({ layers: ["priority-monitoring-points"] }).map((feature) => {
            const point = map.project((feature.geometry as Point).coordinates as [number, number]);
            return { id: feature.properties.id, category: feature.properties.category, x: point.x, y: point.y };
          }));
          containerRef.current.dataset.mapZoom = String(map.getZoom());
          containerRef.current.dataset.sourceFeatures = String(sourceDistricts);
          containerRef.current.dataset.renderedFeatures = String(renderedDistricts);
          containerRef.current.dataset.rainfallVisibility = String(map.getLayoutProperty("rainfall-heatmap", "visibility"));
          containerRef.current.dataset.rainfallReady = String(map.isSourceLoaded("rainfall-heatmap"));
          containerRef.current.dataset.floodHubMarkers = JSON.stringify(map.queryRenderedFeatures({ layers: ["google-flood-hub-points"] })
            .filter((feature) => feature.geometry.type === "Point")
            .map((feature) => {
              const point = map.project((feature.geometry as Point).coordinates as [number, number]);
              return { id: feature.properties.id, severity: feature.properties.severity, x: point.x, y: point.y };
            }));
          containerRef.current.dataset.monitoringStations = JSON.stringify(map.queryRenderedFeatures({ layers: ["observed-water-stations"] })
            .filter((feature) => feature.properties.monitoring_station_id && feature.geometry.type === "Point")
            .map((feature) => {
              const point = map.project((feature.geometry as Point).coordinates as [number, number]);
              return { id: feature.properties.monitoring_station_id, value: feature.properties.flow_value, label: feature.properties.flow_label, x: point.x, y: point.y };
            }));
          containerRef.current.dataset.renderedCatchments = String(map.queryRenderedFeatures({ layers: ["catchment-area-fill"] }).length);
          const renderedKashmirContext = map.queryRenderedFeatures({ layers: ["jammu-kashmir-context-line"] });
          containerRef.current.dataset.renderedKashmirContext = String(renderedKashmirContext.length);
          containerRef.current.dataset.kashmirSourceTypes = JSON.stringify([...new Set(renderedKashmirContext.map((feature) => feature.properties.boundary_type))]);
          containerRef.current.dataset.boundaryPaint = JSON.stringify(["ndma-operational-line", "jammu-kashmir-context-line", "pakistan-loc-line"].map((id) => ({ id, width: map.getPaintProperty(id, "line-width"), dash: map.getPaintProperty(id, "line-dasharray") ?? null, opacity: map.getPaintProperty(id, "line-opacity") })));
          const renderedGlaciers = map.queryRenderedFeatures({ layers: ["glacier-fill"] });
          containerRef.current.dataset.renderedGlaciers = String(renderedGlaciers.length);
          containerRef.current.dataset.renderedExternalGlaciers = String(renderedGlaciers.filter((feature) => feature.properties.highlight === "external_contributor").length);
          containerRef.current.dataset.glacierClickTargets = JSON.stringify((glacierDataRef.current?.features ?? [])
            .filter((feature) => feature.properties.highlight === "external_contributor" && feature.properties.area_km2 >= 10)
            .slice(0, 8).map((feature) => {
              const point = map.project([feature.properties.longitude, feature.properties.latitude]);
              return { id: feature.properties.id, name: feature.properties.name, x: point.x, y: point.y };
            }));
          containerRef.current.dataset.renderedDistrictBoundaries = String(map.queryRenderedFeatures({ layers: ["district-boundaries-purple"] }).length);
          containerRef.current.dataset.renderedBorderCheckpoints = String(map.queryRenderedFeatures({ layers: ["border-test-points"] }).length);
          containerRef.current.dataset.borderRenderRevision = String(Number(containerRef.current.dataset.borderRenderRevision ?? 0) + 1);
          containerRef.current.dataset.districtBoundarySource = String(map.getLayer("district-boundaries-purple")?.source ?? "");
          containerRef.current.dataset.renderedUnnamedDistricts = String(map.queryRenderedFeatures({ layers: ["district-boundaries-purple"] }).filter((feature) => !feature.properties.district_name).length);
          containerRef.current.dataset.renderedDistrictNames = JSON.stringify([...new Set(map.queryRenderedFeatures({ layers: ["district-name-labels"] }).map((feature) => feature.properties.district_name))]);
          containerRef.current.dataset.renderedKashmirDistricts = String(map.queryRenderedFeatures({ layers: ["district-boundaries-purple"] }).filter((feature) => /Kashmir/.test(feature.properties.province ?? "")).length);
          containerRef.current.dataset.kashmirDistrictTargets = JSON.stringify(districtDisplayRef.current.features.filter((feature) => ["Srinagar", "Muzaffarabad", "Kathua"].includes(feature.properties?.district_name)).map((feature) => {
            const [west, south, east, north] = bbox(feature);
            const point = map.project([(west + east) / 2, (south + north) / 2]);
            return { name: feature.properties?.district_name, x: point.x, y: point.y };
          }));
          updateDistrictClickTargets();
        }
      });
    });
    map.once("style.load", () => map.once("render", warmAfterFirstPaint));
    const resizeObserver = new ResizeObserver(() => {
      if (map.getContainer().dataset.terrainStation) {map.resize();return;}
      if (selectedCoordinateRef.current) fitCoordinate(map, selectedCoordinateRef.current, 0);
      else if (populationOverlayRef.current) {
        const [w,s,e,n] = populationOverlayRef.current.summary.bounds;
        map.resize();
        map.fitBounds([[w,s],[e,n]], { padding: 35, duration: 0, maxZoom: 11 });
      }
      else if (activeCatchmentRef.current && map.getSource("catchment-areas")) fitCatchmentExtent(map, activeCatchmentRef.current);
      else if (rainfallEnabledRef.current) fitRainfallExtent(map);
      else if (glacierEnabledRef.current) fitGlacierExtent(map, 0);
      else fitPakistanExtent(map);
    });
    resizeObserver.observe(containerRef.current);
    mapRef.current = map;
    return () => { cancelWarmup(); map.off("render", warmAfterFirstPaint); resizeObserver.disconnect(); map.getCanvas().removeEventListener("mouseleave", hideCoordinates); hideCoordinates(); map.remove(); mapRef.current = null; };
  }, [expanded]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !selectedCoordinate) return;
    const marker = new maplibregl.Marker({ color: "#ef4444" }).setLngLat([selectedCoordinate.longitude, selectedCoordinate.latitude]).addTo(map);
    marker.getElement().setAttribute("aria-label", "Located coordinate");
    marker.getElement().setAttribute("role", "img");
    marker.getElement().style.pointerEvents = "none";
    if (coordinateNavigationRef.current) fitCoordinate(map, selectedCoordinate);
    return () => {
      marker.remove();
      if (containerRef.current) { delete containerRef.current.dataset.locatedCoordinate; delete containerRef.current.dataset.coordinateZoom; }
    };
  }, [selectedCoordinate, expanded]);

  useEffect(() => {
    const map = mapRef.current;
    const inspected = coordinateDetailsPoint ?? selectedCoordinate;
    if (!map || !inspected) return;
    const layerNames: Record<string, string> = { "water-lines": "Water feature", "river-status-lines": "River status",
      "priority-monitoring-points": "Priority monitoring",
      "water-bodies": "Water body", "observed-water-stations": "River monitoring", "model-water-points": "Model point",
      "google-flood-hub-points": "Google Flood Hub", stations: "Risk location", incidents: "Incident", reports: "Citizen report", resources: "Response resource" };
    const readFeatures = () => {
      if (!map.isStyleLoaded() || map.isMoving()) return;
      const point = map.project([inspected.longitude, inspected.latitude]);
      const features = map.queryRenderedFeatures([[point.x - 8, point.y - 8], [point.x + 8, point.y + 8]],
        { layers: Object.keys(layerNames).filter((id) => map.getLayer(id)) });
      const unique = new Map<string, CoordinateMatch>();
      for (const feature of features) {
        const properties = feature.properties;
        const match = coordinateMatch(`${layerNames[feature.layer.id]} (nearby)`, { ...properties,
          name: properties.name ?? properties.title ?? properties.location_name ?? properties.id }, "name",
          [["severity", "Severity"], ["flood_category", "Flood category"], ["flow_label", "Flow"], ["live_status", "Status"], ["water_system", "Water system"], ["telemetry_status", "Telemetry"]]);
        unique.set(`${match.kind}:${match.name}`, match);
      }
      const matches = [...unique.values()];
      setVisibleCoordinateMatches((previous) => JSON.stringify(previous) === JSON.stringify(matches) ? previous : matches);
      if (containerRef.current && selectedCoordinate) {
        containerRef.current.dataset.locatedCoordinate = JSON.stringify(selectedCoordinate);
        containerRef.current.dataset.coordinateZoom = String(map.getZoom());
      }
    };
    map.on("idle", readFeatures);
    readFeatures();
    return () => { map.off("idle", readFeatures); };
  }, [selectedCoordinate, coordinateDetailsPoint, expanded]);

  useEffect(() => {
    if (selectedDistrict || selectedGlacier || selectedCatchment || selectedWaterFeature || selectedFloodHubFeature || selectedStationId) setCoordinateDetailsPoint(null);
  }, [selectedDistrict, selectedGlacier, selectedCatchment, selectedWaterFeature, selectedFloodHubFeature, selectedStationId]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const update = () => {
      if (!map.getSource("priority-monitoring")) return;
      updateMapSource(map.getSource("priority-monitoring") as GeoJSONSource, stationPopupSources["priority-monitoring"]);
      for (const id of ["priority-monitoring-points", "priority-monitoring-labels"]) map.setLayerZoomRange(id, visibleMonitoringSites.features.length > 300 ? 6 : id.endsWith("labels") ? 7 : 0, 24);
      if (mapDiagnosticsEnabled && containerRef.current) containerRef.current.dataset.priorityMonitoringSites = JSON.stringify(visibleMonitoringSites);
    };
    map.on("style.load", update); update();
    return () => { map.off("style.load", update); };
  }, [visibleMonitoringSites, stationPopupSources, expanded]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const updateSources = () => {
      if (!map.getSource("rainfall-heatmap")) { map.once("style.load", updateSources); return; }
    const sourceData: Record<string, FeatureCollection> = {
      "jammu-kashmir-context": kashmirBoundaryData,
      "catchment-areas": backgroundReady || layers.catchments ? catchmentMapData : emptyCollection,
      "district-risk": (screeningMapData ?? emptyCollection) as FeatureCollection,
      "district-display": districtDisplayData,
      "google-flood-hub": floodHub ?? emptyCollection,
      "glaciers": glacierData ?? emptyCollection,
      "glacier-indus-basin": glacierIndusBasin,
      "water-lines": waterData.lines,
      "river-status-lines": riverStatusLines,
      "water-bodies": waterData.bodies,
      "observed-water-stations": waterData.observedStations,
      "model-water-points": waterData.modelPoints,
      "stations": operationalData.stations,
      "incidents": operationalData.incidents,
      "reports": operationalData.reports,
      "resources": operationalData.resources,
    };
    if (studySources) Object.assign(sourceData, studySources);
    Object.assign(sourceData, stationPopupSources);
    for (const id of ["observed-water-stations", "water-quantity-labels"]) map.setLayerZoomRange(id, sourceData["observed-water-stations"].features.length > 300 ? 6 : 0, 24);
    map.setLayerZoomRange("water-bodies", sourceData["water-bodies"].features.length > 300 ? 6 : 0, 24);
    for (const [id, data] of Object.entries(sourceData)) {
      updateMapSource(map.getSource(id) as GeoJSONSource | undefined, data);
    }
    if (containerRef.current) {
      containerRef.current.dataset.kashmirBoundarySource = kashmirBoundarySource;
      containerRef.current.dataset.districtBoundarySource = "district-display";
      containerRef.current.dataset.districtSourceFeatures = String(districtDisplayData.features.length);
      containerRef.current.dataset.districtNames = JSON.stringify([...new Set(districtDisplayData.features.map((feature) => feature.properties?.district_name))]);
      containerRef.current.dataset.unnamedDistricts = String(districtDisplayData.features.filter((feature) => !feature.properties?.district_name).length);
    }
    const rainfallSource = map.getSource("rainfall-heatmap") as ImageSource | undefined;
    const rainfallSpec = rainfallSource?.serialize();
    if (rainfallSpec?.type === "image" && rainfallSpec.url !== rainfallHeatmapData.imageUrl) rainfallSource?.updateImage({ url: rainfallHeatmapData.imageUrl });
    if (containerRef.current) containerRef.current.dataset.rainfallCells = String(rainfallHeatmapData.cellCount);
    if (containerRef.current) containerRef.current.dataset.glacierFeatures = String(glacierData?.features.length ?? 0);
    if (containerRef.current) {
      containerRef.current.dataset.floodHubFeatures = String(floodHub?.features.length ?? 0);
      containerRef.current.dataset.floodHubStatus = floodHub?.metadata.status ?? "loading";
    }
    if (mapDiagnosticsEnabled && containerRef.current) {
      containerRef.current.dataset.sourceUpdates = JSON.stringify(Object.fromEntries(Object.keys(sourceData).map((id) => [id, sourceUpdateCount(map.getSource(id) as GeoJSONSource | undefined)])));
      containerRef.current.dataset.studyCatchment = studySources ? studyCatchment?.properties.basin_id ?? "none" : "off";
      containerRef.current.dataset.studyCounts = JSON.stringify(studySources ? Object.fromEntries(Object.entries(studySources).map(([id, collection]) => [id, collection.features.length])) : {});
      containerRef.current.dataset.studyWater = JSON.stringify(studySources ? { lines: studySources["water-lines"], bodies: studySources["water-bodies"] } : null);
      containerRef.current.dataset.studyRainfallImage = studySources ? rainfallHeatmapData.imageUrl : "";
    }
    };
    updateSources();
    return () => { map.off("style.load", updateSources); };
  }, [screeningMapData, districtDisplayData, operationalData, rainfallHeatmapData, riverStatusLines, waterData, floodHub, glacierData, backgroundReady, layers.catchments, kashmirBoundaryData, kashmirBoundarySource, studySources, studyCatchment, stationPopupSources]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const updateVisibility = () => {
      if (!map.getLayer("rainfall-heatmap")) { map.once("style.load", updateVisibility); return; }
    const visibility = (visible: boolean) => visible ? "visible" : "none";
    const setFilterIfChanged = (id: string, filter: maplibregl.FilterSpecification | null) => {
      if (JSON.stringify(map.getFilter(id) ?? null) !== JSON.stringify(filter)) map.setFilter(id, filter);
    };
    const glaciersWereVisible = map.getLayoutProperty("glacier-fill", "visibility") === "visible";
    for (const id of ["glacier-fill", "glacier-line"]) {
      map.setLayoutProperty(id, "visibility", visibility(layers.glaciers));
      setFilterIfChanged(id, glacierFilter(glacierView));
    }
    map.setLayoutProperty("glacier-drainage-line", "visibility", visibility(layers.glaciers));
    if (layers.glaciers && !glaciersWereVisible && !rainfallHeatmapEnabled && !selectedCoordinateRef.current) fitGlacierExtent(map);
    if (containerRef.current) {
      containerRef.current.dataset.glacierVisibility = visibility(layers.glaciers);
      containerRef.current.dataset.glacierView = glacierView;
    }
    for (const id of ["district-risk-fill", "district-risk-line"]) map.setLayoutProperty(id, "visibility", visibility(layers.risk));
    const boundaryVisibility = visibility(layers.boundary);
    for (const id of ["jammu-kashmir-context-fill", "jammu-kashmir-context-casing", "jammu-kashmir-context-line", "pakistan-loc-line"]) map.setLayoutProperty(id, "visibility", boundaryVisibility);
    if (containerRef.current) containerRef.current.dataset.kashmirBoundaryVisibility = boundaryVisibility;
    const admin1Visibility = visibility(layers.boundary);
    map.setLayoutProperty("ndma-operational-fill", "visibility", "none");
    map.setLayoutProperty("ndma-operational-casing", "visibility", admin1Visibility);
    map.setLayoutProperty("ndma-operational-line", "visibility", admin1Visibility);
    map.setLayoutProperty("pakistan-region-labels", "visibility", visibility(!studyActive && (layers.risk || layers.districts || layers.glaciers)));
    if (containerRef.current) containerRef.current.dataset.admin1BoundaryVisibility = admin1Visibility;
    for (const id of ["district-boundaries-purple", "district-name-labels"]) map.setLayoutProperty(id, "visibility", visibility(layers.districts));
    if (containerRef.current) containerRef.current.dataset.districtBoundariesVisibility = visibility(layers.districts);
    map.setLayoutProperty("district-risk-line", "visibility", visibility(layers.risk && !layers.districts));
    if (containerRef.current) containerRef.current.dataset.screeningOutlineVisibility = visibility(layers.risk && !layers.districts);
    const rainfallWasVisible = map.getLayoutProperty("rainfall-heatmap", "visibility") === "visible";
    map.setLayoutProperty("rainfall-heatmap", "visibility", visibility(rainfallHeatmapEnabled));
    if (containerRef.current) containerRef.current.dataset.rainfallVisibility = visibility(rainfallHeatmapEnabled);
    map.setPaintProperty("district-risk-fill", "fill-opacity", rainfallHeatmapEnabled ? 0 : ["match", ["get", "severity"], "CRITICAL", 0.66, "HIGH", 0.58, "MEDIUM", 0.46, 0.18]);
    if (rainfallHeatmapEnabled && !rainfallWasVisible && !selectedCoordinateRef.current) fitRainfallExtent(map, 350);
    map.setLayoutProperty("google-flood-hub-points", "visibility", visibility(layers.floodHub));
    setFilterIfChanged("google-flood-hub-points", showNormalFloodHub ? null : ["!=", ["get", "severity"], "NO_FLOODING"]);
    for (const id of ["border-test-outline", "border-test-points", "border-test-labels"]) {
      map.setLayoutProperty(id, "visibility", visibility(layers.borderTest));
    }
    if (containerRef.current) containerRef.current.dataset.borderTestVisibility = visibility(layers.borderTest);
    for (const id of ["catchment-area-fill", "catchment-area-line", "catchment-area-labels"] as const) {
      map.setLayoutProperty(id, "visibility", visibility(layers.catchments));
      setFilterIfChanged(id, catchmentId ? ["==", ["get", "basin_id"], catchmentId] : null);
    }
    for (const id of ["water-lines-glow", "water-lines", "water-bodies"]) map.setLayoutProperty(id, "visibility", visibility(layers.water));
    for (const id of ["river-status-lines-glow", "river-status-lines", "model-water-points"]) map.setLayoutProperty(id, "visibility", visibility(layers.waterForecasts));
    if (containerRef.current) {
      containerRef.current.dataset.waterGeometryVisibility = String(map.getLayoutProperty("water-lines", "visibility"));
      containerRef.current.dataset.waterForecastVisibility = String(map.getLayoutProperty("river-status-lines", "visibility"));
    }
    map.setLayoutProperty("observed-water-stations", "visibility", visibility(layers.gauges));
    map.setLayoutProperty("water-quantity-labels", "visibility", visibility(layers.gauges && waterQuantity !== "status"));
    map.setPaintProperty("observed-water-stations", "circle-color", waterQuantity === "status"
      ? ["match", ["get", "flood_category"], "Below low", "#28d983", "Low flood", "#ffc857", "Medium flood", "#ff9b43", "High flood", "#ff4d61", "Very high flood", "#ff4d61", "Exceptionally high flood", "#ff4d61", "#38cbea"]
      : ["get", "flow_color"]);
    for (const id of ["stations", "incidents", "reports", "resources"] as const) map.setLayoutProperty(id, "visibility", visibility(layers[id]));
    };
    updateVisibility();
    return () => { map.off("style.load", updateVisibility); };
  }, [layers, rainfallHeatmapEnabled, catchmentId, waterQuantity, showNormalFloodHub, glacierView, studyActive]);

  useMapBasemap(mapRef, basemap);
  usePopulationLayers(mapRef, populationOverlay);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    let applied = false;
    const updateOverlay = () => {
      if (applied && (!sarOverlay || map.getSource("sar-water-extent"))) {
        if (mapDiagnosticsEnabled && containerRef.current && sarOverlay) {
          containerRef.current.dataset.sarOverlayReady = String(map.isSourceLoaded("sar-water-extent"));
        }
        return;
      }
      if (!map.isStyleLoaded()) return;
      for (const id of ["sar-analysis-boundary", "sar-permanent-water", "sar-water-extent", "sar-event-imagery"]) {
        if (map.getLayer(id)) map.removeLayer(id);
        if (map.getSource(id)) map.removeSource(id);
      }
      if (!sarOverlay) { applied = true; return; }
      const addRaster = (id: string, url: string, visible: boolean) => {
        map.addSource(id, { type: "image", url, coordinates: sarOverlay.coordinates });
        map.addLayer({ id, type: "raster", source: id,
          layout: { visibility: visible && sarOverlayVisible ? "visible" : "none" },
          paint: { "raster-opacity": 1, "raster-fade-duration": 0, "raster-resampling": "nearest" } });
      };
      if (sarOverlay.validation) addRaster("sar-event-imagery", sarOverlay.validation.event_image_data_url, sarEventBackground);
      const selectedImage = sarView === "water" ? sarOverlay.all_water_image_data_url
        : sarView === "reference" ? sarOverlay.validation?.reference_water_image_data_url
        : sarView === "errors" ? sarOverlay.validation?.error_image_data_url
        : sarView === "event" ? sarOverlay.validation?.event_image_data_url : sarOverlay.image_data_url;
      map.addSource("sar-water-extent", { type: "image", url: selectedImage ?? sarOverlay.image_data_url, coordinates: sarOverlay.coordinates });
      map.addLayer({ id: "sar-water-extent", type: "raster", source: "sar-water-extent",
        layout: { visibility: sarOverlayVisible ? "visible" : "none" },
        paint: { "raster-opacity": 0.9, "raster-fade-duration": 0, "raster-resampling": "nearest" } },
      map.getLayer("google-flood-hub-points") ? "google-flood-hub-points" : undefined);
      if (sarOverlay.permanent_water_image_data_url) addRaster("sar-permanent-water", sarOverlay.permanent_water_image_data_url, sarPermanentVisible);
      map.addSource("sar-analysis-boundary", { type: "geojson", data: {
        type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [[...sarOverlay.coordinates, sarOverlay.coordinates[0]]] },
      } });
      map.addLayer({ id: "sar-analysis-boundary", type: "line", source: "sar-analysis-boundary",
        layout: { visibility: sarOverlayVisible ? "visible" : "none" },
        paint: { "line-color": "#ffdf79", "line-width": 2, "line-dasharray": [3, 2] } });
      applied = true;
    };
    map.on("style.load", updateOverlay);
    map.on("idle", updateOverlay);
    if (map.isStyleLoaded()) updateOverlay();
    return () => { map.off("style.load", updateOverlay); map.off("idle", updateOverlay); };
  }, [sarOverlay, expanded, sarView, sarPermanentVisible, sarEventBackground, sarOverlayVisible]);

  async function runSarInference(point?: MapCoordinate) {
    const request = ++sarRequestRef.current;
    setSarBusy(true);
    setSarError(null);
    setSarOverlay(null);
    setSarValidationOpen(false);
    try {
      const overlay = point
        ? await api.sarWaterExtentAtLocation(point.latitude, point.longitude)
        : await api.sarWaterExample(sarSelection === "permanent" ? "permanent" : "historical");
      if (request !== sarRequestRef.current) return;
      if (overlay.response_version !== 2 || !Number.isFinite(overlay.potential_flood_area_km2)) {
        throw new Error("The backend is running an older satellite analysis version. Restart the backend, refresh this page, and select the location again.");
      }
      setSarOverlay(overlay);
      setSarView("potential");
      setSarEventBackground(true);
      setSarOverlayVisible(true);
      const longitude = overlay.coordinates.map(([lon]) => lon);
      const latitude = overlay.coordinates.map(([, lat]) => lat);
      mapRef.current?.fitBounds([[Math.min(...longitude), Math.min(...latitude)], [Math.max(...longitude), Math.max(...latitude)]],
        { padding: { left: window.innerWidth > 900 ? 300 : 45, right: 45, top: 80, bottom: 70 }, duration: 500, maxZoom: 14 });
    } catch (error) {
      if (request === sarRequestRef.current) setSarError(error instanceof Error ? error.message : "Water extent inference failed.");
    } finally {
      if (request === sarRequestRef.current) setSarBusy(false);
    }
  }
  useStationHover({ mapRef, interactionRef: stationInteractionRef, pickingRef: coordinatePickingRef,
    catchment: studyActive ? studyCatchment : activeCatchment, expanded, revision: stationPopupSources,
    onPin: (touch) => {
      setSelectedDistrict(null); setSelectedCatchment(null); setSelectedGlacier(null);
      setSelectedWaterFeature(null); setSelectedFloodHubFeature(null); setSelectedStationId(null); setCoordinateDetailsPoint(null);
      if (touch) setMapControlsOpen(false);
    }, onInspect: selectStation });

  useEffect(() => {
    if (selectedDistrict || selectedCatchment || selectedWaterFeature || selectedFloodHubFeature || selectedStationId) setSelectedGlacier(null);
  }, [selectedDistrict, selectedCatchment, selectedWaterFeature, selectedFloodHubFeature, selectedStationId]);

  const metadata = nationalRisk?.metadata;
  const waterMetadata = waterIntelligence?.metadata;
  const selectedWaterKind = selectedWaterFeature?.properties.data_class.replace("_", " ");
  const staticMapLoading = ((layers.districts || layers.risk) && !districtBoundaries && !districtBoundaryError)
    || (layers.districts && !kashmirDistricts && !kashmirDistrictError)
    || (layers.glaciers && !glacierData && !glacierError);
  return (
    <section className={`national-map-panel ${expanded ? "national-map-expanded" : ""}`}>
      <header className="map-panel-header">
        <div><span><MapPinned size={18} /></span><div><h2>Pakistan National Flood Risk &amp; Operations Map</h2><p>{metadata ? `${metadata.returned_feature_count} districts · observed ${new Date(metadata.observed_at).toLocaleString()}` : "Loading national coverage"}</p></div></div>
        <div className="map-header-meta"><StatusBadge value={metadata?.data_mode ?? "LOADING"} /><span><Database size={13} /> {metadata?.cache_status ?? "waiting"}</span></div>
      </header>
      <div className={`river-monitoring-layout ${selectedStationId || (layers.catchments && selectedCatchment) ? "has-station" : ""}`}>
      <div className="map-workspace">
        <div ref={containerRef} className={`national-map ${coordinatePicking ? "coordinate-picking" : ""}`} aria-label="Interactive Pakistan district flood risk map" aria-busy={staticMapLoading} />
        {staticMapLoading && <div className="map-loading-indicator" role="status" aria-label="Loading map layers">
          <LoaderCircle size={36} className="spinning" aria-hidden="true" />
          <span>Loading map layers...</span>
        </div>}
        <output ref={coordinateReadoutRef} className="map-coordinate-readout" aria-label="Map cursor coordinates" aria-live="off" hidden />
        {mapOverlay && <div className="map-command-overlay">{mapOverlay}</div>}
        <StationTerrainStudio mapRef={mapRef} selectedStationId={selectedStationId} onSelectStation={selectStation} onEnter={()=>{setMapControlsOpen(false);setLayers(current=>({...current,water:true}));}}/>
        <div className="map-layer-control">
          <button className="map-layer-toggle" data-tour-target="gis-map-layers-toggle" type="button" aria-label="Toggle map layers" title="Map layers" aria-expanded={mapControlsOpen} onClick={() => setMapControlsOpen((current) => !current)}><Layers3 size={14} /><span>Map layers</span>{mapControlsOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}</button>
          {coordinatePicking && <div className="coordinate-pick-status"><span role="status"><MousePointer2 size={14} /> Coordinate selection</span><button type="button" title="Cancel coordinate selection" aria-label="Cancel coordinate selection" onClick={() => setPickingMode(false)}><X size={14} /></button></div>}
          <div hidden={!mapControlsOpen}>
          <div className="map-basemap-control" role="group" aria-label="Map background">
            <strong>Map background</strong>
            <div className="map-basemap-options">
              {(["satellite", "vector"] as const).map((value) => <button key={value} type="button" aria-pressed={basemap === value} onClick={() => setBasemap(value)}>{value === "satellite" ? "Satellite" : "Vector"}</button>)}
            </div>
            <small>Vector gives rainfall colors a clearer background.</small>
          </div>
          <form className="coordinate-search" aria-label="Locate coordinates" onSubmit={(event) => { event.preventDefault(); locateCoordinate(); }}>
            <div className="coordinate-search-heading"><strong>Coordinates</strong>{(selectedCoordinate || coordinatePicking) && <button type="button" title="Deselect location" aria-label="Deselect location" onClick={() => clearCoordinate()}><X size={14} /></button>}</div>
            <div className="coordinate-inputs">
              <label><span>Latitude</span><input aria-label="Target latitude" inputMode="decimal" value={latitudeInput} placeholder="33.6844" onChange={(event) => { setLatitudeInput(event.target.value); setCoordinateError(null); }} /></label>
              <label><span>Longitude</span><input aria-label="Target longitude" inputMode="decimal" value={longitudeInput} placeholder="73.0479" onChange={(event) => { setLongitudeInput(event.target.value); setCoordinateError(null); }} /></label>
              <button type="submit" title="Locate coordinates" aria-label="Locate coordinates"><Crosshair size={16} /></button>
              <button type="button" title="Select coordinates on map" aria-label="Select coordinates on map" aria-pressed={coordinatePicking} onClick={() => setPickingMode(!coordinatePickingRef.current)}><MousePointer2 size={16} /></button>
            </div>
            {coordinateError && <span className="coordinate-error" role="alert">{coordinateError}</span>}
            {selectedCoordinate && <label className="coordinate-study-toggle"><input type="checkbox" aria-label="Enable corresponding layers" checked={studyEnabled} onChange={(event) => toggleStudyLayers(event.target.checked)} /><span>Enable corresponding layers</span></label>}
            {selectedCoordinate && studyEnabled && <small className="coordinate-study-status" role="status">{studyCatchment ? `${studyCatchment.properties.name} / ${Object.keys(activeStudyLayers).length} layers` : "No catchment covers this coordinate"}</small>}
          </form>
          <details className="operational-layer-options" data-layer-category="static" data-tour-target="gis-static-layers" open>
          <summary><strong><MapPinned size={14} /> Static layers</strong></summary>
          {([
            ["boundary", "Pakistan boundary"], ["glaciers", "Glaciers & upstream drainage"], ["borderTest", "Boundary alignment test"], ["districts", "District names & boundaries"], ["catchments", "Catchment areas"], ["water", "Rivers, lakes & dams"], ["stations", "Risk locations"],
          ] as const).map(([id, label]) => <div key={id}>
            <label data-tour-target={`gis-layer-${id}`}><input type="checkbox" checked={layers[id]} disabled={studyActive && id !== "boundary"} title={studyActive && id !== "boundary" ? "Controlled by corresponding catchment" : undefined} onChange={() => setLayers((current) => ({ ...current, [id]: !current[id] }))} /><span>{label}</span></label>
            {id === "boundary" && <>
              <label className="kashmir-boundary-source"><span>Kashmir boundary source</span><select aria-label="Kashmir boundary source" disabled={!layers.boundary} value={kashmirBoundarySource} onChange={(event) => setKashmirBoundarySource(event.target.value as "districts" | "previous")}>
                <option value="districts">District-aligned (2021)</option><option value="previous">Previous outline (Parallax)</option>
              </select></label>
              {layers.boundary && kashmirBoundarySource === "previous" && <small className="rainfall-source-note">Previous outline: district edges may differ.</small>}
            </>}
          </div>)}
          <fieldset className="priority-monitoring-controls">
            <legend>Priority monitoring points</legend>
            {monitoringCategories.map((category) => {
              const count = scopedMonitoringSites.features.filter((feature) => feature.properties.category === category.id).length;
              return <label key={category.id} data-tour-target={`gis-monitoring-${category.id}`}><input type="checkbox" aria-label={category.label} checked={enabledMonitoringCategories.includes(category.id)}
                onChange={(event) => {
                  if (studyActive) setStudyMonitoringHidden((current) => event.target.checked ? current.filter((id) => id !== category.id) : [...current, category.id]);
                  else setMonitoringCategoriesOn((current) => event.target.checked ? [...current, category.id] : current.filter((id) => id !== category.id));
                }} /><MonitoringSymbol category={category.id} />
                <span>{category.label}<small>{category.priority} / {count} points</small></span></label>;
            })}
            <small className="rainfall-source-note">{visibleMonitoringSites.features.length} / {scopedMonitoringSites.features.length} selected</small>
          </fieldset>
          {(layers.districts || layers.risk) && !districtBoundaries && <span className="rainfall-source-note" role="status">{districtBoundaryError ?? "Loading district boundaries..."}</span>}
          {layers.districts && !kashmirDistricts && <span className="rainfall-source-note" role="status">{kashmirDistrictError ?? "Loading Kashmir district boundaries..."}</span>}
          {layers.glaciers && <div className="glacier-layer-options">
            <label className="river-network-select"><span>Glaciers</span><select aria-label="Glacier coverage" disabled={studyActive} value={glacierView} onChange={(event) => { setGlacierView(event.target.value as GlacierView); setSelectedGlacier(null); }}>
              <option value="all">All regional glaciers</option><option value="contributors">Pakistan river contributors</option><option value="external">External contributors</option>
            </select></label>
            <button type="button" className="glacier-headwaters-button" aria-label="Show glacier headwaters" title="Show glacier headwaters" onClick={() => { if (mapRef.current) fitGlacierExtent(mapRef.current); }}><Crosshair size={14} /> Headwaters</button>
            <span className="rainfall-source-note" role="status">{glacierError ?? (glacierData ? `${glacierData.metadata.feature_count.toLocaleString()} outlines / ${glacierData.metadata.counts.external_contributors.toLocaleString()} external contributors` : "Loading glacier inventory...")}</span>
            <small className="rainfall-source-note">RGI 7 / inventory snapshot / area &gt;= 1 km2</small>
          </div>}
          {layers.borderTest && <div className="border-checkpoint-controls">{borderCheckpoints.features.map((feature) => <button key={feature.properties.number}
            type="button" title={`Inspect ${feature.properties.name} border checkpoint`} aria-label={`Inspect ${feature.properties.name} border checkpoint`}
            onClick={() => mapRef.current?.easeTo({ center: feature.geometry.coordinates as [number, number], zoom: 8, duration: 500,
              offset: [containerRef.current && containerRef.current.clientWidth < 700 ? 0 : 112, 40] })}>
            <Crosshair size={13} />{feature.properties.number}. {feature.properties.name}</button>)}</div>}
          <label className="river-network-select"><span>Basin</span><select aria-label="Catchment area" disabled={studyActive} value={catchmentId} onChange={(event) => selectCatchment(event.target.value)}><option value="">All catchments</option>{catchmentAreas.features.map((feature) => <option value={feature.properties.basin_id} key={feature.id}>{feature.properties.name}</option>)}</select></label>
          {layers.catchments && <span className="rainfall-source-note">HydroBASINS level 5 / {catchmentAreas.features.length} sub-basins</span>}
          </details>
          <details className="operational-layer-options" data-layer-category="dynamic" data-tour-target="gis-dynamic-layers" open>
          <summary><strong><RadioTower size={14} /> Dynamic layers</strong></summary>
          {([
            ["risk", "District screening"], ["waterForecasts", "River status & model forecasts"], ["gauges", "River monitoring"], ["floodHub", "Google Flood Hub"], ["incidents", "Incidents"], ["reports", "Citizen reports"], ["resources", "Response resources"],
          ] as const).map(([id, label]) => <label key={id} data-tour-target={`gis-layer-${id}`}><input type="checkbox" checked={layers[id]} disabled={studyActive} title={studyActive ? "Controlled by corresponding catchment" : undefined} onChange={() => setLayers((current) => ({ ...current, [id]: !current[id] }))} /><span>{label}</span></label>)}
          <details className="sar-water-control">
            <summary><strong><Waves size={14} /> Satellite water extent</strong></summary>
            <label className="sar-example-selection"><span>Suggested location</span><select aria-label="Satellite analysis location" value={sarSelection} disabled={sarBusy} onChange={(event) => { sarPickRef.current = false; setPickingMode(false); setSarSelection(event.target.value); }}>
              <option value="historical">Pakistan · 28 Jun 2017 (example)</option>
              <option value="permanent">Pakistan · permanent-water comparison</option>
              <option value="map">Recent imagery · choose on map</option>
            </select></label>
            {sarSelection !== "map" ? <>
              <small>Historical example with a visible model prediction. No imagery download needed.</small>
              <button className="sar-select-location" type="button" disabled={sarBusy} onClick={() => { sarPickRef.current = false; setPickingMode(false); void runSarInference(); }}><Waves size={14} />{sarBusy ? "Loading analysis..." : "View flood example"}</button>
            </> : <>
            <button className="sar-select-location" type="button" disabled={sarBusy} onClick={() => {
              sarPickRef.current = true;
              setPickingMode(true);
            }}><MousePointer2 size={14} />{sarBusy ? "Processing satellite imagery..." : "Select place on map"}</button>
            </>}
            {sarBusy && <small role="status">{sarSelection !== "map" ? "Loading recorded historical prediction..." : "Fetching and aligning satellite data. This may take a minute."}</small>}
            {sarError && <small role="alert">{sarError}</small>}
            {sarOverlay && <div className="sar-water-result">
              <label><input type="checkbox" checked={sarOverlayVisible} onChange={(event) => setSarOverlayVisible(event.target.checked)} /><span>Show analysis layers</span></label>
              <button type="button" title="Remove water extent overlay" aria-label="Remove water extent overlay" onClick={() => setSarOverlay(null)}><X size={14} /></button>
              <div className="sar-layer-options">
                <label><span>Display</span><select aria-label="Satellite result layer" value={sarView} onChange={event => setSarView(event.target.value as typeof sarView)}>
                  <option value="potential">Potential flooding (cyan)</option><option value="water">All predicted water (cyan)</option>
                  {sarOverlay.validation && <><option value="reference">Reference water labels (green)</option><option value="errors">Missed / false detections</option><option value="event">Event radar only</option></>}
                </select></label>
                {sarOverlay.permanent_water_image_data_url && <label><input type="checkbox" checked={sarPermanentVisible} onChange={event => setSarPermanentVisible(event.target.checked)} /><span>Permanent-water reference (blue)</span></label>}
                {sarOverlay.validation && <>
                  <label><input type="checkbox" checked={sarEventBackground} onChange={event => setSarEventBackground(event.target.checked)} /><span>Use event-date radar background</span></label>
                  <button className="sar-compare-button" type="button" onClick={() => setSarValidationOpen(true)}>Compare imagery, labels & accuracy</button>
                </>}
                {sarView === "errors" && <small>Cyan: correct water · Pink: missed water · Orange: false detection · Gray: excluded</small>}
                {sarOverlay.validation && <small>{sarEventBackground ? `Inside the box: event radar from ${sarOverlay.during_date}.` : "Context basemap may show a different date."}</small>}
              </div>
              <SarWaterSummary result={sarOverlay} />
            </div>}
          </details>
          <div className="feature-visualization-control">
            <strong><CloudRain size={14} /> Rainfall</strong>
            <label data-tour-target="gis-layer-rainfall"><input type="checkbox" checked={rainfallHeatmapEnabled} disabled={studyActive} title={studyActive ? "Controlled by corresponding catchment" : undefined} onChange={() => setRainfallHeatmapEnabled((current) => !current)} /><span>Rainfall heatmap</span></label>
            <div className="rainfall-window-grid" aria-label="Rainfall heatmap time window">
              {rainfallWindowOptions.map((option) => (
                <button key={option.id} type="button" aria-pressed={rainfallHeatmapEnabled && rainfallWindow === option.id} className={rainfallHeatmapEnabled && rainfallWindow === option.id ? "active" : ""} onClick={() => { setRainfallWindow(option.id); setRainfallHeatmapEnabled(true); }}>
                  {option.label}
                </button>
              ))}
            </div>
            <span className="rainfall-source-note">Source: <a href="https://open-meteo.com/en/docs" target="_blank" rel="noreferrer">Open-Meteo</a> / {regionalRainfall ? "Pakistan, Kashmir & upstream basins" : `Local weather interpolation / ${selectedRainfallWindow.sourceLabel}`}</span>
            {regionalRainfall && <span className="rainfall-source-note">Interpolated model rainfall / 1 degree samples</span>}
            {rainfallHeatmapEnabled && <span className="rainfall-source-note" role="status">{rainfallError ? (regionalRainfall ? "Regional refresh failed; cached data shown." : "Upstream rainfall unavailable; local data only.") : regionalRainfall ? regionalRainfall.metadata.warning ?? (regionalRainfall.metadata.cache_status === "stale" ? "Cached regional rainfall shown." : "") : "Loading upstream rainfall..."}</span>}
            {rainfallHeatmapEnabled && rainfallHeatmapData.cellCount === 0 && regionalRainfall && <span className="rainfall-source-note" role="status">{regionalRainfall.features.some((feature) => feature.properties.accumulations_mm[rainfallWindow] != null) ? "No rainfall detected for this period." : "Rainfall data unavailable for this period."}</span>}
          </div>
          <div className="water-quantity-control">
            <strong><Gauge size={14} /> Water quantity</strong>
            <label><span>Measure</span><select aria-label="Water quantity" value={waterQuantity} onChange={(event) => {
              setWaterQuantity(event.target.value as WaterQuantity);
              setLayers((current) => ({ ...current, gauges: true }));
            }}>{waterQuantityOptions.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}</select></label>
            <label><span>Units</span><select aria-label="Water quantity units" value={flowUnit} onChange={(event) => setFlowUnit(event.target.value as FlowUnit)}><option value="cumecs">m3/s (cumecs)</option><option value="cusecs">cusecs</option></select></label>
            <label><span>Minimum</span><input type="number" aria-label="Minimum discharge" min="0" step="any" disabled={studyActive || waterQuantity === "status"}
              value={Number(flowInUnit(minimumFlow, flowUnit).toFixed(3))} onChange={(event) => {
                const value = event.target.valueAsNumber;
                if (!Number.isFinite(value) || value < 0) { setMinimumFlow(0); return; }
                setMinimumFlow(flowUnit === "cusecs" ? value / CUSECS_PER_CUMEC : value);
              }} /></label>
            <span className="rainfall-source-note" role="status">{monitoring ? `${waterData.observedStations.features.length} matching stations` : monitoringError ? "Station data unavailable" : "Loading station data"}</span>
          </div>
          <label className="river-network-select"><span>River</span><select aria-label="Monitoring river" disabled={studyActive} value={monitoringRiver} onChange={(event) => setMonitoringRiver(event.target.value)}><option>All</option>{Object.keys(monitoring?.chains ?? {}).map((river) => <option key={river}>{river}</option>)}</select></label>
          <label className="river-network-select"><span>Station</span><select aria-label="Monitoring station" value={selectedStationId ?? ""} onChange={(event) => { if (event.target.value) selectStation(event.target.value); }}><option value="">Select station</option>{Object.entries(monitoring?.chains ?? {}).filter(([river]) => monitoringRiver === "All" || monitoringRiver === river).map(([river, ids]) => <optgroup key={river} label={river}>{ids.filter((id) => catchmentStations.some((station) => station.id === id)).map((id) => <option value={id} key={`${river}-${id}`}>{monitoring?.stations.find((station) => station.id === id)?.name ?? id}</option>)}</optgroup>)}</select></label>
            {layers.floodHub && <div className="floodhub-controls">
              <label><input type="checkbox" disabled={studyActive} checked={showNormalFloodHub} onChange={(event) => setShowNormalFloodHub(event.target.checked)} />Show normal conditions</label>
              <span className="rainfall-source-note" role="status">{floodHubError ?? floodHub?.metadata.message ?? (floodHub ? `${floodHub.features.length} Google river forecast points` : "Loading Google forecasts...")}</span>
              {floodHub?.metadata.fetched_at && <small>Retrieved {floodHubTime(floodHub.metadata.fetched_at)}</small>}
              {floodHub?.metadata.status === "not_configured" && <a href="https://developers.google.com/flood-forecasting#api_access" target="_blank" rel="noreferrer">Google API access</a>}
            </div>}
          </details>
          <div className="map-control-notices">
            {metadata?.data_mode === "simulation" && <div className="map-simulation-label"><AlertTriangle size={15} /><strong>SIMULATED NATIONAL LAYER</strong></div>}
            {waterMetadata?.map_notice && <div className="map-water-notice"><AlertTriangle size={14} /><span>{waterMetadata.map_notice}</span></div>}
            <details className="map-boundary-details"><summary>Map boundaries</summary><div className="map-boundary-notice"><MapPinned size={14} /><span>Pakistan operational outlines are district-derived. Kashmir outline: {kashmirBoundarySource === "districts" ? "district-aligned, 2021 geography" : "previous Parallax context outline; district edges may differ"}. Cyan LoC is a separate reference overlay. Display geometry is not an NDMA-certified boundary.</span></div></details>
            {waterMetadata && <div className="water-intelligence-summary"><Waves size={14} /><strong>Water intelligence</strong><span>{waterMetadata.water_feature_count} GIS features</span><span>{waterMetadata.observed_station_count} stations</span><span>{waterMetadata.model_forecast_count} model points</span></div>}
          </div>
          </div>
        </div>
        <button className="map-home-button" type="button" title="Show regional Pakistan overview" aria-label="Show regional Pakistan overview" onClick={() => { setPickingMode(false); setCoordinateDetailsPoint(null); setCatchmentId(""); setSelectedCatchment(null); setSelectedFloodHubFeature(null); if (mapRef.current) (rainfallHeatmapEnabled ? fitRainfallExtent : fitPakistanExtent)(mapRef.current, 350); }}><Crosshair size={15} /></button>
        <div className="map-legend">
          {monitoringCategories.filter((category) => enabledMonitoringCategories.includes(category.id) && visibleMonitoringSites.features.some((feature) => feature.properties.category === category.id)).map((category) =>
            <span key={category.id}><MonitoringSymbol category={category.id} />{category.label}</span>)}
          {rainfallHeatmapEnabled ? <>
            <strong>Rainfall / {selectedRainfallWindow.label}</strong>
            <span className="rainfall-ramp" aria-label="Rainfall accumulation in millimeters"><span><i />0.1</span><span><i />10</span><span><i />25</span><span><i />50</span><span><i />100+ mm</span></span>
          </> : <>
            {layers.boundary && <><strong>Pakistan &amp; Kashmir</strong><span><i className="legend-operational" /> Operational outline</span><span><i className="legend-special-boundary" /> Jammu &amp; Kashmir (disputed)</span><span><i className="legend-loc" /> LoC</span></>}
            {layers.risk && <><strong>Screening severity</strong><span><i className="legend-low" /> Low</span><span><i className="legend-medium" /> Medium</span><span><i className="legend-high" /> High</span><span><i className="legend-critical" /> Critical</span></>}
            {layers.waterForecasts && <><span><i className="legend-river-normal" /> Normal river</span><span><i className="legend-river-rising" /> Rising</span><span><i className="legend-river-danger" /> Flood/Danger</span><span><i className="legend-model" /> Model point</span></>}
            {layers.gauges && <span><i className="legend-gauge" /> Gauge metadata</span>}
          </>}
          {layers.catchments && <span><i className="legend-catchment" /> HydroBASINS catchments</span>}
          {layers.glaciers && <>{Object.entries(glacierColors).map(([id, color]) => <span key={id}><i style={{ background: color }} />{id === "external_contributor" ? "External glacier contributor" : id === "pakistan_contributor" ? "Pakistan glacier contributor" : id === "divide_uncertain" ? "Drainage uncertain" : "Other glacier basin"}</span>)}</>}
          {layers.floodHub && floodHubLegend.filter((item) => showNormalFloodHub || item.severity !== "NO_FLOODING").map((item) => <span key={item.severity}><i className="legend-floodhub-point" style={{ background: item.color }} />Google: {item.label}</span>)}
          {sarOverlay && sarOverlayVisible && <>
            <span><i style={{ background: sarView === "reference" ? "#45e083" : "#00cae1" }} /> {sarOverlay.is_historical_example ? "Historical: " : ""}{sarView === "reference" ? "Reference water" : sarView === "errors" ? "Detection errors" : sarView === "event" ? "Event radar" : sarView === "water" ? "All predicted water" : "Potential flooding"}</span>
            {sarPermanentVisible && sarOverlay.permanent_water_image_data_url && <span><i style={{ background: "#4c73ff" }} /> Permanent-water reference</span>}
          </>}
          {layers.districts && <span><i className="legend-district-names" /> District names &amp; boundaries</span>}
          {layers.borderTest && <><span><i style={{ background: "#ff2020" }} /> 3 border checkpoints</span><span><i className="legend-district-names" style={{ borderTopColor: "#a855f7" }} /> Pakistan / province outline</span></>}
          {layers.gauges && waterQuantity !== "status" && <div className="water-quantity-legend">
            <strong>{quantityLabel} / {flowUnit === "cusecs" ? "cusecs" : "m3/s"}</strong>
            {flowBands.map((band, index) => <span key={band.minimum}><i style={{ background: band.color }} />{flowInUnit(band.minimum, flowUnit).toLocaleString("en", { maximumFractionDigits: 0 })}{index === flowBands.length - 1 ? "+" : `-${flowInUnit(flowBands[index + 1].minimum, flowUnit).toLocaleString("en", { maximumFractionDigits: 0 })}`}</span>)}
            <span><i style={{ background: "#94a3b8" }} /> Unavailable</span>
          </div>}
        </div>
        {coordinateDetailsPoint && <aside className="district-inspector coordinate-inspector" aria-label="Coordinate details">
          <button type="button" title="Close coordinate details" aria-label="Close coordinate details" onClick={() => setCoordinateDetailsPoint(null)}><X size={17} /></button>
          <span className="inspector-eyebrow">Located coordinate</span>
          <h3>{coordinateDetailsPoint.latitude.toFixed(6)}, {coordinateDetailsPoint.longitude.toFixed(6)}</h3>
          <small>Coverage: loaded map datasets</small>
          {selectedCoordinate && selectedCoordinate.latitude === coordinateDetailsPoint.latitude && selectedCoordinate.longitude === coordinateDetailsPoint.longitude && <label className="coordinate-study-toggle"><input type="checkbox" aria-label="Enable corresponding layers" checked={studyEnabled} onChange={(event) => toggleStudyLayers(event.target.checked)} /><span>Enable corresponding layers</span></label>}
          {!districtBoundaries || !kashmirDistricts || !glacierData ? <p role="status">{districtBoundaryError || kashmirDistrictError || glacierError ? "Some map datasets are unavailable." : "Some map datasets are still loading."}</p> : null}
          {coordinateMatches.length === 0 && <p>No features found in loaded map data.</p>}
          {coordinateMatches.map((match, index) => <section className="coordinate-feature" key={`${match.kind}:${match.name}:${index}`}>
            <span>{match.kind}</span><h4>{match.name}</h4>
            {match.fields.length > 0 && <dl>{match.fields.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>}
          </section>)}
        </aside>}
        {layers.glaciers && selectedGlacier && <aside className="district-inspector glacier-inspector" aria-label="Glacier details">
          <button type="button" aria-label="Close glacier details" onClick={() => setSelectedGlacier(null)}><X size={17} /></button>
          <span className="inspector-eyebrow">Glacier inventory</span><h3>{selectedGlacier.properties.name}</h3>
          <dl>
            <div><dt>Drainage</dt><dd>{selectedGlacier.properties.drainage}</dd></div>
            <div><dt>Connection</dt><dd>{glacierConnectionLabels[selectedGlacier.properties.connection]}</dd></div>
            <div><dt>Map boundary</dt><dd>{selectedGlacier.properties.outside_pakistan_boundary ? "Outside Pakistan operational footprint" : "Inside Pakistan operational footprint"}</dd></div>
            <div><dt>Inventory area</dt><dd>{selectedGlacier.properties.area_km2.toLocaleString()} km2</dd></div>
            <div><dt>Outline date</dt><dd>{selectedGlacier.properties.source_date?.slice(0, 10) ?? "Unavailable"}</dd></div>
            <div><dt>Coordinates</dt><dd>{selectedGlacier.properties.latitude.toFixed(5)}, {selectedGlacier.properties.longitude.toFixed(5)}</dd></div>
            <div><dt>RGI ID</dt><dd>{selectedGlacier.properties.id}</dd></div>
          </dl>
          <p>Potential drainage connection from HydroBASINS; not a measured meltwater flow or flood forecast.</p>
          <small className="river-data-source"><a href="https://rgidata.org/" target="_blank" rel="noreferrer">RGI 7 / GLIMS</a> / <a href="https://www.hydrosheds.org/products/hydrobasins" target="_blank" rel="noreferrer">HydroBASINS</a></small>
        </aside>}
        {selectedDistrict && <aside className="district-inspector" aria-label="District details">
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
            {selectedDistrict.properties.display_boundary_source && <div><dt>Display boundary</dt><dd>{selectedDistrict.properties.display_boundary_source}</dd></div>}
          </dl>
          <p>Weather screening for national prioritization. Open a monitored station for river-aware XGBoost prediction.</p>
          <small className="river-data-source">Source: <a href="https://open-meteo.com/en/docs" target="_blank" rel="noreferrer">Open-Meteo weather</a> / local risk model</small>
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
        {layers.floodHub && selectedFloodHubFeature && <aside className="district-inspector floodhub-inspector">
          <button aria-label="Close Flood Hub details" onClick={() => setSelectedFloodHubFeature(null)}><X size={17} /></button>
          <span className="inspector-eyebrow">Google riverine flood forecast</span>
          <h3>{selectedFloodHubFeature.properties.name}</h3>
          <div className="district-score"><strong><Waves size={22} /> {selectedFloodHubFeature.properties.river}</strong><span className="floodhub-severity"><i style={{ background: floodHubLegend.find((item) => item.severity === selectedFloodHubFeature.properties.severity)?.color }} />{selectedFloodHubFeature.properties.severity_label}</span></div>
          <dl>
            <div><dt>Issued</dt><dd>{floodHubTime(selectedFloodHubFeature.properties.issued_at)}</dd></div>
            <div><dt>Forecast from</dt><dd>{floodHubTime(selectedFloodHubFeature.properties.forecast_start)}</dd></div>
            <div><dt>Forecast until</dt><dd>{floodHubTime(selectedFloodHubFeature.properties.forecast_end)}</dd></div>
            <div><dt>Trend</dt><dd>{selectedFloodHubFeature.properties.trend === "FORECAST_TREND_UNSPECIFIED" ? "Unavailable" : selectedFloodHubFeature.properties.trend.replaceAll("_", " ")}</dd></div>
            <div><dt>Gauge source</dt><dd>{selectedFloodHubFeature.properties.source}</dd></div>
            <div><dt>Data status</dt><dd>{floodHub?.metadata.status === "stale" ? "Last retrieved forecasts" : "Latest retrieved forecasts"}</dd></div>
          </dl>
          {floodHub?.metadata.status === "stale" && <p>{floodHub.metadata.message}</p>}
          <small className="river-data-source">Source: <a href={selectedFloodHubFeature.properties.source_url} target="_blank" rel="noreferrer">Google Flood Hub</a> / <a href="https://developers.google.com/flood-forecasting" target="_blank" rel="noreferrer">Flood Forecasting API</a></small>
        </aside>}
      </div>
      {layers.catchments && selectedCatchment && <aside className="river-station-inspector catchment-inspector" aria-label="Catchment details">
        <header><div><span>HydroBASINS catchment</span><h3>{selectedCatchment.properties.name}</h3></div><button type="button" title="Close catchment details" aria-label="Close catchment details" onClick={() => setSelectedCatchment(null)}><X size={17} /></button></header>
        <dl className="river-station-stats">
          <div><dt>Approximate area</dt><dd>{selectedCatchment.properties.area_km2.toLocaleString("en")} km2</dd></div>
          <div><dt>Monitored stations inside</dt><dd>{monitoring ? catchmentStations.length : "Unavailable"}</dd></div>
        </dl>
        <h4>{waterQuantity === "status" ? "Current discharge" : quantityLabel}</h4>
        {catchmentStations.map((station) => <div className="catchment-station-reading" key={station.id}>
          <button type="button" onClick={() => selectStation(station.id)}>{station.name} / {station.river}</button>
          <strong>{formatFlow(stationQuantity(station, waterQuantity === "status" ? "current" : waterQuantity), flowUnit)}</strong>
          <RiverDataSource source={waterQuantity === "status" || waterQuantity === "current" ? station.current_source : "GloFAS modeled forecast"} station={station} />
        </div>)}
        {!catchmentStations.length && <p>{monitoring ? "No monitored stations inside this sub-basin." : "Station data unavailable."}</p>}
        <p>Station flows are point readings. Catchment water volume is unavailable.</p>
        <p>HydroBASINS level 5; full transboundary sub-basin, simplified for display.</p>
        <footer><a href="https://www.hydrosheds.org/products/hydrobasins" target="_blank" rel="noreferrer">HydroBASINS / HydroSHEDS</a></footer>
      </aside>}
      {selectedStationId && <RiverStationInspector stationId={selectedStationId} data={monitoring} error={monitoringError} refreshing={refreshRequested || Boolean(monitoring?.refreshing)} onRefresh={() => void refreshMonitoring()} onClose={() => setSelectedStationId(null)} onSelect={selectStation} flowUnit={flowUnit} />}
      </div>
      {sarValidationOpen && sarOverlay?.validation && <SarValidationView result={sarOverlay} onClose={() => setSarValidationOpen(false)} />}
      <footer className="map-provenance">
        <span><RadioTower size={14} /> Weather screening: Open-Meteo</span><span><CloudRain size={14} /> Rainfall heatmap: {selectedRainfallWindow.sourceLabel}</span><span><Waves size={14} /> Google Flood Forecasting / CC BY 4.0</span><span><Waves size={14} /> Water: GIS features, station metadata, and modeled points are separated</span><span><Building2 size={14} /> Boundaries: Pakistan boundary adapter + OCHA/WFP ITOS LoC overlay</span><span><MessageSquareText size={14} /> Click a district or water point for evidence</span>
      </footer>
    </section>
  );
}
