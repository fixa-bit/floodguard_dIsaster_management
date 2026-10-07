import { Activity, AlertTriangle, CloudRain, LayoutDashboard, Map, Menu, MessageSquareText, ShieldCheck, X, FlaskConical, ChartNoAxesCombined, Waves } from "lucide-react";
import { useState, type ReactNode } from "react";

export type ViewId = "overview" | "gis" | "rainfall" | "predictive" | "upstream" | "incidents" | "reports" | "activity" | "simulation";

const navItems = [
  { id: "overview" as const, label: "Overview", icon: LayoutDashboard },
  { id: "gis" as const, label: "GIS Operations", icon: Map },
  { id: "predictive" as const, label: "Predictive Risk Views", icon: ChartNoAxesCombined },
  { id: "upstream" as const, label: "Upstream Source Flood Watch", icon: Waves },
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
        <nav aria-label="Main navigation">
          {navItems.map(({ id, label, icon: Icon }) => <button className={activeView === id ? "active" : ""} aria-current={activeView === id ? "page" : undefined} key={id} onClick={() => { onViewChange(id); setOpen(false); }}><Icon size={18} /><span>{label}</span></button>)}
          <p className="sidebar-section-label">Feature visualization</p>
          <button className={activeView === "rainfall" ? "active" : ""} aria-current={activeView === "rainfall" ? "page" : undefined} onClick={() => { onViewChange("rainfall"); setOpen(false); }}><CloudRain size={18} /><span>Rainfall heatmap</span></button>
        </nav>
        <div className="sidebar-foot"><span>National display mode</span><strong>Pakistan Region</strong></div>
      </aside>
      {open && <button className="sidebar-backdrop" aria-label="Close navigation" onClick={() => setOpen(false)} />}
      <main className={`main-content main-${activeView}`}><button className="mobile-menu" onClick={() => setOpen(true)}><Menu size={20} /> Menu</button>{children}</main>
    </div>
  );
}
