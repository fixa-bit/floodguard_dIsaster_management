import { booleanPointInPolygon } from "@turf/boolean-point-in-polygon";
import type { Feature, FeatureCollection, MultiPolygon, Polygon } from "geojson";
import {
  AlertTriangle, Ambulance, CloudRain, Crosshair, GraduationCap, Hospital, LoaderCircle, MapPin, MessageSquareText,
  Shield, Stethoscope, Tent, Waves, X, ZoomIn,
} from "lucide-react";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useMemo, useRef, useState, type ComponentType } from "react";

import { apiFetch } from "../services/api";
import type { CitizenReport, Incident, NationalRiskCollection, RiverMonitoringStation } from "../types/api";
import { pointOf } from "./alarmArea";
import { formatFlow } from "./waterQuantities";
import "../relief-assessment.css";

/** What GIS Operations is assessing: a station, a district, a picked point or the operational area. */
export interface AssessmentTarget {
  kind: "area" | "point" | "district" | "station";
  label: string;
  latitude: number;
  longitude: number;
  stationId?: string;
}

interface Facility { id: string; category: string; name: string; lat: number; lon: number; distance_km: number; tags: Record<string, string> }
interface FacilityCategory { category: string; label: string; count: number; items: Facility[]; nearest_outside: Facility | null }
interface FacilityReply {
  available: boolean; source?: string; retrieved_at?: string; note: string; radius_km: number; total?: number;
  categories: FacilityCategory[]; features: Facility[];
}

const RADII = [10, 25, 50, 100];
const CATEGORY_STYLE: Record<string, { color: string; icon: ComponentType<{ size?: number }> }> = {
  hospital: { color: "#ff5c7a", icon: Hospital },
  clinic: { color: "#ff9f6b", icon: Stethoscope },
  rescue: { color: "#ffd166", icon: Ambulance },
  police: { color: "#6ea8ff", icon: Shield },
  school: { color: "#7ee0a1", icon: GraduationCap },
  assembly: { color: "#c49bff", icon: Tent },
};
const SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];
const empty: FeatureCollection = { type: "FeatureCollection", features: [] };
const RELIEF_LAYERS = ["relief-ring-fill", "relief-ring-casing", "relief-ring-line", "relief-facilities-points", "relief-facilities-labels"];
const easeInOutSine = (t: number) => 0.5 - 0.5 * Math.cos(Math.PI * t);

function distanceKm(aLat: number, aLon: number, bLat: number, bLon: number) {
  const r = Math.PI / 180, dLat = (bLat - aLat) * r, dLon = (bLon - aLon) * r;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(aLat * r) * Math.cos(bLat * r) * Math.sin(dLon / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(h));
}

/** The radius as a ring of points around the target, for the map. */
function ring(latitude: number, longitude: number, km: number): Feature<Polygon> {
  const coordinates: [number, number][] = [];
  for (let i = 0; i <= 72; i += 1) {
    const angle = (i / 72) * 2 * Math.PI;
    const dLat = (km / 111.32) * Math.cos(angle);
    const dLon = (km / (111.32 * Math.cos((latitude * Math.PI) / 180))) * Math.sin(angle);
    coordinates.push([longitude + dLon, latitude + dLat]);
  }
  return { type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [coordinates] } };
}

const km = (value: number) => `${value < 10 ? value.toFixed(1) : Math.round(value)} km`;
const when = (iso: string) => new Date(iso).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

/**
 * GIS Operations' relief and assessment panel. For the chosen target and radius it brings together
 * the hazard (district screening, rain, nearby river stations), the field situation (incidents,
 * citizen reports) and the relief facilities around it, and draws the radius and facilities on the map.
 */
export function ReliefAssessment({ map, target, picking, onPick, onClear, risk, districts, stations, incidents, reports, onSelectStation }: {
  map: MapLibreMap | null; target: AssessmentTarget | null; picking: boolean; onPick: () => void; onClear: () => void;
  risk: NationalRiskCollection | null; districts: FeatureCollection; stations: RiverMonitoringStation[];
  incidents: Incident[]; reports: CitizenReport[]; onSelectStation: (id: string) => void;
}) {
  const [radius, setRadius] = useState(25);
  const [reply, setReply] = useState<FacilityReply | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>("hospital");
  const popup = useRef<maplibregl.Popup | null>(null);

  // Facilities around the target (the backend answers from the OpenStreetMap extract).
  useEffect(() => {
    if (!target) { setReply(null); return; }
    let live = true;
    setLoading(true); setError(null);
    apiFetch<FacilityReply>(`/resources/facilities/nearby?latitude=${target.latitude.toFixed(5)}&longitude=${target.longitude.toFixed(5)}&radius_km=${radius}&per_category=12`)
      .then((result) => { if (live) setReply(result); })
      .catch((e) => { if (live) { setReply(null); setError(e instanceof Error ? e.message : "Facilities could not be loaded."); } })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [target?.latitude, target?.longitude, radius]);

  const district = useMemo(() => {
    if (!target) return null;
    const point: [number, number] = [target.longitude, target.latitude];
    return districts.features.find((feature) => (feature.geometry?.type === "Polygon" || feature.geometry?.type === "MultiPolygon")
      && booleanPointInPolygon(point, feature as Feature<Polygon | MultiPolygon>)) ?? null;
  }, [target, districts]);
  const districtName = district ? String(district.properties?.district_name ?? "") : "";
  const screening = useMemo(() => districtName
    ? risk?.features.find((feature) => feature.properties.district_name.toLowerCase() === districtName.toLowerCase())?.properties ?? null
    : null, [risk, districtName]);

  const nearbyStations = useMemo(() => {
    if (!target) return [];
    const ranked = stations.map((station) => ({ station, km: distanceKm(target.latitude, target.longitude, station.latitude, station.longitude) }))
      .sort((a, b) => a.km - b.km);
    const inside = ranked.filter((item) => item.km <= radius);
    return (inside.length ? inside : ranked.slice(0, 2)).map((item) => ({ ...item, inside: item.km <= radius }));
  }, [target, stations, radius]);

  const stationPoints = useMemo(() => new Map(stations.map((station) => [station.id.toUpperCase(), { latitude: station.latitude, longitude: station.longitude }])), [stations]);
  const nearbyIncidents = useMemo(() => !target ? [] : incidents.flatMap((incident) => {
    const point = pointOf(incident.location_id, stationPoints);
    const away = point ? distanceKm(target.latitude, target.longitude, point.latitude, point.longitude) : Infinity;
    return away <= radius ? [{ incident, km: away }] : [];
  }).sort((a, b) => SEVERITY_ORDER.indexOf(a.incident.severity) - SEVERITY_ORDER.indexOf(b.incident.severity)), [target, incidents, stationPoints, radius]);
  const nearbyReports = useMemo(() => !target ? [] : reports
    .map((report) => ({ report, km: distanceKm(target.latitude, target.longitude, report.latitude, report.longitude) }))
    .filter((item) => item.km <= radius)
    .sort((a, b) => (b.report.timestamp ?? "").localeCompare(a.report.timestamp ?? "")), [target, reports, radius]);

  const inFlood = nearbyStations.filter((item) => item.inside && /flood|high|very|exceptional|danger/i.test(item.station.flood_category ?? "") && !/below/i.test(item.station.flood_category ?? ""));
  const openIncidents = nearbyIncidents.filter((item) => item.incident.status !== "CLOSED" && item.incident.status !== "RESOLVED");
  const pendingReports = nearbyReports.filter((item) => item.report.verification_status === "PENDING");
  const deepest = Math.max(0, ...nearbyReports.map((item) => item.report.reported_water_depth_cm ?? 0));
  const count = (category: string) => reply?.categories.find((item) => item.category === category)?.count ?? 0;

  // The radius and the facilities on the map (added again after a style change).
  useEffect(() => {
    if (!map) return;
    const ringData = target ? { type: "FeatureCollection", features: [ring(target.latitude, target.longitude, radius)] } as FeatureCollection : empty;
    const facilityData: FeatureCollection = { type: "FeatureCollection", features: (reply?.features ?? []).map((facility) => ({
      type: "Feature", geometry: { type: "Point", coordinates: [facility.lon, facility.lat] },
      properties: { id: facility.id, category: facility.category, name: facility.name, distance: km(facility.distance_km) } })) };
    const sync = () => {
      // Not isStyleLoaded(): it stays false while any tiles load. Adding fails only before the style itself is in.
      try { draw(); } catch { /* the style is still loading; the next styledata event draws */ }
    };
    const draw = () => {
      if (!map.getSource("relief-ring")) {
        map.addSource("relief-ring", { type: "geojson", data: empty });
        map.addLayer({ id: "relief-ring-fill", type: "fill", source: "relief-ring", paint: { "fill-color": "#50f5d0", "fill-opacity": 0.05 } });
        map.addLayer({ id: "relief-ring-casing", type: "line", source: "relief-ring", paint: { "line-color": "#03161a", "line-width": 4.5, "line-opacity": 0.7 } });
        map.addLayer({ id: "relief-ring-line", type: "line", source: "relief-ring", paint: { "line-color": "#50f5d0", "line-width": 2.2, "line-dasharray": [2.5, 1.5] } });
      }
      if (!map.getSource("relief-facilities")) {
        map.addSource("relief-facilities", { type: "geojson", data: empty });
        map.addLayer({ id: "relief-facilities-points", type: "circle", source: "relief-facilities", paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 6, 2.5, 10, 4.5, 14, 7],
          "circle-color": ["match", ["get", "category"], ...Object.entries(CATEGORY_STYLE).flatMap(([id, style]) => [id, style.color]), "#ffffff"],
          "circle-stroke-color": "#06171a", "circle-stroke-width": 1 } });
        map.addLayer({ id: "relief-facilities-labels", type: "symbol", source: "relief-facilities", minzoom: 12, layout: {
          "text-field": ["get", "name"], "text-font": ["Open Sans Regular"], "text-size": 11, "text-offset": [0, 1.1], "text-anchor": "top", "text-optional": true },
          paint: { "text-color": "#e8fffb", "text-halo-color": "#06171a", "text-halo-width": 1.2 } });
      }
      // Kept above layers added later (population grid, district shading), only when not already on top.
      const order = map.getLayersOrder();
      if (order.slice(-RELIEF_LAYERS.length).join() !== RELIEF_LAYERS.join()) for (const id of RELIEF_LAYERS) if (map.getLayer(id)) map.moveLayer(id);
      (map.getSource("relief-ring") as GeoJSONSource).setData(ringData);
      (map.getSource("relief-facilities") as GeoJSONSource).setData(facilityData);
    };
    sync();
    map.on("styledata", sync);
    return () => { map.off("styledata", sync); };
  }, [map, target, radius, reply]);

  // A facility on the map shows its name and distance.
  useEffect(() => {
    if (!map) return;
    const show = (event: maplibregl.MapLayerMouseEvent) => {
      const properties = event.features?.[0]?.properties;
      if (!properties) return;
      popup.current?.remove();
      popup.current = new maplibregl.Popup({ closeButton: false, offset: 8, className: "relief-popup" }).setLngLat(event.lngLat)
        .setHTML(`<strong></strong><span></span>`).addTo(map);
      const element = popup.current.getElement();
      element.querySelector("strong")!.textContent = properties.name || "Unnamed facility";
      element.querySelector("span")!.textContent = `${properties.category} · ${properties.distance} from the assessed point`;
    };
    const enter = () => { map.getCanvas().style.cursor = "pointer"; };
    const leave = () => { map.getCanvas().style.cursor = ""; };
    map.on("click", "relief-facilities-points", show);
    map.on("mouseenter", "relief-facilities-points", enter);
    map.on("mouseleave", "relief-facilities-points", leave);
    return () => { map.off("click", "relief-facilities-points", show); map.off("mouseenter", "relief-facilities-points", enter); map.off("mouseleave", "relief-facilities-points", leave); popup.current?.remove(); };
  }, [map]);

  const showArea = () => {
    if (!map || !target) return;
    const [outer] = ring(target.latitude, target.longitude, radius).geometry.coordinates;
    const lons = outer.map((c) => c[0]), lats = outer.map((c) => c[1]);
    map.fitBounds([[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]], { padding: 48, pitch: 0, bearing: 0, duration: 1800, easing: easeInOutSine });
  };
  const flyTo = (lat: number, lon: number) => map?.flyTo({ center: [lon, lat], zoom: Math.max(map.getZoom(), 13), duration: 1800, easing: easeInOutSine, essential: true });

  return (
    <aside className="relief-assessment" aria-label="Relief and assessment">
      <header className="relief-head">
        <div>
          <span>Relief &amp; assessment</span>
          <h3>{target ? target.label : "Choose a place"}</h3>
          {target && <small>{target.latitude.toFixed(4)}°N, {target.longitude.toFixed(4)}°E{districtName && target.kind !== "district" ? ` · ${districtName} district` : ""}</small>}
        </div>
        <div className="relief-head-actions">
          <button type="button" aria-pressed={picking} title="Pick a point on the map" onClick={onPick}><Crosshair size={14} /> {picking ? "Click the map…" : "Pick point"}</button>
          {target && target.kind !== "area" && <button type="button" title="Back to the operational area" aria-label="Back to the operational area" onClick={onClear}><X size={14} /></button>}
        </div>
      </header>
      <p className="relief-hint">Click a district or station on the map, or pick any point, to assess it. With nothing selected the panel assesses the operational area chosen at the top.</p>

      {target && <>
        <div className="relief-radius" role="group" aria-label="Assessment radius">
          <span>Within</span>
          {RADII.map((value) => <button key={value} type="button" aria-pressed={radius === value} onClick={() => setRadius(value)}>{value} km</button>)}
          <button type="button" className="relief-zoom" title="Show this area on the map" aria-label="Show this area on the map" onClick={showArea}><ZoomIn size={14} /></button>
        </div>

        <div className="relief-summary">
          <div className={screening && ["HIGH", "CRITICAL"].includes(screening.severity) ? "warn" : ""}><span>District risk</span><strong>{screening ? screening.severity.toLowerCase() : "—"}</strong><small>{screening ? `${Math.round(screening.risk_probability * 100)}% screening` : districtName ? "No screening" : "Outside districts"}</small></div>
          <div className={inFlood.length ? "warn" : ""}><span>Stations in flood</span><strong>{inFlood.length}</strong><small>of {nearbyStations.filter((item) => item.inside).length} within {radius} km</small></div>
          <div className={openIncidents.length ? "warn" : ""}><span>Open incidents</span><strong>{openIncidents.length}</strong><small>{pendingReports.length} report{pendingReports.length === 1 ? "" : "s"} to verify</small></div>
          <div><span>Hospitals</span><strong>{loading ? "…" : reply?.available ? count("hospital") : "—"}</strong><small>{reply?.available ? `${count("clinic")} clinics · ${count("school")} schools` : "Facilities unavailable"}</small></div>
        </div>

        <section className="relief-section">
          <h4><CloudRain size={14} /> Hazard</h4>
          {screening ? <dl className="relief-facts">
            <div><dt>District</dt><dd>{screening.district_name} · {screening.severity.toLowerCase()} ({Math.round(screening.risk_probability * 100)}%)</dd></div>
            {typeof screening.rainfall_24h_mm === "number" && <div><dt>Rain, last 24 h</dt><dd>{screening.rainfall_24h_mm.toFixed(1)} mm</dd></div>}
            {typeof screening.forecast_rainfall_24h_mm === "number" && <div><dt>Rain, next 24 h</dt><dd>{screening.forecast_rainfall_24h_mm.toFixed(1)} mm</dd></div>}
            {screening.top_risk_factors?.length > 0 && <div><dt>Drivers</dt><dd>{screening.top_risk_factors.slice(0, 3).join(", ")}</dd></div>}
          </dl> : <p className="relief-muted">{districtName ? `${districtName}: no district screening loaded.` : "No district screening for this point."}</p>}
          <h5><Waves size={13} /> River stations {nearbyStations.some((item) => item.inside) ? `within ${radius} km` : "(nearest, outside the radius)"}</h5>
          <ul className="relief-list">
            {nearbyStations.map(({ station, km: away, inside }) => (
              <li key={station.id}>
                <button type="button" onClick={() => onSelectStation(station.id)}>
                  <strong>{station.name}</strong><small>{station.river} · {km(away)}{inside ? "" : " away"}</small>
                </button>
                <span className={`relief-status ${/below|normal/i.test(station.flood_category ?? "") ? "" : "warn"}`}>{station.flood_category || "no reading"}</span>
                <em>{formatFlow(station.current_discharge_cumecs)}</em>
              </li>
            ))}
            {!nearbyStations.length && <li className="relief-muted">River station data is loading or unavailable.</li>}
          </ul>
        </section>

        <section className="relief-section">
          <h4><AlertTriangle size={14} /> Field situation</h4>
          <ul className="relief-list">
            {nearbyIncidents.slice(0, 4).map(({ incident, km: away }) => (
              <li key={`i${incident.id}`}><div><strong>Incident #{incident.id} · {incident.type.toLowerCase()}</strong><small>{incident.description}</small></div>
                <span className="relief-status warn">{incident.severity.toLowerCase()} · {incident.status.toLowerCase()}</span><em>{km(away)}</em></li>
            ))}
            {nearbyReports.slice(0, 4).map(({ report, km: away }) => (
              <li key={`r${report.id}`}><div><strong><MessageSquareText size={12} /> Citizen report #{report.id}</strong><small>{report.description}{report.reported_water_depth_cm ? ` · water ${report.reported_water_depth_cm} cm` : ""}</small></div>
                <span className={`relief-status ${report.verification_status === "PENDING" ? "warn" : ""}`}>{report.verification_status.toLowerCase()}</span><em>{km(away)}</em></li>
            ))}
            {!nearbyIncidents.length && !nearbyReports.length && <li className="relief-muted">No incidents or citizen reports within {radius} km.</li>}
          </ul>
          {nearbyReports.length > 0 && <p className="relief-muted">{nearbyReports.length} citizen report{nearbyReports.length === 1 ? "" : "s"}{deepest ? `, deepest water reported ${deepest} cm` : ""}{nearbyReports[0]?.report.timestamp ? `, latest ${when(nearbyReports[0].report.timestamp)}` : ""}.</p>}
        </section>

        <section className="relief-section">
          <h4><Hospital size={14} /> Relief facilities {reply?.total !== undefined && <small>{reply.total} within {radius} km</small>}</h4>
          {loading && <p className="relief-muted"><LoaderCircle size={13} className="spinning" /> Finding facilities…</p>}
          {error && <p className="relief-error">{error}</p>}
          {reply && !reply.available && <p className="relief-error">{reply.note}</p>}
          {reply?.available && reply.categories.map((group) => {
            const style = CATEGORY_STYLE[group.category];
            const Icon = style?.icon ?? MapPin;
            const expanded = open === group.category;
            return (
              <div className="relief-category" key={group.category}>
                <button type="button" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : group.category)}>
                  <i style={{ background: style?.color }} /><Icon size={14} /><span>{group.label}</span>
                  <strong>{group.count}</strong>
                  <small>{group.items[0] ? `nearest ${km(group.items[0].distance_km)}` : group.nearest_outside ? `nearest ${km(group.nearest_outside.distance_km)}` : "none mapped"}</small>
                </button>
                {expanded && <ul className="relief-list">
                  {group.items.map((facility) => (
                    <li key={facility.id}><button type="button" onClick={() => flyTo(facility.lat, facility.lon)}>
                      <strong>{facility.name || "Unnamed"}</strong>
                      <small>{[facility.tags.operator, facility.tags["addr:city"], facility.tags.beds ? `${facility.tags.beds} beds` : null, facility.tags.phone ?? facility.tags["contact:phone"]].filter(Boolean).join(" · ") || "No details mapped"}</small>
                    </button><em>{km(facility.distance_km)}</em></li>
                  ))}
                  {!group.items.length && group.nearest_outside && <li><button type="button" onClick={() => flyTo(group.nearest_outside!.lat, group.nearest_outside!.lon)}>
                    <strong>{group.nearest_outside.name || "Unnamed"}</strong><small>Nearest, outside the radius</small></button><em>{km(group.nearest_outside.distance_km)}</em></li>}
                  {group.count > group.items.length && <li className="relief-muted">+{group.count - group.items.length} more on the map</li>}
                </ul>}
              </div>
            );
          })}
          {reply?.available && <p className="relief-source">Facilities: © OpenStreetMap contributors (ODbL), retrieved {reply.retrieved_at?.slice(0, 10)}. {reply.note} Confirm before dispatching.</p>}
        </section>
      </>}
    </aside>
  );
}
