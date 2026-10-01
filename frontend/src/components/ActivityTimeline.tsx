import { Activity, AlertTriangle, BellRing, CircleDot, Radio, UserRoundCheck } from "lucide-react";

import type { SystemEvent } from "../types/api";
import { formatRelativeTime, locationName } from "../utils/format";
import { Panel } from "./Panel";

const eventIcons = {
  RISK_UPDATED: Activity,
  MONITORING_MODE_CHANGED: Radio,
  INCIDENT_CREATED: AlertTriangle,
  CITIZEN_REPORT_RECEIVED: UserRoundCheck,
  INCIDENT_CONFIRMED: BellRing,
  ALERT_REQUIRED: BellRing,
};

export function ActivityTimeline({ events, full = false }: { events: SystemEvent[]; full?: boolean }) {
  const visible = full ? events : events.slice(0, 7);
  return (
    <Panel title="System Activity" icon={Activity} action={<span className="live-label"><i /> Live event stream</span>}>
      {!visible.length ? <div className="empty-state">No system events recorded.</div> : (
        <div className="timeline">
          {visible.map((event) => {
            const Icon = eventIcons[event.event_type as keyof typeof eventIcons] ?? CircleDot;
            return <article key={event.id}>
              <div className={`timeline-icon event-${event.event_type.toLowerCase()}`}><Icon size={15} /></div>
              <div><div><strong>{event.event_type.replaceAll("_", " ")}</strong><span>{formatRelativeTime(event.timestamp)}</span></div><p>{event.message}</p><small>{locationName(event.location_id)}</small></div>
            </article>;
          })}
        </div>
      )}
    </Panel>
  );
}
