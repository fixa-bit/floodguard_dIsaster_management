import { FastForward, FlaskConical, RotateCcw, Play } from "lucide-react";
import { useEffect, useState } from "react";

import { LOCATIONS, SCENARIOS, type Scenario } from "../config";
import { ApiError, api } from "../services/api";
import type { SimulationStatus, SystemStatus } from "../types/api";
import { Panel } from "./Panel";

interface SimulationPanelProps {
  status: SimulationStatus | null;
  system: SystemStatus | null;
  selectedLocation: string;
  onChanged: () => Promise<unknown> | void;
}

export function SimulationPanel({ status, system, selectedLocation, onChanged }: SimulationPanelProps) {
  const [scenario, setScenario] = useState<Scenario>("HEAVY_RAIN");
  const [location, setLocation] = useState(selectedLocation);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => setLocation(selectedLocation), [selectedLocation]);

  async function action(operation: () => Promise<SimulationStatus>) {
    setBusy(true); setError(null);
    try { await operation(); await onChanged(); }
    catch (reason) { setError(reason instanceof ApiError ? reason.message : "Simulation action failed"); }
    finally { setBusy(false); }
  }

  const isSimulationMode = system?.data_mode === "simulation";
  const simulationEnabled = system?.simulation_enabled === true;
  return (
    <Panel title="Simulation Control" icon={FlaskConical}>
      <div className={`simulation-context ${isSimulationMode ? "simulation-active" : "simulation-isolated"}`}>
        <strong>{isSimulationMode ? "SIMULATION MODE ACTIVE" : simulationEnabled ? "LIVE FEEDS REMAIN ACTIVE" : "SIMULATION DISABLED"}</strong>
        <span>{isSimulationMode ? "Risk and environmental readings use deterministic scenario data." : simulationEnabled ? "Scenario controls are isolated from live operational feeds." : "This deployment accepts real provider data only."}</span>
      </div>
      <div className="simulation-form">
        <label>Scenario<select value={scenario} onChange={(event) => setScenario(event.target.value as Scenario)}>{SCENARIOS.map((item) => <option key={item}>{item}</option>)}</select></label>
        <label>Location<select value={location} onChange={(event) => setLocation(event.target.value)}>{LOCATIONS.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
      </div>
      <div className="simulation-actions">
        <button className="primary-button" disabled={busy || !simulationEnabled} onClick={() => void action(() => api.startSimulation(scenario, location))}><Play size={16} /> Start</button>
        <button className="secondary-button" disabled={busy || !simulationEnabled} onClick={() => void action(api.advanceSimulation)}><FastForward size={16} /> Advance</button>
        <button className="secondary-button" disabled={busy || !simulationEnabled} onClick={() => void action(api.resetSimulation)}><RotateCcw size={16} /> Reset</button>
      </div>
      {error && <p className="inline-error">{error}</p>}
      {status && <div className="simulation-current"><span>Configured scenario</span><strong>{status.scenario.replaceAll("_", " ")}</strong><small>{status.location_id} · {status.monitoring_interval_minutes} min monitoring</small></div>}
    </Panel>
  );
}
