import { Building2, Hospital, PhoneCall, UsersRound } from "lucide-react";

import type { ResourceGroups } from "../types/api";
import { locationName } from "../utils/format";
import { Panel } from "./Panel";

export function ResourcesPanel({ resources, locationId }: { resources: ResourceGroups; locationId: string }) {
  const rows = [
    ...resources.shelters.map((resource) => ({ ...resource, icon: UsersRound })),
    ...resources.hospitals.map((resource) => ({ ...resource, icon: Hospital })),
    ...resources.contacts.map((resource) => ({ ...resource, icon: PhoneCall })),
  ].filter((resource) => resource.location_id === locationId || resource.resource_type === "emergency_contact");
  return (
    <Panel title="Emergency Resources" icon={Building2}>
      {!rows.length ? <div className="empty-state">No resources configured for this location.</div> : (
        <div className="resource-list">{rows.map(({ icon: Icon, ...resource }) => (
          <article key={resource.id}><Icon size={18} /><div><strong>{resource.name}</strong><span>{resource.address} · {locationName(resource.location_id)}</span></div><div>{resource.phone && <a href={`tel:${resource.phone}`}>{resource.phone}</a>}{resource.capacity && <small>Capacity {resource.capacity}</small>}</div></article>
        ))}</div>
      )}
    </Panel>
  );
}
