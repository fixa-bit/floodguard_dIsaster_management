import { Activity, AlertTriangle, FileText, BellRing, CloudRain, ExternalLink, LayoutDashboard, Map, Menu, MessageSquareText, ShieldCheck, X, FlaskConical, ChartNoAxesCombined, Waves, Droplets, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useEffect, useRef, useState, type FocusEvent, type MouseEvent, type ReactNode } from "react";

export type ViewId = "overview" | "gis" | "rainfall" | "predictive" | "riverine-forecast" | "upstream" | "monitoring" | "alerts" | "incidents" | "reports" | "activity" | "simulation" | "situation-reports" | "alarm-automation";

const navItems = [
  { id: "overview" as const, label: "Overview", icon: LayoutDashboard },
  { id: "gis" as const, label: "GIS Operations", icon: Map },
  { id: "predictive" as const, label: "Predictive Risk Views", icon: ChartNoAxesCombined },
  { id: "riverine-forecast" as const, label: "Riverine Forecast", icon: Waves },
  { id: "upstream" as const, label: "Upstream Source Flood Watch", icon: Waves },
  { id: "monitoring" as const, label: "River Monitoring", icon: Droplets },
  { id: "incidents" as const, label: "Incidents", icon: AlertTriangle },
  { id: "reports" as const, label: "Citizen Reports", icon: MessageSquareText },
  { id: "activity" as const, label: "System Activity", icon: Activity },
  { id: "situation-reports" as const, label: "Flood Reports", icon: FileText },
  { id: "alarm-automation" as const, label: "Alerts & Alarms", icon: BellRing },
  { id: "simulation" as const, label: "Simulation", icon: FlaskConical },
];

const EXPANDED_KEY = "floodguard-sidebar-expanded";

function readExpanded() {
  try {
    return localStorage.getItem(EXPANDED_KEY) === "1";
  } catch {
    return false;
  }
}

/**
 * Navigation rail. By default it shows icons only; hovering or focusing an icon shows its
 * name in a floating label. The expand button switches to icons with names, remembered
 * in this browser. On narrow screens the full menu slides in from the left as before.
 */
export function AppShell({ activeView, onViewChange, children }: { activeView: ViewId; onViewChange: (view: ViewId) => void; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(readExpanded);
  const [tip, setTip] = useState<{ label: string; top: number } | null>(null);
  const firstRender = useRef(true);

  useEffect(() => {
    try {
      localStorage.setItem(EXPANDED_KEY, expanded ? "1" : "0");
    } catch {
      /* storage unavailable: the choice lasts for this visit */
    }
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    setTip(null);
    // Maps size themselves on window resize; tell them once the rail has finished moving.
    const timer = window.setTimeout(() => window.dispatchEvent(new Event("resize")), 260);
    return () => window.clearTimeout(timer);
  }, [expanded]);

  const showTip = (label: string) => (event: MouseEvent<HTMLElement> | FocusEvent<HTMLElement>) => {
    if (expanded || window.matchMedia("(max-width: 980px)").matches) return;
    const rect = event.currentTarget.getBoundingClientRect();
    // Screen pixels -> CSS pixels under the page zoom (--ui-zoom, 0.8 on desktop).
    const zoom = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--ui-zoom")) || 1;
    setTip({ label, top: (rect.top + rect.height / 2) / zoom });
  };
  const hideTip = () => setTip(null);
  const tipProps = (label: string) => ({ onMouseEnter: showTip(label), onMouseLeave: hideTip, onFocus: showTip(label), onBlur: hideTip, "aria-label": label });

  return (
    <div className={`app-shell ${expanded ? "sidebar-expanded" : "sidebar-collapsed"}`}>
      <aside className={`sidebar ${open ? "sidebar-open" : ""}`}>
        <div className="brand-lockup"><div><ShieldCheck size={24} /></div><span><strong>FloodGuard AI</strong><small>NDMA Command Screen</small></span><button className="mobile-close" onClick={() => setOpen(false)}><X size={20} /></button></div>
        <nav aria-label="Main navigation" onScroll={hideTip}>
          {navItems.map(({ id, label, icon: Icon }) => { const on = activeView === id || (id === "alarm-automation" && activeView === "alerts"); return <button className={on ? "active" : ""} aria-current={on ? "page" : undefined} key={id} onClick={() => { onViewChange(id); setOpen(false); hideTip(); }} {...tipProps(label)}><Icon size={18} /><span>{label}</span></button>; })}
          <p className="sidebar-section-label"><span>Feature visualization</span></p>
          <button className={activeView === "rainfall" ? "active" : ""} aria-current={activeView === "rainfall" ? "page" : undefined} onClick={() => { onViewChange("rainfall"); setOpen(false); hideTip(); }} {...tipProps("Rainfall heatmap")}><CloudRain size={18} /><span>Rainfall heatmap</span></button>
          <p className="sidebar-section-label"><span>External maps</span></p>
          <a className="sidebar-external-map" href="https://sites.research.google/floods/l/30.36468142775536/76.22165549983335/6.182499999999997" target="_blank" rel="noopener noreferrer" title={expanded ? "Open the full Google Flood Hub map in a new tab" : undefined} onClick={() => setOpen(false)} {...tipProps("Google Flood Hub ↗")}><Waves size={18} /><span>Google Flood Hub</span><ExternalLink size={14} /></a>
        </nav>
        <button className="sidebar-toggle" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded} {...tipProps(expanded ? "Collapse menu" : "Expand menu")} aria-label={expanded ? "Collapse menu to icons" : "Expand menu to show names"}>
          {expanded ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}
          <span>{expanded ? "Collapse" : "Expand"}</span>
        </button>
        <div className="sidebar-foot"><span>National display mode</span><strong>Pakistan Region</strong></div>
      </aside>
      {tip && <div className="sidebar-tip" role="tooltip" style={{ top: tip.top }}>{tip.label}</div>}
      {open && <button className="sidebar-backdrop" aria-label="Close navigation" onClick={() => setOpen(false)} />}
      <main className={`main-content main-${activeView}`}><button className="mobile-menu" onClick={() => setOpen(true)}><Menu size={20} /> Menu</button>{children}</main>
    </div>
  );
}
