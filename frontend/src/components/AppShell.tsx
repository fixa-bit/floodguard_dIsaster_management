import { Activity, AlertTriangle, LayoutDashboard, Map, Menu, MessageSquareText, ShieldCheck, X, FlaskConical } from "lucide-react";
import { useState, type ReactNode } from "react";

export type ViewId = "overview" | "gis" | "incidents" | "reports" | "activity" | "simulation";

const navItems = [
  { id: "overview" as const, label: "Overview", icon: LayoutDashboard },
  { id: "gis" as const, label: "GIS Operations", icon: Map },
  { id: "incidents" as const, label: "Incidents", icon: AlertTriangle },
  { id: "reports" as const, label: "Citizen Reports", icon: MessageSquareText },
  { id: "activity" as const, label: "System Activity", icon: Activity },
  { id: "simulation" as const, label: "Simulation", icon: FlaskConical },
];

export function AppShell({ activeView, onViewChange, children }: { activeView: ViewId; onViewChange: (view: ViewId) => void; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="app-shell">
      <aside className={`sidebar ${open ? "sidebar-open" : ""}`}>
        <div className="brand-lockup"><div><ShieldCheck size={24} /></div><span><strong>FloodGuard AI</strong><small>NDMA Command Screen</small></span><button className="mobile-close" onClick={() => setOpen(false)}><X size={20} /></button></div>
        <nav>{navItems.map(({ id, label, icon: Icon }) => <button className={activeView === id ? "active" : ""} key={id} onClick={() => { onViewChange(id); setOpen(false); }}><Icon size={18} /><span>{label}</span></button>)}</nav>
        <div className="sidebar-foot"><span>National display mode</span><strong>Pakistan Region</strong></div>
      </aside>
      {open && <button className="sidebar-backdrop" aria-label="Close navigation" onClick={() => setOpen(false)} />}
      <main className="main-content"><button className="mobile-menu" onClick={() => setOpen(true)}><Menu size={20} /> Menu</button>{children}</main>
    </div>
  );
}
