import { Activity, AlertTriangle, Clock3, Radio, Siren, Users } from "lucide-react";

import type { DashboardSummary } from "../types/api";

interface KpiGridProps {
  summary: DashboardSummary | null;
  currentRisk: number | null;
  monitoringInterval: number | null;
}

export function KpiGrid({ summary, currentRisk, monitoringInterval }: KpiGridProps) {
  const items = [
    { label: "Current highest risk", value: currentRisk === null ? "—" : `${Math.round(currentRisk * 100)}%`, icon: Activity, tone: "risk" },
    { label: "Active incidents", value: summary?.active_incidents ?? "—", icon: Siren, tone: "neutral" },
    { label: "Critical incidents", value: summary?.critical_incidents ?? "—", icon: AlertTriangle, tone: "critical" },
    { label: "Confirmed floods", value: summary?.confirmed_floods ?? "—", icon: Radio, tone: "warning" },
    { label: "Pending citizen reports", value: summary?.pending_citizen_reports ?? "—", icon: Users, tone: "neutral" },
    { label: "Monitoring interval", value: monitoringInterval === null ? "—" : `${monitoringInterval} min`, icon: Clock3, tone: "monitor" },
  ];

  return (
    <section className="kpi-grid" aria-label="Operational summary">
      {items.map(({ label, value, icon: Icon, tone }) => (
        <article className={`kpi-card kpi-${tone}`} key={label}>
          <div className="kpi-icon"><Icon size={18} aria-hidden="true" /></div>
          <div><span>{label}</span><strong>{value}</strong></div>
        </article>
      ))}
    </section>
  );
}
