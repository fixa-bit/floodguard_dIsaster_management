import { AlertTriangle, CheckCircle2, Database, FlaskConical, LoaderCircle, Play, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { ApiError, api } from "../services/api";
import type { MonitoringSimulationRequest, MonitoringSimulationResult, SimulationStation } from "../types/api";
import { formatDateTime } from "../utils/format";
import { StatusBadge } from "./StatusBadge";
import "../simulation.css";

type DraftReading = { id: number; offset: string; value: string; p25: string; p75: string };
type Measurement = MonitoringSimulationRequest["measurement"];
type Unit = MonitoringSimulationRequest["unit"];

function localNow() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function optionalNumber(value: string) {
  return value.trim() === "" ? null : Number(value);
}

export function SimulationPanel({ onCompleted, onOpenAlerts, onOpenIncidents }: {
  onCompleted: (result: MonitoringSimulationResult) => void;
  onOpenAlerts: () => void;
  onOpenIncidents: () => void;
}) {
  const [stations, setStations] = useState<SimulationStation[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [name, setName] = useState("Flood threshold test");
  const [stationCode, setStationCode] = useState("TAUNSA");
  const [measurement, setMeasurement] = useState<Measurement>("discharge_inflow");
  const [unit, setUnit] = useState<Unit>("cusecs");
  const [startAt, setStartAt] = useState(localNow);
  const [reference, setReference] = useState("");
  const [thresholdMode, setThresholdMode] = useState<"saved" | "custom">("saved");
  const [warning, setWarning] = useState("");
  const [danger, setDanger] = useState("");
  const [readings, setReadings] = useState<DraftReading[]>([{ id: 0, offset: "0", value: "", p25: "", p75: "" }]);
  const nextRowId = useRef(1);
  const attempt = useRef<{ signature: string; runId: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<MonitoringSimulationResult | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true); setLoadError(null);
    api.simulationStations().then((items) => {
      if (!active) return;
      setStations(items);
      setStationCode((previous) => items.some((item) => item.code === previous) ? previous : items[0]?.code ?? "");
    }).catch((reason: unknown) => {
      if (active) setLoadError(reason instanceof Error ? reason.message : "Station data unavailable");
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [retry]);

  const station = stations.find((item) => item.code === stationCode);
  const saved = station?.thresholds.filter((item) => item.measurement === measurement && item.unit === unit &&
    ["warning", "danger"].includes(item.level) && item.value !== null &&
    (measurement !== "water_level" || Boolean(item.level_reference) && item.level_reference === reference)) ?? [];
  const savedWarning = saved.find((item) => item.level === "warning")?.value ?? null;
  const savedDanger = saved.find((item) => item.level === "danger")?.value ?? null;
  const activeWarning = thresholdMode === "saved" ? savedWarning : optionalNumber(warning);
  const activeDanger = thresholdMode === "saved" ? savedDanger : optionalNumber(danger);
  const hasThreshold = activeWarning !== null || activeDanger !== null;

  function updateReading(id: number, field: keyof Omit<DraftReading, "id">, value: string) {
    setReadings((items) => items.map((item) => item.id === id ? { ...item, [field]: value } : item));
  }

  function readingLevel(value: string) {
    if (value.trim() === "") return "Pending";
    if (activeDanger !== null && Number(value) >= activeDanger) return "Danger";
    if (activeWarning !== null && Number(value) >= activeWarning) return "Warning";
    return hasThreshold ? "Normal" : "No threshold";
  }

  function loadProfile(profile: string) {
    if (!hasThreshold || profile === "custom") return;
    const limit = activeDanger ?? activeWarning!;
    const low = Math.min(activeWarning ?? limit, limit);
    const values = profile === "normal" ? [low * 0.5, low * 0.7, low * 0.8]
      : profile === "warning" ? [low * 0.8, activeWarning ?? limit, activeWarning ?? limit]
      : profile === "danger" ? [low * 0.8, activeWarning ?? limit, limit]
      : [low * 0.6, low * 0.9, limit * 1.1, low * 0.7];
    setReadings(values.map((value, index) => ({ id: nextRowId.current++, offset: String(index * 60), value: String(Number(value.toFixed(3))), p25: "", p75: "" })));
  }

  async function play(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setError(null);
    const limits = [activeWarning, activeDanger].filter((value) => value !== null);
    if (!limits.length || limits.some((value) => !Number.isFinite(value))) {
      setError("Enter a warning or danger threshold, or select matching saved thresholds."); return;
    }
    if (activeWarning !== null && activeDanger !== null && activeDanger <= activeWarning) {
      setError("Danger threshold must exceed warning threshold."); return;
    }
    const offsets = readings.map((item) => Number(item.offset));
    if (offsets.some((offset, index) => index > 0 && offset <= offsets[index - 1])) {
      setError("Reading offsets must be unique and increase with each row."); return;
    }
    if (readings.some((item) => optionalNumber(item.p25) !== null && optionalNumber(item.p75) !== null && Number(item.p25) > Number(item.p75))) {
      setError("The lower band (p25) must not exceed the upper band (p75)."); return;
    }
    const payload = {
      name, station: stationCode, measurement, unit, start_at: new Date(startAt).toISOString(),
      level_reference: measurement === "water_level" ? reference : null, threshold_mode: thresholdMode,
      warning_threshold: thresholdMode === "custom" ? optionalNumber(warning) : null,
      danger_threshold: thresholdMode === "custom" ? optionalNumber(danger) : null,
      readings: readings.map((item) => ({ offset_minutes: Number(item.offset), value: Number(item.value), p25: optionalNumber(item.p25), p75: optionalNumber(item.p75) })),
    };
    const signature = JSON.stringify(payload);
    if (attempt.current?.signature !== signature) attempt.current = { signature, runId: crypto.randomUUID() };
    setBusy(true);
    try {
      const played = await api.playMonitoringSimulation({ ...payload, run_id: attempt.current.runId });
      setResult(played); onCompleted(played);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Simulation could not be saved. Retry Play.");
    } finally { setBusy(false); }
  }

  function newRun() {
    attempt.current = null; setResult(null); setError(null); setStartAt(localNow());
  }

  return <div className="simulation-workspace">
    <div className="simulation-workspace-header"><FlaskConical size={20} /><strong>Monitoring Scenario</strong><span className="simulated-flow-stamp">Simulated flow</span></div>
    {loading ? <div className="simulation-loading" role="status"><LoaderCircle className="spinning" size={18} /> Loading monitoring stations</div>
      : loadError ? <div className="simulation-feedback" role="alert"><span>{loadError}</span><button type="button" className="secondary-button" onClick={() => setRetry((value) => value + 1)}><RotateCcw size={16} /> Retry</button></div>
      : !stations.length ? <div className="empty-state">No monitoring stations are registered.</div>
      : <form onChange={() => setError(null)} onSubmit={(event) => void play(event)}>
        <fieldset disabled={busy || Boolean(result)}>
          <div className="simulation-fields">
            <label>Scenario name<input required maxLength={100} value={name} onChange={(event) => setName(event.target.value)} /></label>
            <label>Station<select aria-label="Station" value={stationCode} onChange={(event) => setStationCode(event.target.value)}>{stations.map((item) => <option key={item.code} value={item.code}>{item.name}{item.river ? ` / ${item.river}` : ""}</option>)}</select></label>
            <label>Measurement<select aria-label="Measurement" value={measurement} onChange={(event) => { const next = event.target.value as Measurement; setMeasurement(next); setUnit(next === "water_level" ? "m" : "cusecs"); }}>{[ ["discharge_inflow", "Discharge inflow"], ["discharge_outflow", "Discharge outflow"], ["water_level", "Water level"] ].map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label>Unit<select aria-label="Unit" value={unit} onChange={(event) => setUnit(event.target.value as Unit)}>{(measurement === "water_level" ? ["m", "ft"] : ["cusecs", "m3/s"]).map((value) => <option key={value}>{value}</option>)}</select></label>
            <label>Reading start (local time)<input type="datetime-local" required value={startAt} onChange={(event) => setStartAt(event.target.value)} /></label>
            {measurement === "water_level" && <label>Gauge datum / reference<input required maxLength={160} value={reference} onChange={(event) => setReference(event.target.value)} /></label>}
          </div>
          <div className="simulation-section-head"><h2>Thresholds</h2><div className="simulation-segments" role="group" aria-label="Threshold source"><button type="button" aria-pressed={thresholdMode === "saved"} onClick={() => setThresholdMode("saved")}>Saved thresholds</button><button type="button" aria-pressed={thresholdMode === "custom"} onClick={() => setThresholdMode("custom")}>Custom test thresholds</button></div></div>
          <div className="simulation-thresholds">
            <label>Warning ({unit}){thresholdMode === "custom" ? <input type="number" step="any" min={measurement === "water_level" ? undefined : 0} value={warning} onChange={(event) => setWarning(event.target.value)} /> : <output>{savedWarning?.toLocaleString() ?? "Not configured"}</output>}</label>
            <label>Danger ({unit}){thresholdMode === "custom" ? <input type="number" step="any" min={measurement === "water_level" ? undefined : 0} value={danger} onChange={(event) => setDanger(event.target.value)} /> : <output>{savedDanger?.toLocaleString() ?? "Not configured"}</output>}</label>
            <span className="simulation-threshold-source"><Database size={15} />{thresholdMode === "saved" ? "Monitoring database" : "Test limits"}</span>
          </div>
          {thresholdMode === "saved" && !hasThreshold && <p className="simulation-threshold-missing" role="status">No matching saved thresholds.</p>}
          <div className="simulation-section-head"><h2>Testing Readings <small>{readings.length} / 240</small></h2><label className="simulation-profile-label">Profile<select aria-label="Testing profile" value="custom" disabled={!hasThreshold} onChange={(event) => loadProfile(event.target.value)}><option value="custom">Custom readings</option><option value="normal">Below threshold</option><option value="warning">Warning crossing</option><option value="danger">Danger crossing</option><option value="surge">Surge and recovery</option></select></label></div>
          <div className="table-wrap simulation-readings"><table className="data-table"><thead><tr><th>Offset (min)</th><th>Value ({unit})</th><th>p25</th><th>p75</th><th>Expected level</th><th><span className="sr-only">Remove</span></th></tr></thead><tbody>{readings.map((item, index) => <tr key={item.id}>
            <td><input aria-label={`Reading ${index + 1} offset minutes`} type="number" required min={0} max={525600} step={1} value={item.offset} onChange={(event) => updateReading(item.id, "offset", event.target.value)} /></td>
            <td><input aria-label={`Reading ${index + 1} value`} type="number" required step="any" min={measurement === "water_level" ? undefined : 0} value={item.value} onChange={(event) => updateReading(item.id, "value", event.target.value)} /></td>
            <td><input aria-label={`Reading ${index + 1} p25`} type="number" step="any" value={item.p25} onChange={(event) => updateReading(item.id, "p25", event.target.value)} /></td>
            <td><input aria-label={`Reading ${index + 1} p75`} type="number" step="any" value={item.p75} onChange={(event) => updateReading(item.id, "p75", event.target.value)} /></td>
            <td><StatusBadge value={readingLevel(item.value)} /></td>
            <td><button type="button" className="icon-button" title="Remove reading" aria-label={`Remove reading ${index + 1}`} disabled={readings.length === 1} onClick={() => setReadings((items) => items.filter((row) => row.id !== item.id))}><Trash2 size={16} /></button></td>
          </tr>)}</tbody></table></div>
          <button type="button" className="secondary-button simulation-add-reading" disabled={readings.length >= 240} onClick={() => setReadings((items) => [...items, { id: nextRowId.current++, offset: String(Number(items.at(-1)?.offset ?? 0) + 60), value: "", p25: "", p75: "" }])}><Plus size={16} /> Add reading</button>
        </fieldset>
        {!result && <div className="simulation-playbar"><button type="submit" className="primary-button" disabled={busy || !hasThreshold}>{busy ? <LoaderCircle className="spinning" size={16} /> : <Play size={16} />}{busy ? "Saving readings" : "Play"}</button><span className="simulated-flow-stamp">Simulated flow</span></div>}
        {error && <p className="simulation-feedback" role="alert">{error}</p>}
      </form>}
    {result && <section className={`simulation-result ${result.alerts.length ? "simulation-result-alert" : ""}`} aria-label="Simulation result" aria-live="polite">
      <div className="simulation-result-heading">{result.alerts.length ? <AlertTriangle size={22} /> : <CheckCircle2 size={22} />}<div><h2>{result.alerts.length ? "Threshold reached" : "Readings saved"}</h2><span>{result.inserted} readings saved / {result.alerts.length} alerts / {result.incidents.length} incidents</span></div></div>
      {result.alerts.map((alert) => <div className="simulation-result-event" key={alert.id}><StatusBadge value={String(alert.event_metadata.threshold_level)} /><span>{alert.message}<small>{formatDateTime(String(alert.event_metadata.value_at))} / Incident #{String(alert.event_metadata.incident_id)}</small></span></div>)}
      <div className="simulation-result-actions"><button type="button" className="secondary-button" onClick={newRun}><RotateCcw size={16} /> New run</button>{result.alerts.length > 0 && <><button type="button" className="secondary-button" onClick={onOpenAlerts}>Alerts ({result.alerts.length})</button><button type="button" className="secondary-button" onClick={onOpenIncidents}>Incidents ({result.incidents.length})</button></>}</div>
    </section>}
  </div>;
}
