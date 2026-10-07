import { Camera, CheckCircle2, Crosshair, Eye, Image as ImageIcon, Map as MapIcon, MapPin, MessageSquareText, Plus, Ruler, Star, Video, X } from "lucide-react";
import type { ChangeEvent, FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";

import { LOCATIONS } from "../config";
import type { CitizenReport } from "../types/api";
import { formatRelativeTime, locationName, parseApiDate } from "../utils/format";
import { Panel } from "./Panel";
import { StatusBadge } from "./StatusBadge";

const ACTIVE_WINDOW_MS = 60_000;

interface CitizenReportsPanelProps {
  reports: CitizenReport[];
  full?: boolean;
  onCreateReport?: (payload: {
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
  }) => Promise<CitizenReport | unknown> | CitizenReport | unknown;
  onToggleImportant?: (reportId: number) => Promise<CitizenReport | unknown> | CitizenReport | unknown;
  onCloseReport?: (reportId: number) => Promise<CitizenReport | unknown> | CitizenReport | unknown;
}

function activeSecondsRemaining(timestamp: string, now: number) {
  const ageMs = now - parseApiDate(timestamp).getTime();
  return Math.max(0, Math.ceil((ACTIVE_WINDOW_MS - ageMs) / 1000));
}

const firstLocation = LOCATIONS[0];

interface ReportFormState {
  location_id: string;
  latitude: string;
  longitude: string;
  google_maps_url: string;
  description: string;
  reported_water_depth_cm: string;
  image_url: string;
  video_url: string;
  image_latitude: string;
  image_longitude: string;
  source: string;
}

function createInitialForm(): ReportFormState {
  return {
    location_id: firstLocation.id,
    latitude: String(firstLocation.latitude),
    longitude: String(firstLocation.longitude),
    google_maps_url: "",
    description: "",
    reported_water_depth_cm: "",
    image_url: "",
    video_url: "",
    image_latitude: "",
    image_longitude: "",
    source: "citizen",
  };
}

function parseGoogleMapsCoordinates(value: string) {
  const decoded = decodeURIComponent(value);
  const patterns = [
    /@(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)/,
    /[?&](?:q|query|ll)=(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)/,
    /(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)/,
  ];
  for (const pattern of patterns) {
    const match = decoded.match(pattern);
    if (!match) continue;
    const latitude = Number(match[1]);
    const longitude = Number(match[2]);
    if (Number.isFinite(latitude) && Number.isFinite(longitude)) return { latitude, longitude };
  }
  return null;
}

function readAscii(view: DataView, offset: number, length: number) {
  let value = "";
  for (let index = 0; index < length; index += 1) {
    const byte = view.getUint8(offset + index);
    if (byte === 0) break;
    value += String.fromCharCode(byte);
  }
  return value;
}

function readGpsCoordinate(view: DataView, tiffStart: number, valueOffset: number, littleEndian: boolean) {
  const values = [0, 1, 2].map((index) => {
    const offset = tiffStart + valueOffset + index * 8;
    const numerator = view.getUint32(offset, littleEndian);
    const denominator = view.getUint32(offset + 4, littleEndian);
    return denominator ? numerator / denominator : 0;
  });
  return values[0] + values[1] / 60 + values[2] / 3600;
}

async function extractImageGps(file: File) {
  const buffer = await file.arrayBuffer();
  const view = new DataView(buffer);
  if (view.byteLength < 4 || view.getUint16(0) !== 0xffd8) return null;

  let offset = 2;
  while (offset + 4 < view.byteLength) {
    if (view.getUint8(offset) !== 0xff) break;
    const marker = view.getUint8(offset + 1);
    const size = view.getUint16(offset + 2);
    if (marker === 0xe1 && readAscii(view, offset + 4, 6) === "Exif") {
      const tiffStart = offset + 10;
      const littleEndian = readAscii(view, tiffStart, 2) === "II";
      const ifdOffset = view.getUint32(tiffStart + 4, littleEndian);
      const ifdStart = tiffStart + ifdOffset;
      const entries = view.getUint16(ifdStart, littleEndian);
      let gpsOffset: number | null = null;
      for (let index = 0; index < entries; index += 1) {
        const entry = ifdStart + 2 + index * 12;
        if (view.getUint16(entry, littleEndian) === 0x8825) {
          gpsOffset = view.getUint32(entry + 8, littleEndian);
          break;
        }
      }
      if (gpsOffset === null) return null;

      const gpsStart = tiffStart + gpsOffset;
      const gpsEntries = view.getUint16(gpsStart, littleEndian);
      let latRef = "N";
      let lonRef = "E";
      let latOffset: number | null = null;
      let lonOffset: number | null = null;
      for (let index = 0; index < gpsEntries; index += 1) {
        const entry = gpsStart + 2 + index * 12;
        const tag = view.getUint16(entry, littleEndian);
        const type = view.getUint16(entry + 2, littleEndian);
        const count = view.getUint32(entry + 4, littleEndian);
        const valueOffset = view.getUint32(entry + 8, littleEndian);
        if (tag === 1 && type === 2) latRef = readAscii(view, entry + 8, Math.min(count, 4));
        if (tag === 3 && type === 2) lonRef = readAscii(view, entry + 8, Math.min(count, 4));
        if (tag === 2 && type === 5) latOffset = valueOffset;
        if (tag === 4 && type === 5) lonOffset = valueOffset;
      }
      if (latOffset === null || lonOffset === null) return null;
      const latitude = readGpsCoordinate(view, tiffStart, latOffset, littleEndian) * (latRef === "S" ? -1 : 1);
      const longitude = readGpsCoordinate(view, tiffStart, lonOffset, littleEndian) * (lonRef === "W" ? -1 : 1);
      return { latitude, longitude };
    }
    offset += 2 + size;
  }
  return null;
}

export function CitizenReportsPanel({ reports, full = false, onCreateReport, onToggleImportant, onCloseReport }: CitizenReportsPanelProps) {
  const [now, setNow] = useState(() => Date.now());
  const [pendingClose, setPendingClose] = useState<Set<number>>(new Set());
  const [form, setForm] = useState(createInitialForm);
  const [showForm, setShowForm] = useState(false);
  const [showCoordinates, setShowCoordinates] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [locationMessage, setLocationMessage] = useState<string | null>(null);
  const [imageGeoMessage, setImageGeoMessage] = useState<string | null>(null);
  const [imageFileName, setImageFileName] = useState<string | null>(null);
  const [createdReports, setCreatedReports] = useState<CitizenReport[]>([]);
  const [reportOverrides, setReportOverrides] = useState<Map<number, CitizenReport>>(new Map());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const combinedReports = useMemo(() => {
    const reportIds = new Set(reports.map((report) => report.id));
    return [...createdReports.filter((report) => !reportIds.has(report.id)), ...reports].map((report) => reportOverrides.get(report.id) ?? report);
  }, [createdReports, reportOverrides, reports]);

  const visible = useMemo(() => {
    const sorted = [...combinedReports].sort((a, b) => {
      const aActive = activeSecondsRemaining(a.timestamp, now) > 0 ? 1 : 0;
      const bActive = activeSecondsRemaining(b.timestamp, now) > 0 ? 1 : 0;
      if (aActive !== bActive) return bActive - aActive;
      return parseApiDate(b.timestamp).getTime() - parseApiDate(a.timestamp).getTime();
    });
    return full ? sorted : sorted.slice(0, 30);
  }, [combinedReports, full, now]);

  async function handleToggleImportant(reportId: number) {
    if (!onToggleImportant) return;
    const report = combinedReports.find((item) => item.id === reportId);
    if (report?.report_status === "CLOSED") return;
    if (report) {
      const optimistic = {
        ...report,
        is_important: !report.is_important,
        important_marked_at: !report.is_important ? new Date().toISOString() : null,
      };
      setReportOverrides((current) => new Map(current).set(reportId, optimistic));
      setCreatedReports((current) => current.map((item) => item.id === reportId ? optimistic : item));
    }
    try {
      const updated = await onToggleImportant(reportId);
      if (updated && typeof updated === "object" && "id" in updated) {
        setReportOverrides((current) => new Map(current).set(reportId, updated as CitizenReport));
        setCreatedReports((current) => current.map((report) => report.id === reportId ? updated as CitizenReport : report));
      }
    } catch {
      if (report) {
        setReportOverrides((current) => new Map(current).set(reportId, report));
        setCreatedReports((current) => current.map((item) => item.id === reportId ? report : item));
      }
    }
  }

  async function handleCloseReport(reportId: number) {
    if (!onCloseReport || pendingClose.has(reportId)) return;
    const report = combinedReports.find((item) => item.id === reportId);
    if (report) {
      const optimistic = { ...report, report_status: "CLOSED", closed_at: new Date().toISOString() };
      setReportOverrides((current) => new Map(current).set(reportId, optimistic));
      setCreatedReports((current) => current.map((item) => item.id === reportId ? optimistic : item));
    }
    setPendingClose((current) => new Set(current).add(reportId));
    try {
      const closed = await onCloseReport(reportId);
      if (closed && typeof closed === "object" && "id" in closed) {
        setReportOverrides((current) => new Map(current).set(reportId, closed as CitizenReport));
        setCreatedReports((current) => current.map((report) => report.id === reportId ? closed as CitizenReport : report));
      }
    } finally {
      setPendingClose((current) => {
        const next = new Set(current);
        next.delete(reportId);
        return next;
      });
    }
  }

  function updateLocation(locationId: string) {
    const location = LOCATIONS.find((item) => item.id === locationId) ?? firstLocation;
    setForm((current) => ({
      ...current,
      location_id: location.id,
      latitude: String(location.latitude),
      longitude: String(location.longitude),
    }));
  }

  function applyGoogleMapsLink() {
    const coordinates = parseGoogleMapsCoordinates(form.google_maps_url);
    if (!coordinates) {
      setLocationMessage("No coordinates found in that Google Maps link.");
      return;
    }
    setForm((current) => ({
      ...current,
      latitude: coordinates.latitude.toFixed(6),
      longitude: coordinates.longitude.toFixed(6),
    }));
    setLocationMessage("Coordinates applied from Google Maps link.");
  }

  function useBrowserLocation() {
    if (!navigator.geolocation) {
      setLocationMessage("Browser location is not available.");
      return;
    }
    setLocationMessage("Requesting device location...");
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setForm((current) => ({
          ...current,
          latitude: position.coords.latitude.toFixed(6),
          longitude: position.coords.longitude.toFixed(6),
        }));
        setLocationMessage(`Device location applied with ${Math.round(position.coords.accuracy)} m accuracy.`);
      },
      (error) => setLocationMessage(error.message || "Could not read device location."),
      { enableHighAccuracy: true, timeout: 10000 },
    );
  }

  function openGoogleMap() {
    const latitude = Number(form.latitude);
    const longitude = Number(form.longitude);
    const query = Number.isFinite(latitude) && Number.isFinite(longitude) ? `${latitude},${longitude}` : "Pakistan flood report";
    window.open(`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`, "_blank", "noopener,noreferrer");
  }

  async function handleImageFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    setImageFileName(file?.name ?? null);
    setImageGeoMessage(null);
    setForm((current) => ({ ...current, image_latitude: "", image_longitude: "" }));
    if (!file) return;
    try {
      const coordinates = await extractImageGps(file);
      if (!coordinates) {
        setImageGeoMessage("No image GPS found. Image GPS will save as null.");
        return;
      }
      setForm((current) => ({
        ...current,
        image_latitude: coordinates.latitude.toFixed(6),
        image_longitude: coordinates.longitude.toFixed(6),
      }));
      setImageGeoMessage("Image GPS extracted from photo metadata.");
    } catch {
      setImageGeoMessage("Could not read image metadata. Image GPS will save as null.");
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!onCreateReport || submitting) return;
    const description = form.description.trim();
    const latitude = Number(form.latitude);
    const longitude = Number(form.longitude);
    const depth = form.reported_water_depth_cm.trim() ? Number(form.reported_water_depth_cm) : null;
    const imageLatitude = form.image_latitude.trim() ? Number(form.image_latitude) : null;
    const imageLongitude = form.image_longitude.trim() ? Number(form.image_longitude) : null;
    if (!description) {
      setFormError("Report description is required.");
      return;
    }
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
      setFormError("Latitude and longitude must be valid numbers.");
      return;
    }
    if (depth !== null && !Number.isFinite(depth)) {
      setFormError("Reported water depth must be a valid number.");
      return;
    }
    if ((imageLatitude !== null && !Number.isFinite(imageLatitude)) || (imageLongitude !== null && !Number.isFinite(imageLongitude))) {
      setFormError("Image GPS latitude and longitude must be valid numbers or empty.");
      return;
    }

    setSubmitting(true);
    setFormError(null);
    try {
      const created = await onCreateReport({
        location_id: form.location_id,
        latitude,
        longitude,
        description,
        reported_water_depth_cm: depth,
        image_url: form.image_url.trim() || null,
        video_url: form.video_url.trim() || null,
        image_latitude: imageLatitude,
        image_longitude: imageLongitude,
        source: form.source.trim() || "citizen",
      });
      if (created && typeof created === "object" && "id" in created) {
        setCreatedReports((current) => [created as CitizenReport, ...current].slice(0, 10));
      }
      setForm(createInitialForm());
      setLocationMessage(null);
      setImageGeoMessage(null);
      setImageFileName(null);
      setShowForm(false);
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Could not save citizen report.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Panel
      title="Citizen Reports"
      icon={MessageSquareText}
      action={(
        <div className="report-panel-actions">
          <span className="count-label">{combinedReports.length} received</span>
          {full && onCreateReport && (
            <button className="create-report-button" type="button" onClick={() => setShowForm((current) => !current)}>
              {showForm ? <X size={14} /> : <Plus size={14} />}
              {showForm ? "Close" : "Create report"}
            </button>
          )}
        </div>
      )}
    >
      {full && onCreateReport && showForm && (
        <form className="report-entry-form" onSubmit={handleSubmit}>
          <div className="report-location-tools">
            <button type="button" className="secondary-button" onClick={useBrowserLocation}><Crosshair size={14} /> Use my location</button>
            <button type="button" className="secondary-button" onClick={openGoogleMap}><MapIcon size={14} /> Open Google Map</button>
            <button type="button" className="secondary-button" onClick={() => setShowCoordinates((current) => !current)}><Eye size={14} /> {showCoordinates ? "Hide lat/long" : "Show lat/long"}</button>
          </div>
          <div className="report-map-link-row">
            <label>
              <span>Google Maps link</span>
              <input value={form.google_maps_url} onChange={(event) => setForm((current) => ({ ...current, google_maps_url: event.target.value }))} placeholder="Paste Google Maps link or lat,lng" />
            </label>
            <button className="secondary-button" type="button" onClick={applyGoogleMapsLink}>Apply map link</button>
          </div>
          {locationMessage && <div className="form-hint">{locationMessage}</div>}
          <div className="report-form-grid">
            <label>
              <span>Location</span>
              <select value={form.location_id} onChange={(event) => updateLocation(event.target.value)}>
                {LOCATIONS.map((location) => <option key={location.id} value={location.id}>{location.name} ({location.id})</option>)}
              </select>
            </label>
            <label className={!showCoordinates ? "collapsed-field" : undefined}>
              <span>Latitude</span>
              <input value={form.latitude} onChange={(event) => setForm((current) => ({ ...current, latitude: event.target.value }))} inputMode="decimal" />
            </label>
            <label className={!showCoordinates ? "collapsed-field" : undefined}>
              <span>Longitude</span>
              <input value={form.longitude} onChange={(event) => setForm((current) => ({ ...current, longitude: event.target.value }))} inputMode="decimal" />
            </label>
            <label>
              <span>Depth cm</span>
              <input value={form.reported_water_depth_cm} onChange={(event) => setForm((current) => ({ ...current, reported_water_depth_cm: event.target.value }))} inputMode="decimal" placeholder="Optional" />
            </label>
          </div>
          <label className="report-description-field">
            <span>Report</span>
            <textarea value={form.description} onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))} rows={3} placeholder="Describe the incident, flooding, blocked road, rescue need, or observed water level." />
          </label>
          <div className="report-form-grid report-form-media">
            <label>
              <span>Image URL</span>
              <input value={form.image_url} onChange={(event) => setForm((current) => ({ ...current, image_url: event.target.value }))} placeholder="Optional image link" />
            </label>
            <label>
              <span>Video URL</span>
              <input value={form.video_url} onChange={(event) => setForm((current) => ({ ...current, video_url: event.target.value }))} placeholder="Optional video link" />
            </label>
            <label>
              <span>Source</span>
              <input value={form.source} onChange={(event) => setForm((current) => ({ ...current, source: event.target.value }))} />
            </label>
            <button className="primary-button" type="submit" disabled={submitting}>{submitting ? "Saving" : "Save report"}</button>
          </div>
          <div className="report-image-geo-row">
            <label className="file-picker">
              <span>Geotagged image</span>
              <input type="file" accept="image/jpeg,image/jpg,image/*" onChange={handleImageFile} />
            </label>
            <div className="image-geo-display">
              <span><ImageIcon size={13} /> {imageFileName ?? "No image selected"}</span>
              <strong>Image GPS: {form.image_latitude || "null"}, {form.image_longitude || "null"}</strong>
            </div>
          </div>
          {imageGeoMessage && <div className="form-hint">{imageGeoMessage}</div>}
          {formError && <div className="inline-error">{formError}</div>}
        </form>
      )}
      {!visible.length ? <div className="empty-state">No citizen reports received.</div> : (
        <div className="report-list report-list-scroll">
          {visible.map((report) => {
            const secondsRemaining = activeSecondsRemaining(report.timestamp, now);
            const isActive = secondsRemaining > 0;
            const isClosing = pendingClose.has(report.id);
            const isClosed = report.report_status === "CLOSED";
            return (
            <article key={report.id} className={`report-card ${isActive ? "report-active" : ""} ${report.is_important ? "report-important" : ""} ${isClosed ? "report-closed" : ""}`}>
              <div className="report-head">
                <div><MapPin size={15} /><strong>{locationName(report.location_id)}</strong><span>{formatRelativeTime(report.timestamp)}</span></div>
                <div className="report-statuses">
                  {isActive && <span className="report-live-badge">Live {secondsRemaining}s</span>}
                  {report.is_important && <StatusBadge value="important" subtle />}
                  <StatusBadge value={report.report_status} subtle />
                  <StatusBadge value={report.verification_status} subtle />
                </div>
              </div>
              <p>{report.description}</p>
              <div className="report-card-meta">
                <span>{report.source}</span>
                <span>Report GPS: {report.latitude.toFixed(5)}, {report.longitude.toFixed(5)}</span>
                <span>Image GPS: {report.image_latitude ?? "null"}, {report.image_longitude ?? "null"}</span>
                {report.reported_water_depth_cm !== null && <span className="depth-label"><Ruler size={14} /> Reported depth: {report.reported_water_depth_cm} cm</span>}
                {report.closed_at && <span><CheckCircle2 size={13} /> Closed {formatRelativeTime(report.closed_at)}</span>}
              </div>
              {(report.image_url || report.video_url || (!isClosed && (onToggleImportant || onCloseReport))) && (
                <div className="report-actions">
                  <div className="report-media-row">
                    {report.image_url && <a className="report-media-chip" href={report.image_url} target="_blank" rel="noreferrer"><Camera size={13} /> Image</a>}
                    {report.video_url && <a className="report-media-chip" href={report.video_url} target="_blank" rel="noreferrer"><Video size={13} /> Video</a>}
                  </div>
                  <div className="report-action-buttons">
                    {onToggleImportant && !isClosed && (
                      <button className="important-button" type="button" onClick={() => void handleToggleImportant(report.id)} title={report.is_important ? "Unmark report as important" : "Mark report important for escalation"}>
                        <Star size={13} /> {report.is_important ? "Unmark" : "Important"}
                      </button>
                    )}
                    {onCloseReport && !isClosed && (
                      <button className="close-report-button" type="button" disabled={isClosing} onClick={() => void handleCloseReport(report.id)} title="Close report in database">
                        <CheckCircle2 size={13} /> {isClosing ? "Closing" : "Close report"}
                      </button>
                    )}
                  </div>
                </div>
              )}
            </article>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
