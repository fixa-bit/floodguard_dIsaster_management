import { AlertTriangle, Building2, Crosshair, Database, Gauge, Layers3, MapPinned, MessageSquareText, RadioTower, Waves, X } from "lucide-react";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map as MapLibreMap, MapLayerMouseEvent, StyleSpecification } from "maplibre-gl";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { useEffect, useMemo, useRef, useState } from "react";
import type { FeatureCollection, Point, Polygon } from "geojson";

import { LOCATIONS, MAP_STYLE_URL, type LocationId } from "../config";
import type { CitizenReport, DistrictRiskFeature, Incident, NationalRiskCollection, ResourceGroups, WaterIntelligenceCollection, WaterIntelligenceFeature } from "../types/api";
import { StatusBadge } from "./StatusBadge";

maplibregl.setWorkerUrl(maplibreWorkerUrl);

interface NationalRiskMapProps {
  nationalRisk: NationalRiskCollection | null;
  waterIntelligence: WaterIntelligenceCollection | null;
  incidents: Incident[];
  reports: CitizenReport[];
  resources: ResourceGroups;
  selectedLocation: LocationId;
  onLocationChange: (location: LocationId) => void;
  expanded?: boolean;
}

const baseStyle: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "background", type: "background", paint: { "background-color": "#edf2f0" } }],
};

const emptyCollection: FeatureCollection = { type: "FeatureCollection", features: [] };
const pakistanFitBounds: [[number, number], [number, number]] = [[59.4, 20.5], [81.2, 38.7]];
const pakistanMaxBounds: [[number, number], [number, number]] = [[54.0, 17.5], [85.5, 41.5]];
const pakistanFitPadding = { top: 30, right: 38, bottom: 56, left: 38 };
const ndmaOperationalExtent: FeatureCollection<Polygon> = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      id: "ndma_operational_jammu_kashmir",
      geometry: {
        type: "Polygon",
        coordinates: [[
          [73.45, 32.58],
          [74.18, 32.82],
          [74.95, 32.52],
          [75.78, 32.72],
          [76.86, 33.18],
          [78.18, 33.2],
          [79.36, 33.86],
          [80.48, 34.64],
          [80.36, 35.3],
          [79.45, 35.72],
          [78.64, 36.24],
          [78.16, 37.02],
          [76.86, 37.28],
          [75.6, 36.78],
          [74.72, 35.82],
          [73.92, 34.7],
          [73.48, 33.56],
          [73.45, 32.58],
        ]],
      },
      properties: {
        name: "Jammu & Kashmir operational extent",
        source: "NDMA operational display overlay",
        note: "Displayed as part of Pakistan operational map context where district-level risk coverage is incomplete.",
      },
    },
  ],
};
const pakistanPoliticalBase: FeatureCollection<Polygon> = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      id: "base_balochistan",
      geometry: { type: "Polygon", coordinates: [[[60.55, 24.1], [61.0, 28.4], [62.8, 30.5], [65.1, 31.2], [67.5, 30.1], [68.9, 28.4], [68.2, 26.0], [66.7, 24.0], [64.5, 23.35], [61.8, 24.0], [60.55, 24.1]]] },
      properties: { name: "Balochistan", color: "#f3d58a" },
    },
    {
      type: "Feature",
      id: "base_sindh",
      geometry: { type: "Polygon", coordinates: [[[66.6, 23.35], [68.2, 24.0], [69.4, 25.7], [69.0, 27.9], [68.1, 28.7], [67.4, 27.8], [67.0, 26.1], [66.4, 24.6], [66.6, 23.35]]] },
      properties: { name: "Sindh", color: "#d7c9e9" },
    },
    {
      type: "Feature",
      id: "base_punjab",
      geometry: { type: "Polygon", coordinates: [[[69.0, 27.9], [71.2, 28.4], [73.2, 29.2], [74.8, 30.2], [75.6, 31.6], [74.9, 32.8], [73.5, 33.0], [71.9, 32.3], [70.7, 31.2], [69.6, 29.8], [69.0, 27.9]]] },
      properties: { name: "Punjab", color: "#f4cdbf" },
    },
    {
      type: "Feature",
      id: "base_khyber_pakhtunkhwa",
      geometry: { type: "Polygon", coordinates: [[[69.2, 31.0], [70.8, 32.0], [71.7, 33.0], [72.6, 34.0], [73.8, 35.0], [74.3, 36.0], [73.2, 36.8], [71.3, 36.2], [70.0, 35.0], [69.0, 33.5], [68.6, 32.2], [69.2, 31.0]]] },
      properties: { name: "Khyber Pakhtunkhwa", color: "#f0b8ad" },
    },
    {
      type: "Feature",
      id: "base_gilgit_baltistan",
      geometry: { type: "Polygon", coordinates: [[[73.2, 35.2], [74.0, 36.0], [75.3, 36.8], [76.8, 37.5], [78.2, 37.1], [79.1, 36.4], [78.8, 35.4], [77.5, 35.1], [76.2, 35.3], [74.8, 35.0], [73.2, 35.2]]] },
      properties: { name: "Gilgit-Baltistan", color: "#dbeebf" },
    },
    {
      type: "Feature",
      id: "base_ajk",
      geometry: { type: "Polygon", coordinates: [[[73.6, 33.1], [74.5, 33.4], [75.0, 34.0], [74.8, 34.9], [73.8, 34.8], [73.2, 34.2], [73.2, 33.5], [73.6, 33.1]]] },
      properties: { name: "Azad Jammu & Kashmir", color: "#dcefd9" },
    },
    {
      type: "Feature",
      id: "base_jammu_kashmir",
      geometry: ndmaOperationalExtent.features[0].geometry,
      properties: { name: "Jammu and Kashmir", color: "#dff1e7" },
    },
  ],
};
const pakistanPoliticalLabels: FeatureCollection<Point> = {
  type: "FeatureCollection",
  features: [
    { type: "Feature", geometry: { type: "Point", coordinates: [64.6, 27.9] }, properties: { name: "BALOCHISTAN" } },
    { type: "Feature", geometry: { type: "Point", coordinates: [67.8, 25.7] }, properties: { name: "SINDH" } },
    { type: "Feature", geometry: { type: "Point", coordinates: [72.8, 30.7] }, properties: { name: "PUNJAB" } },
    { type: "Feature", geometry: { type: "Point", coordinates: [71.8, 34.2] }, properties: { name: "KHYBER PAKHTUNKHWA" } },
    { type: "Feature", geometry: { type: "Point", coordinates: [76.6, 36.2] }, properties: { name: "GILGIT-BALTISTAN" } },
    { type: "Feature", geometry: { type: "Point", coordinates: [74.2, 34.2] }, properties: { name: "AJ&K" } },
    { type: "Feature", geometry: { type: "Point", coordinates: [77.6, 34.4] }, properties: { name: "JAMMU & KASHMIR" } },
    { type: "Feature", geometry: { type: "Point", coordinates: [64.0, 33.5] }, properties: { name: "AFGHANISTAN" } },
    { type: "Feature", geometry: { type: "Point", coordinates: [60.6, 27.2] }, properties: { name: "IRAN" } },
    { type: "Feature", geometry: { type: "Point", coordinates: [78.2, 30.4] }, properties: { name: "INDIA" } },
    { type: "Feature", geometry: { type: "Point", coordinates: [78.2, 38.0] }, properties: { name: "CHINA" } },
    { type: "Feature", geometry: { type: "Point", coordinates: [64.2, 22.3] }, properties: { name: "ARABIAN SEA" } },
  ],
};

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
    context.fillStyle = "#2b8fbf";
    context.strokeStyle = "#e7f6fb";
    context.lineWidth = 3;
    context.beginPath();
    context.arc(16, 16, 7, 0, Math.PI * 2);
    context.fill();
    context.stroke();
  });
  addIcon(map, "dam-icon", (context) => {
    context.fillStyle = "#185f80";
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
    context.fillStyle = "#ffffff";
    context.strokeStyle = "#0f5d86";
    context.lineWidth = 5;
    context.beginPath();
    context.arc(16, 16, 9, 0, Math.PI * 2);
    context.fill();
    context.stroke();
  });
  addIcon(map, "model-diamond", (context) => {
    context.fillStyle = "#4d6f8f";
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
  map.fitBounds(pakistanFitBounds, { padding: pakistanFitPadding, duration });
}

export function NationalRiskMap({ nationalRisk, waterIntelligence, incidents, reports, resources, selectedLocation, onLocationChange, expanded = false }: NationalRiskMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const nationalRiskRef = useRef(nationalRisk);
  const waterIntelligenceRef = useRef(waterIntelligence);
  const locationChangeRef = useRef(onLocationChange);
  const [selectedDistrict, setSelectedDistrict] = useState<DistrictRiskFeature | null>(null);
  const [selectedWaterFeature, setSelectedWaterFeature] = useState<WaterIntelligenceFeature | null>(null);
  const [layers, setLayers] = useState({ risk: true, water: true, stations: true, incidents: true, reports: true, resources: true });

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
      observedStations: { type: "FeatureCollection", features: features.filter((feature) => feature.geometry.type === "Point" && feature.properties.data_class === "observed_station") } as FeatureCollection<Point>,
      modelPoints: { type: "FeatureCollection", features: features.filter((feature) => feature.geometry.type === "Point" && feature.properties.data_class === "model_forecast") } as FeatureCollection<Point>,
    };
  }, [waterIntelligence]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: MAP_STYLE_URL || baseStyle,
      center: [69.35, 30.45],
      zoom: expanded ? 3.45 : 3.25,
      minZoom: 2.35,
      maxZoom: 12,
      maxBounds: pakistanMaxBounds,
      attributionControl: false,
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
    map.on("load", () => {
      requestAnimationFrame(() => fitPakistanExtent(map));
      window.setTimeout(() => fitPakistanExtent(map), 250);
      addWaterIcons(map);
      map.addSource("pakistan-political-base", { type: "geojson", data: pakistanPoliticalBase });
      map.addSource("pakistan-political-labels", { type: "geojson", data: pakistanPoliticalLabels });
      map.addLayer({ id: "arabian-sea-base", type: "background", paint: { "background-color": "#d7eef5" } });
      map.addLayer({ id: "pakistan-region-fill", type: "fill", source: "pakistan-political-base", paint: { "fill-color": ["get", "color"], "fill-opacity": 0.96 } });
      map.addLayer({ id: "pakistan-region-line", type: "line", source: "pakistan-political-base", paint: { "line-color": "#18815f", "line-width": ["interpolate", ["linear"], ["zoom"], 3, 1.4, 7, 2.4, 10, 3.4], "line-opacity": 0.9 } });
      map.addSource("ndma-operational-extent", { type: "geojson", data: ndmaOperationalExtent });
      map.addLayer({ id: "ndma-operational-fill", type: "fill", source: "ndma-operational-extent", paint: { "fill-color": "#dff1e7", "fill-opacity": 0.58 } });
      map.addLayer({ id: "ndma-operational-line", type: "line", source: "ndma-operational-extent", paint: { "line-color": "#0d4f55", "line-width": ["interpolate", ["linear"], ["zoom"], 3, 1.6, 7, 2.8, 10, 4], "line-opacity": 0.92 } });
      map.addSource("district-risk", { type: "geojson", data: (nationalRiskRef.current ?? emptyCollection) as FeatureCollection });
      map.addLayer({
        id: "district-risk-fill",
        type: "fill",
        source: "district-risk",
        paint: {
          "fill-color": ["match", ["get", "severity"], "CRITICAL", "#c83b44", "HIGH", "#df6b2f", "MEDIUM", "#d29a2e", "#4e9870"],
          "fill-opacity": 0.38,
        },
      });
      map.addLayer({ id: "district-risk-line", type: "line", source: "district-risk", paint: { "line-color": "#ffffff", "line-width": 0.8, "line-opacity": 0.85 } });
      map.addLayer({ id: "pakistan-operational-outline", type: "line", source: "district-risk", paint: { "line-color": "#0d4f55", "line-width": ["interpolate", ["linear"], ["zoom"], 3, 1.2, 7, 2.2, 10, 3.4], "line-opacity": 0.68 } });
      map.addLayer({ id: "pakistan-region-labels", type: "symbol", source: "pakistan-political-labels", layout: { "text-field": ["get", "name"], "text-size": ["interpolate", ["linear"], ["zoom"], 3, 11, 6, 16], "text-letter-spacing": 0.08, "text-allow-overlap": false }, paint: { "text-color": "#38525a", "text-halo-color": "#ffffff", "text-halo-width": 1.5, "text-opacity": 0.82 } });
      map.addSource("water-lines", { type: "geojson", data: waterData.lines });
      map.addLayer({ id: "water-lines", type: "line", source: "water-lines", paint: { "line-color": "#2378a6", "line-width": ["interpolate", ["linear"], ["zoom"], 4, 1.7, 8, 3.4, 12, 6], "line-opacity": 0.86 } });
      map.addSource("water-bodies", { type: "geojson", data: waterData.bodies });
      map.addLayer({ id: "water-bodies", type: "symbol", source: "water-bodies", layout: { "icon-image": ["case", ["in", ["get", "feature_kind"], ["literal", ["dam", "dam_reservoir", "reservoir"]]], "dam-icon", "water-dot"], "icon-size": 1, "icon-allow-overlap": true } });
      map.addSource("observed-water-stations", { type: "geojson", data: waterData.observedStations });
      map.addLayer({ id: "observed-water-stations", type: "symbol", source: "observed-water-stations", layout: { "icon-image": "gauge-ring", "icon-size": 1, "icon-allow-overlap": true } });
      map.addSource("model-water-points", { type: "geojson", data: waterData.modelPoints });
      map.addLayer({ id: "model-water-points", type: "symbol", source: "model-water-points", layout: { "icon-image": "model-diamond", "icon-size": 1, "icon-allow-overlap": true } });
      map.addSource("stations", { type: "geojson", data: operationalData.stations });
      map.addLayer({ id: "stations", type: "circle", source: "stations", paint: { "circle-radius": ["case", ["==", ["get", "selected"], 1], 8, 6], "circle-color": "#083f48", "circle-stroke-color": "#ffffff", "circle-stroke-width": 2 } });
      map.addSource("incidents", { type: "geojson", data: operationalData.incidents });
      map.addLayer({ id: "incidents", type: "circle", source: "incidents", paint: { "circle-radius": 7, "circle-color": "#c83b44", "circle-stroke-color": "#ffffff", "circle-stroke-width": 2 } });
      map.addSource("reports", { type: "geojson", data: operationalData.reports });
      map.addLayer({ id: "reports", type: "circle", source: "reports", paint: { "circle-radius": 5, "circle-color": "#6d57a5", "circle-stroke-color": "#ffffff", "circle-stroke-width": 1.5 } });
      map.addSource("resources", { type: "geojson", data: operationalData.resources });
      map.addLayer({ id: "resources", type: "circle", source: "resources", paint: { "circle-radius": 5, "circle-color": "#16756f", "circle-stroke-color": "#ffffff", "circle-stroke-width": 1.5 } });

      map.on("mouseenter", "district-risk-fill", () => { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "district-risk-fill", () => { map.getCanvas().style.cursor = ""; });
      map.on("click", "district-risk-fill", (event: MapLayerMouseEvent) => {
        const districtId = event.features?.[0]?.properties?.district_id;
        const district = nationalRiskRef.current?.features.find((feature) => feature.properties.district_id === districtId) ?? null;
        setSelectedDistrict(district);
        setSelectedWaterFeature(null);
      });
      for (const layerId of ["water-lines", "water-bodies", "observed-water-stations", "model-water-points"] as const) {
        map.on("mouseenter", layerId, () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", layerId, () => { map.getCanvas().style.cursor = ""; });
        map.on("click", layerId, (event: MapLayerMouseEvent) => {
          const id = event.features?.[0]?.id ?? event.features?.[0]?.properties?.id;
          const feature = waterIntelligenceRef.current?.features.find((item) => item.id === id) ?? null;
          setSelectedWaterFeature(feature);
          setSelectedDistrict(null);
        });
      }
      map.on("click", "stations", (event: MapLayerMouseEvent) => {
        const id = event.features?.[0]?.properties?.id as LocationId | undefined;
        if (id) locationChangeRef.current(id);
      });
      map.on("idle", () => {
        const sourceDistricts = map.querySourceFeatures("district-risk").length;
        const renderedDistricts = map.queryRenderedFeatures({ layers: ["district-risk-fill"] }).length;
        if (containerRef.current) {
          containerRef.current.dataset.sourceFeatures = String(sourceDistricts);
          containerRef.current.dataset.renderedFeatures = String(renderedDistricts);
        }
      });
    });
    const resizeObserver = new ResizeObserver(() => {
      if (map.loaded()) fitPakistanExtent(map);
      else map.resize();
    });
    resizeObserver.observe(containerRef.current);
    mapRef.current = map;
    return () => { resizeObserver.disconnect(); map.remove(); mapRef.current = null; };
  }, [expanded]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.isStyleLoaded()) return;
    (map.getSource("district-risk") as GeoJSONSource | undefined)?.setData((nationalRisk ?? emptyCollection) as FeatureCollection);
    (map.getSource("water-lines") as GeoJSONSource | undefined)?.setData(waterData.lines);
    (map.getSource("water-bodies") as GeoJSONSource | undefined)?.setData(waterData.bodies);
    (map.getSource("observed-water-stations") as GeoJSONSource | undefined)?.setData(waterData.observedStations);
    (map.getSource("model-water-points") as GeoJSONSource | undefined)?.setData(waterData.modelPoints);
    (map.getSource("stations") as GeoJSONSource | undefined)?.setData(operationalData.stations);
    (map.getSource("incidents") as GeoJSONSource | undefined)?.setData(operationalData.incidents);
    (map.getSource("reports") as GeoJSONSource | undefined)?.setData(operationalData.reports);
    (map.getSource("resources") as GeoJSONSource | undefined)?.setData(operationalData.resources);
  }, [nationalRisk, operationalData]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.isStyleLoaded()) return;
    const visibility = (visible: boolean) => visible ? "visible" : "none";
    for (const id of ["ndma-operational-fill", "ndma-operational-line", "district-risk-fill", "district-risk-line", "pakistan-operational-outline"]) map.setLayoutProperty(id, "visibility", visibility(layers.risk));
    for (const id of ["water-lines", "water-bodies", "observed-water-stations", "model-water-points"]) map.setLayoutProperty(id, "visibility", visibility(layers.water));
    for (const id of ["stations", "incidents", "reports", "resources"] as const) map.setLayoutProperty(id, "visibility", visibility(layers[id]));
  }, [layers]);

  const metadata = nationalRisk?.metadata;
  const waterMetadata = waterIntelligence?.metadata;
  const selectedWaterKind = selectedWaterFeature?.properties.data_class.replace("_", " ");
  return (
    <section className={`national-map-panel ${expanded ? "national-map-expanded" : ""}`}>
      <header className="map-panel-header">
        <div><span><MapPinned size={18} /></span><div><h2>Pakistan National Risk Map</h2><p>{metadata ? `${metadata.returned_feature_count} districts · observed ${new Date(metadata.observed_at).toLocaleString()}` : "Loading national coverage"}</p></div></div>
        <div className="map-header-meta"><StatusBadge value={metadata?.data_mode ?? "LOADING"} /><span><Database size={13} /> {metadata?.cache_status ?? "waiting"}</span></div>
      </header>
      <div className="map-workspace">
        <div ref={containerRef} className="national-map" aria-label="Interactive Pakistan district flood risk map" />
        <div className="map-layer-control">
          <strong><Layers3 size={14} /> Operational layers</strong>
          {([
            ["risk", "District screening"], ["water", "Water intelligence"], ["stations", "Risk locations"], ["incidents", "Incidents"], ["reports", "Citizen reports"], ["resources", "Response resources"],
          ] as const).map(([id, label]) => <label key={id}><input type="checkbox" checked={layers[id]} onChange={() => setLayers((current) => ({ ...current, [id]: !current[id] }))} /><span>{label}</span></label>)}
        </div>
        <button className="map-home-button" type="button" title="Show full Pakistan operational extent" aria-label="Show full Pakistan operational extent" onClick={() => { if (mapRef.current) fitPakistanExtent(mapRef.current, 350); }}><Crosshair size={15} /></button>
        <div className="map-legend"><strong>Screening severity</strong><span><i className="legend-operational" /> NDMA extent</span><span><i className="legend-low" /> Low</span><span><i className="legend-medium" /> Medium</span><span><i className="legend-high" /> High</span><span><i className="legend-critical" /> Critical</span><span><i className="legend-water" /> River/lake</span><span><i className="legend-gauge" /> Gauge metadata</span><span><i className="legend-model" /> Model point</span></div>
        {metadata?.data_mode === "simulation" && <div className="map-simulation-label"><AlertTriangle size={15} /><strong>SIMULATED NATIONAL LAYER</strong></div>}
        {waterMetadata?.map_notice && <div className="map-water-notice"><AlertTriangle size={14} /><span>{waterMetadata.map_notice}</span></div>}
        <div className="map-boundary-notice"><MapPinned size={14} /><span>NDMA-style Pakistan operational extent includes Azad Jammu & Kashmir, Gilgit-Baltistan, and the wider Jammu & Kashmir section even where ADM2 risk data is unavailable.</span></div>
        {waterMetadata && <div className="water-intelligence-summary"><Waves size={14} /><strong>Water intelligence</strong><span>{waterMetadata.water_feature_count} GIS features</span><span>{waterMetadata.observed_station_count} stations</span><span>{waterMetadata.model_forecast_count} model points</span></div>}
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
      <footer className="map-provenance">
        <span><RadioTower size={14} /> Weather screening: Open-Meteo</span><span><Waves size={14} /> Water: GIS features, station metadata, and modeled points are separated</span><span><Building2 size={14} /> Operational map: Pakistan ADM2 plus NDMA Kashmir extent overlay</span><span><MessageSquareText size={14} /> Click a district or water point for evidence</span>
      </footer>
    </section>
  );
}

