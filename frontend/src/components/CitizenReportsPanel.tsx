import { MapPin, MessageSquareText, Ruler } from "lucide-react";

import type { CitizenReport } from "../types/api";
import { formatRelativeTime, locationName } from "../utils/format";
import { Panel } from "./Panel";
import { StatusBadge } from "./StatusBadge";

export function CitizenReportsPanel({ reports, full = false }: { reports: CitizenReport[]; full?: boolean }) {
  const visible = (full ? reports : reports.slice(0, 5));
  return (
    <Panel title="Citizen Reports" icon={MessageSquareText} action={<span className="count-label">{reports.length} received</span>}>
      {!visible.length ? <div className="empty-state">No citizen reports received.</div> : (
        <div className="report-list">
          {visible.map((report) => (
            <article key={report.id}>
              <div className="report-head"><div><MapPin size={15} /><strong>{locationName(report.location_id)}</strong><span>{formatRelativeTime(report.timestamp)}</span></div><StatusBadge value={report.verification_status} subtle /></div>
              <p>{report.description}</p>
              {report.reported_water_depth_cm !== null && <div className="depth-label"><Ruler size={14} /> Reported depth: {report.reported_water_depth_cm} cm</div>}
            </article>
          ))}
        </div>
      )}
    </Panel>
  );
}
