import { BellRing, ExternalLink } from "lucide-react";
import { useState } from "react";

import type { SystemEvent } from "../types/api";
import { formatDateTime, locationName } from "../utils/format";
import { Panel } from "./Panel";
import { StatusBadge } from "./StatusBadge";
import "../simulation.css";

export function AlertTable({ alerts, onOpenIncident }: { alerts: SystemEvent[]; onOpenIncident: (id: number) => void }) {
  const [filter, setFilter] = useState("all");
  const simulated = (alert: SystemEvent) => alert.event_metadata.source === "SIMULATED_FLOW";
  const visible = alerts.filter((alert) => filter === "all" || (filter === "simulated" ? simulated(alert) : !simulated(alert)));
  return <Panel title="Alerts" icon={BellRing} action={<span className="count-label">{visible.length} records</span>}>
    <div className="simulation-segments alert-filters" role="group" aria-label="Alert source">{[["all", "All"], ["operational", "Operational"], ["simulated", "Simulated flow"]].map(([value, label]) => <button type="button" key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}>{label}</button>)}</div>
    {!visible.length ? <div className="empty-state">No alerts recorded.</div> : <div className="table-wrap"><table className="data-table alerts-table"><thead><tr><th>Station / Location</th><th>Severity</th><th>Alert</th><th>Source</th><th>Recorded</th><th>Incident</th></tr></thead><tbody>{visible.map((alert) => {
      const metadata = alert.event_metadata;
      const incidentId = typeof metadata.incident_id === "number" ? metadata.incident_id : null;
      return <tr key={alert.id}><td><strong>{String(metadata.station_name ?? locationName(alert.location_id))}</strong><small>Alert #{alert.id}</small></td><td><StatusBadge value={String(metadata.severity ?? "CRITICAL")} /></td><td className="alert-message">{alert.message}{typeof metadata.threshold_value === "number" && <small>{String(metadata.threshold_level)}: {metadata.threshold_value.toLocaleString()} {String(metadata.unit)} / {metadata.threshold_mode === "custom" ? "Test limit" : "Saved threshold"}</small>}</td><td>{simulated(alert) ? <span className="simulated-flow-stamp">Simulated flow</span> : "Monitoring"}</td><td>{formatDateTime(alert.timestamp)}</td><td>{incidentId !== null ? <button type="button" className="alert-incident-link" onClick={() => onOpenIncident(incidentId)} title={`Open incident ${incidentId}`}><ExternalLink size={14} />#{incidentId}</button> : <span>No linked incident</span>}</td></tr>;
    })}</tbody></table></div>}
  </Panel>;
}
