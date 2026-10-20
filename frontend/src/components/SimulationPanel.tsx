import { AlertTriangle, CheckCircle2, Database, FlaskConical, LoaderCircle, Play, Plus, RotateCcw, Trash2 } from "lucide-react";
import { lazy, Suspense, useEffect, useRef, useState, type FormEvent } from "react";

import { ApiError, api } from "../services/api";
import type { MonitoringSimulationRequest, MonitoringSimulationResult, SimulationStation } from "../types/api";
import { formatDateTime } from "../utils/format";
import { StatusBadge } from "./StatusBadge";
import "../simulation.css";

type DraftReading = { id: number; offset: string; value: string; p25: string; p75: string };
type Measurement = MonitoringSimulationRequest["measurement"];
type Unit = MonitoringSimulationRequest["unit"];
const FloodVisualization = lazy(() => import("./SimulationFloodVisualization").then((module) => ({ default: module.SimulationFloodVisualization })));
const StormReplay = lazy(() => import("./SimulationReplayWorkspace").then((module) => ({ default: module.SimulationReplayWorkspace })));
const simulationViews = ["monitoring", "spread", "replay"] as const;

const scenarioNames = ["Flood threshold test", "Below threshold test", "Warning crossing test", "Danger crossing test", "Surge and recovery test"];
const sliderLimits = { cusecs: { min: 0, max: 1000000, step: 1000 }, "m3/s": { min: 0, max: 30000, step: 10 }, m: { min: -20, max: 50, step: 0.1 }, ft: { min: -60, max: 160, step: 0.1 } };

function localNow(minutes = 0) {
  const now = new Date(Date.now() + minutes * 60000);
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function optionalNumber(value: string) {
  return value.trim() === "" ? null : Number(value);
}

function NumberSlider({ label, value, onChange, min, max, step, optional = false, defaultValue = 0, suffix = "" }: {
  label: string; value: string; onChange: (value: string) => void;
  min: number; max: number; step: number; optional?: boolean; defaultValue?: number; suffix?: string;
}) {
  const enabled = !optional || value !== "";
  const current = value === "" ? defaultValue : Number(value);
  const lower = Math.min(min, current);
  const upper = Math.max(max, current);
  const change = (next: number) => onChange(String(Number(Math.max(lower, Math.min(upper, next)).toFixed(step < 1 ? 3 : 0))));
  return <div className={`simulation-slider-field ${enabled ? "" : "simulation-slider-off"}`}>
    <div className="simulation-slider-heading"><span>{label}</span><output aria-label={`${label} selected value`}>{enabled ? `${current.toLocaleString(undefined, { maximumFractionDigits: 3 })}${suffix ? ` ${suffix}` : ""}` : "Not set"}</output></div>
    <div className="simulation-slider-controls">
      <button type="button" aria-label={`Decrease ${label}`} disabled={!enabled || current <= lower} onClick={() => change(current - step)}>−</button>
      <input aria-label={label} aria-valuetext={enabled ? `${current} ${suffix}`.trim() : "Not set"} type="range" min={lower} max={upper} step="any" value={current} disabled={!enabled} onChange={(event) => change(Number(event.target.value))} />
      <button type="button" aria-label={`Increase ${label}`} disabled={!enabled || current >= upper} onClick={() => change(current + step)}>+</button>
    </div>
    {optional && <label className="simulation-slider-enable"><input type="checkbox" aria-label={`Enable ${label}`} checked={enabled} onChange={(event) => onChange(event.target.checked ? String(defaultValue) : "")} /> Include {label.toLowerCase()}</label>}
  </div>;
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
  const [customName, setCustomName] = useState(false);
  const [stationCode, setStationCode] = useState("TAUNSA");
  const [measurement, setMeasurement] = useState<Measurement>("discharge_inflow");
  const [unit, setUnit] = useState<Unit>("cusecs");
  const [startAt, setStartAt] = useState(localNow);
  const [startPreset, setStartPreset] = useState("now");
  const [reference, setReference] = useState("");
  const [customReference, setCustomReference] = useState(false);
  const [rangeScale, setRangeScale] = useState(1);
  const [offsetWindow, setOffsetWindow] = useState(1440);
  const [profile, setProfile] = useState("custom");
  const [thresholdMode, setThresholdMode] = useState<"saved" | "custom">("saved");
  const [warning, setWarning] = useState("");
  const [danger, setDanger] = useState("");
  const [readings, setReadings] = useState<DraftReading[]>([{ id: 0, offset: "0", value: "0", p25: "", p75: "" }]);
  const nextRowId = useRef(1);
  const attempt = useRef<{ signature: string; runId: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<MonitoringSimulationResult | null>(null);
  const [workspaceView, setWorkspaceView] = useState<typeof simulationViews[number]>("monitoring");

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
  const references = [...new Set((station?.thresholds ?? []).filter((item) => item.measurement === "water_level" && item.level_reference).map((item) => item.level_reference!))];
  const referenceOptions = [...new Set([...references, "Local gauge datum (test)", "Mean sea level (test)"])];
  useEffect(() => {
    if (measurement === "water_level" && !customReference) setReference(references[0] ?? "Local gauge datum (test)");
  }, [stationCode, measurement, stations, customReference]);
  const saved = station?.thresholds.filter((item) => item.measurement === measurement && item.unit === unit &&
    ["warning", "danger"].includes(item.level) && item.value !== null &&
    (measurement !== "water_level" || Boolean(item.level_reference) && item.level_reference === reference)) ?? [];
  const savedWarning = saved.find((item) => item.level === "warning")?.value ?? null;
  const savedDanger = saved.find((item) => item.level === "danger")?.value ?? null;
  const activeWarning = thresholdMode === "saved" ? savedWarning : optionalNumber(warning);
  const activeDanger = thresholdMode === "saved" ? savedDanger : optionalNumber(danger);
  const hasThreshold = activeWarning !== null || activeDanger !== null;
  const limits = sliderLimits[unit];
  const valueMax = Math.max(limits.max, (savedWarning ?? 0) * 1.5, (savedDanger ?? 0) * 1.5) * rangeScale;
  const sliderProps = { min: limits.min, max: valueMax, step: limits.step, suffix: unit };

  function changeMeasurement(next: Measurement, nextUnit: Unit) {
    setMeasurement(next); setUnit(nextUnit); setRangeScale(1); setProfile("custom");
    const nextLimits = sliderLimits[nextUnit];
    setWarning(warning === "" ? "" : String(nextLimits.max * 0.3));
    setDanger(danger === "" ? "" : String(nextLimits.max * 0.6));
    setReadings((items) => items.map((item) => ({ ...item, value: "0", p25: "", p75: "" })));
  }

  function useCustomThresholds() {
    setThresholdMode("custom");
    if (warning === "") setWarning(String(savedWarning ?? limits.max * 0.3));
    if (danger === "") setDanger(String(savedDanger ?? limits.max * 0.6));
  }

  function updateReading(id: number, field: keyof Omit<DraftReading, "id">, value: string) {
    setProfile("custom");
    setReadings((items) => items.map((item) => item.id === id ? { ...item, [field]: value } : item));
  }

  function readingLevel(value: string) {
    if (value.trim() === "") return "Pending";
    if (activeDanger !== null && Number(value) >= activeDanger) return "Danger";
    if (activeWarning !== null && Number(value) >= activeWarning) return "Warning";
    return hasThreshold ? "Normal" : "No threshold";
  }

  function loadProfile(profile: string) {
    setProfile(profile);
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
      setError("Enable a warning or danger threshold, or select matching saved thresholds."); return;
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
    attempt.current = null; setResult(null); setError(null); setStartAt(localNow()); setStartPreset("now");
  }

  return <div className="simulation-workspace">
    <div className="simulation-workspace-header"><FlaskConical size={20} /><strong>{workspaceView === "monitoring" ? "Monitoring Scenario" : workspaceView === "spread" ? "Flood spread & population" : "Storm replay"}</strong><span className="simulated-flow-stamp">Simulated flow</span></div>
    <div className="simulation-workspace-tabs" role="tablist" aria-label="Simulation views" onKeyDown={(event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === "Home" ? simulationViews[0] : event.key === "End" ? simulationViews.at(-1)! : simulationViews[(simulationViews.indexOf(workspaceView) + (event.key === "ArrowRight" ? 1 : -1) + simulationViews.length) % simulationViews.length];
      setWorkspaceView(next); document.getElementById(`simulation-tab-${next}`)?.focus();
    }}>
      <button type="button" role="tab" id="simulation-tab-monitoring" data-tour-target="simulation-monitoring" aria-controls="simulation-panel-monitoring" aria-selected={workspaceView === "monitoring"} tabIndex={workspaceView === "monitoring" ? 0 : -1} onClick={() => setWorkspaceView("monitoring")}>Monitoring scenario</button>
      <button type="button" role="tab" id="simulation-tab-spread" data-tour-target="simulation-spread" aria-controls="simulation-panel-spread" aria-selected={workspaceView === "spread"} tabIndex={workspaceView === "spread" ? 0 : -1} onClick={() => setWorkspaceView("spread")}>Flood spread &amp; population</button>
      <button type="button" role="tab" id="simulation-tab-replay" data-tour-target="simulation-replay" aria-controls="simulation-panel-replay" aria-selected={workspaceView === "replay"} tabIndex={workspaceView === "replay" ? 0 : -1} onClick={() => setWorkspaceView("replay")}>Storm replay</button>
    </div>
    <section role="tabpanel" id="simulation-panel-monitoring" aria-labelledby="simulation-tab-monitoring" hidden={workspaceView !== "monitoring"}>
    {loading ? <div className="simulation-loading" role="status"><LoaderCircle className="spinning" size={18} /> Loading monitoring stations</div>
      : loadError ? <div className="simulation-feedback" role="alert"><span>{loadError}</span><button type="button" className="secondary-button" onClick={() => setRetry((value) => value + 1)}><RotateCcw size={16} /> Retry</button></div>
      : !stations.length ? <div className="empty-state">No monitoring stations are registered.</div>
      : <form onChange={() => setError(null)} onSubmit={(event) => void play(event)}>
        <fieldset disabled={busy || Boolean(result)}>
          <div className="simulation-fields">
            <div className="simulation-selector-field"><label>Scenario name<select aria-label="Scenario name" value={customName ? "custom" : name} onChange={(event) => { setCustomName(event.target.value === "custom"); if (event.target.value !== "custom") setName(event.target.value); }}>{scenarioNames.map((item) => <option key={item}>{item}</option>)}<option value="custom">Custom name</option></select></label>{customName && <input aria-label="Custom scenario name" required maxLength={100} value={name} onChange={(event) => setName(event.target.value)} />}</div>
            <label>Station<select data-tour-target="tour-sim-station" aria-label="Station" value={stationCode} onChange={(event) => setStationCode(event.target.value)}>{stations.map((item) => <option key={item.code} value={item.code}>{item.name}{item.river ? ` / ${item.river}` : ""}</option>)}</select></label>
            <label>Measurement<select aria-label="Measurement" value={measurement} onChange={(event) => { const next = event.target.value as Measurement; changeMeasurement(next, next === "water_level" ? "m" : "cusecs"); }}>{[ ["discharge_inflow", "Discharge inflow"], ["discharge_outflow", "Discharge outflow"], ["water_level", "Water level"] ].map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label>Unit<select aria-label="Unit" value={unit} onChange={(event) => changeMeasurement(measurement, event.target.value as Unit)}>{(measurement === "water_level" ? ["m", "ft"] : ["cusecs", "m3/s"]).map((value) => <option key={value}>{value}</option>)}</select></label>
            <div className="simulation-selector-field"><label>Reading start (local time)<select aria-label="Reading start (local time)" value={startPreset} onChange={(event) => { setStartPreset(event.target.value); if (event.target.value !== "custom") setStartAt(localNow(Number(event.target.value) || 0)); }}><option value="now">Now</option><option value="15">In 15 minutes</option><option value="60">In 1 hour</option><option value="custom">Choose date and time</option></select></label>{startPreset === "custom" ? <input aria-label="Custom reading start" type="datetime-local" required value={startAt} onChange={(event) => setStartAt(event.target.value)} /> : <small>{formatDateTime(new Date(startAt).toISOString())}</small>}</div>
            {measurement === "water_level" && <div className="simulation-selector-field"><label>Gauge datum / reference<select aria-label="Gauge datum / reference" value={customReference ? "custom" : reference} onChange={(event) => { setCustomReference(event.target.value === "custom"); if (event.target.value !== "custom") setReference(event.target.value); }}>{referenceOptions.map((item) => <option key={item}>{item}</option>)}<option value="custom">Custom reference</option></select></label>{customReference && <input aria-label="Custom gauge datum / reference" required maxLength={160} value={reference} onChange={(event) => setReference(event.target.value)} />}</div>}
            <label>Slider range<select aria-label="Slider range" value={rangeScale} onChange={(event) => setRangeScale(Number(event.target.value))}><option value={1}>Standard range</option><option value={5}>Extended range (5×)</option></select></label>
            <label>Reading window<select aria-label="Reading window" value={offsetWindow} onChange={(event) => setOffsetWindow(Number(event.target.value))}><option value={1440}>24 hours</option><option value={10080}>7 days</option><option value={43200}>30 days</option><option value={525600}>1 year</option></select></label>
          </div>
          <p className="simulation-control-hint">Drag sliders to set values; use − / + for smaller adjustments. Changing measurement or unit resets reading values and bands.</p>
          <div className="simulation-section-head"><h2>Thresholds</h2><div className="simulation-segments" role="group" aria-label="Threshold source"><button type="button" aria-pressed={thresholdMode === "saved"} onClick={() => setThresholdMode("saved")}>Saved thresholds</button><button type="button" aria-pressed={thresholdMode === "custom"} onClick={useCustomThresholds}>Custom test thresholds</button></div></div>
          <div className="simulation-thresholds">
            {thresholdMode === "custom" ? <NumberSlider label={`Warning (${unit})`} value={warning} onChange={setWarning} {...sliderProps} optional defaultValue={savedWarning ?? limits.max * 0.3} /> : <label>Warning ({unit})<output>{savedWarning?.toLocaleString() ?? "Not configured"}</output></label>}
            {thresholdMode === "custom" ? <NumberSlider label={`Danger (${unit})`} value={danger} onChange={setDanger} {...sliderProps} optional defaultValue={savedDanger ?? limits.max * 0.6} /> : <label>Danger ({unit})<output>{savedDanger?.toLocaleString() ?? "Not configured"}</output></label>}
            <span className="simulation-threshold-source"><Database size={15} />{thresholdMode === "saved" ? "Monitoring database" : "Test limits"}</span>
          </div>
          {thresholdMode === "saved" && !hasThreshold && <p className="simulation-threshold-missing" role="status">No matching saved thresholds.</p>}
          <div className="simulation-section-head"><h2>Testing Readings <small>{readings.length} / 240</small></h2><label className="simulation-profile-label">Profile<select aria-label="Testing profile" value={profile} disabled={!hasThreshold} onChange={(event) => loadProfile(event.target.value)}><option value="custom">Custom readings</option><option value="normal">Below threshold</option><option value="warning">Warning crossing</option><option value="danger">Danger crossing</option><option value="surge">Surge and recovery</option></select></label></div>
          <div className="table-wrap simulation-readings"><table className="data-table"><thead><tr><th>Offset (min)</th><th>Value ({unit})</th><th>p25</th><th>p75</th><th>Expected level</th><th><span className="sr-only">Remove</span></th></tr></thead><tbody>{readings.map((item, index) => <tr key={item.id}>
            <td><NumberSlider label={`Reading ${index + 1} offset minutes`} value={item.offset} onChange={(value) => updateReading(item.id, "offset", value)} min={0} max={Math.min(525600, Math.max(offsetWindow, ...readings.map((row) => Number(row.offset))))} step={1} suffix="min" /></td>
            <td><NumberSlider label={`Reading ${index + 1} value`} value={item.value} onChange={(value) => updateReading(item.id, "value", value)} {...sliderProps} /></td>
            <td><NumberSlider label={`Reading ${index + 1} p25`} value={item.p25} onChange={(value) => updateReading(item.id, "p25", value)} {...sliderProps} optional defaultValue={Number((Number(item.value) * 0.9).toFixed(3))} /></td>
            <td><NumberSlider label={`Reading ${index + 1} p75`} value={item.p75} onChange={(value) => updateReading(item.id, "p75", value)} {...sliderProps} optional defaultValue={Number((Number(item.value) * 1.1).toFixed(3))} /></td>
            <td><StatusBadge value={readingLevel(item.value)} /></td>
            <td><button type="button" className="icon-button" title="Remove reading" aria-label={`Remove reading ${index + 1}`} disabled={readings.length === 1} onClick={() => { setProfile("custom"); setReadings((items) => items.filter((row) => row.id !== item.id)); }}><Trash2 size={16} /></button></td>
          </tr>)}</tbody></table></div>
          <button type="button" className="secondary-button simulation-add-reading" disabled={readings.length >= 240 || Number(readings.at(-1)?.offset ?? 0) + 60 > 525600} onClick={() => { setProfile("custom"); setReadings((items) => [...items, { id: nextRowId.current++, offset: String(Number(items.at(-1)?.offset ?? 0) + 60), value: items.at(-1)?.value ?? "0", p25: "", p75: "" }]); }}><Plus size={16} /> Add reading</button>
        </fieldset>
        {!result && <div className="simulation-playbar"><button type="submit" className="primary-button" disabled={busy || !hasThreshold}>{busy ? <LoaderCircle className="spinning" size={16} /> : <Play size={16} />}{busy ? "Saving readings" : "Play"}</button><span className="simulated-flow-stamp">Simulated flow</span></div>}
        {error && <p className="simulation-feedback" role="alert">{error}</p>}
      </form>}
    {result && <section className={`simulation-result ${result.alerts.length ? "simulation-result-alert" : ""}`} aria-label="Simulation result" aria-live="polite">
      <div className="simulation-result-heading">{result.alerts.length ? <AlertTriangle size={22} /> : <CheckCircle2 size={22} />}<div><h2>{result.alerts.length ? "Threshold reached" : "Readings saved"}</h2><span>{result.inserted} readings saved / {result.alerts.length} alerts awaiting review / {result.incidents.length} incidents</span></div></div>
      {result.alerts.map((alert) => <div className="simulation-result-event" key={alert.id}><StatusBadge value={String(alert.event_metadata.threshold_level)} /><span>{alert.message}<small>{formatDateTime(String(alert.event_metadata.value_at))} / Pending approval in Alerts</small></span></div>)}
      <div className="simulation-result-actions"><button type="button" className="secondary-button" onClick={newRun}><RotateCcw size={16} /> New run</button>{result.alerts.length > 0 && <button type="button" className="secondary-button" onClick={onOpenAlerts}>Review alerts ({result.alerts.length})</button>}{result.incidents.length > 0 && <button type="button" className="secondary-button" onClick={onOpenIncidents}>Incidents ({result.incidents.length})</button>}</div>
    </section>}
    </section>
    <section role="tabpanel" id="simulation-panel-spread" aria-labelledby="simulation-tab-spread" hidden={workspaceView !== "spread"}>
      {workspaceView === "spread" && <Suspense fallback={<div className="simulation-loading" role="status">Loading flood-spread visualization…</div>}><FloodVisualization stationName={station?.name ?? stationCode} /></Suspense>}
    </section>
    <section role="tabpanel" id="simulation-panel-replay" aria-labelledby="simulation-tab-replay" hidden={workspaceView !== "replay"}>
      {workspaceView === "replay" && <Suspense fallback={<div className="simulation-loading" role="status">Loading storm replay…</div>}><StormReplay /></Suspense>}
    </section>
  </div>;
}
