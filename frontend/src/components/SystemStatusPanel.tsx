import { CircleCheck, ServerCog } from "lucide-react";

import type { SystemStatus } from "../types/api";
import { Panel } from "./Panel";
import { StatusBadge } from "./StatusBadge";

export function SystemStatusPanel({ system }: { system: SystemStatus | null }) {
  return (
    <Panel title="System Status" icon={ServerCog}>
      {!system ? <div className="empty-state">System status unavailable.</div> : (
        <div className="system-status-grid">
          <div className="system-mode"><span>Data mode</span><StatusBadge value={system.data_mode} /></div>
          <div><span>Backend</span><strong className="healthy"><CircleCheck size={15} /> {system.backend_status}</strong></div>
          <div><span>Active scenario</span><strong>{system.active_scenario.replaceAll("_", " ")}</strong></div>
          <div><span>Monitoring mode</span><strong>{system.monitoring_mode}</strong></div>
          <div><span>Polling recommendation</span><strong>{system.monitoring_interval_minutes} minutes</strong></div>
          <div><span>Simulation</span><strong>{system.simulation_enabled ? "Enabled" : "Disabled"}</strong></div>
          <div><span>Model fallback</span><strong>{system.rule_based_fallback_enabled ? "Enabled" : "Disabled"}</strong></div>
          <div><span>Risk model</span><strong>{system.ml_model_enabled ? "Development XGBoost" : "Rule engine / live inputs"}</strong></div>
        </div>
      )}
    </Panel>
  );
}
