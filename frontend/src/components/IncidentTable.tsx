import { Eye, Siren } from "lucide-react";
import { useEffect, useState } from "react";

import type { Incident } from "../types/api";
import { formatDateTime, locationName } from "../utils/format";
import { Panel } from "./Panel";
import { StatusBadge } from "./StatusBadge";

export function IncidentTable({ incidents, full = false, initialIncidentId }: { incidents: Incident[]; full?: boolean; initialIncidentId?: number | null }) {
  const [selected, setSelected] = useState<Incident | null>(null);
  useEffect(() => {
    if (initialIncidentId) setSelected(incidents.find((incident) => incident.id === initialIncidentId) ?? null);
  }, [initialIncidentId, incidents]);
  const visible = full ? incidents : incidents.slice(0, 6);
  return (
    <Panel title="Incident Operations" icon={Siren} action={<span className="count-label">{incidents.length} records</span>}>
      {!visible.length ? <div className="empty-state">No incidents have been recorded.</div> : (
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>Location</th><th>Severity</th><th>Status</th><th>Confidence</th><th>Source</th><th>Created</th><th><span className="sr-only">Action</span></th></tr></thead>
            <tbody>{visible.map((incident) => (
              <tr key={incident.id}>
                <td><strong>{locationName(incident.location_id)}</strong><small>#{incident.id}</small></td>
                <td><StatusBadge value={incident.severity} /></td>
                <td><StatusBadge value={incident.status} subtle /></td>
                <td>{Math.round(incident.confidence * 100)}%</td>
                <td>{incident.source === "SIMULATED_FLOW" ? <span className="simulated-flow-stamp">Simulated flow</span> : incident.source}</td>
                <td>{formatDateTime(incident.created_at)}</td>
                <td><button className="icon-button" title="View incident" onClick={() => setSelected(incident)}><Eye size={17} /></button></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
      {selected && (
        <div className="detail-drawer" role="dialog" aria-label={`Incident ${selected.id} details`}>
          <div><span>Incident #{selected.id} {selected.source === "SIMULATED_FLOW" && <span className="simulated-flow-stamp">Simulated flow</span>}</span><button className="text-button" onClick={() => setSelected(null)}>Close</button></div>
          <h3>{selected.description}</h3>
          <dl><dt>Location</dt><dd>{locationName(selected.location_id)}</dd><dt>Type</dt><dd>{selected.type}</dd><dt>Updated</dt><dd>{formatDateTime(selected.updated_at)}</dd></dl>
        </div>
      )}
    </Panel>
  );
}
