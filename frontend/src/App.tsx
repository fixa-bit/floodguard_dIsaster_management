import { AlertCircle, ChevronDown, Clock3, RefreshCw } from "lucide-react";
import { useState } from "react";

import { ActivityTimeline } from "./components/ActivityTimeline";
import { AppShell, type ViewId } from "./components/AppShell";
import { CitizenReportsPanel } from "./components/CitizenReportsPanel";
import { IncidentTable } from "./components/IncidentTable";
import { SimulationPanel } from "./components/SimulationPanel";
import { LOCATIONS, type LocationId } from "./config";
import { useDashboardData } from "./hooks/useDashboardData";
import { OverviewPage } from "./pages/OverviewPage";
import { GISPage } from "./pages/GISPage";

const viewTitles: Record<ViewId, { title: string; subtitle: string }> = {
  overview: { title: "Operational Overview", subtitle: "Live flood intelligence and emergency coordination" },
  gis: { title: "GIS Operations", subtitle: "National hazard screening and operational geography" },
  incidents: { title: "Incident Management", subtitle: "Review active and historical emergency incidents" },
  reports: { title: "Citizen Reports", subtitle: "Field observations awaiting authority verification" },
  activity: { title: "System Activity", subtitle: "Automated decisions, monitoring changes, and response events" },
  simulation: { title: "Simulation", subtitle: "Controlled scenario testing isolated from operational feeds" },
};

export default function App() {
  const [view, setView] = useState<ViewId>("overview");
  const [locationId, setLocationId] = useState<LocationId>("JHG_001");
  const { data, loading, refreshing, errors, lastUpdated, refresh } = useDashboardData(locationId);
  const location = LOCATIONS.find((item) => item.id === locationId)!;
  const heading = viewTitles[view];

  return (
    <AppShell activeView={view} onViewChange={setView}>
      <header className="topbar">
        <div><p className="eyebrow">Emergency Command Dashboard</p><h1>{heading.title}</h1><span>{heading.subtitle}</span></div>
        <div className="topbar-actions">
          <label className="location-select"><span>Operational area</span><div><strong>{location.name}</strong><small>{location.river} River · {location.id}</small><ChevronDown size={17} /></div><select aria-label="Operational location" value={locationId} onChange={(event) => setLocationId(event.target.value as LocationId)}>{LOCATIONS.map((item) => <option value={item.id} key={item.id}>{item.name} ({item.id})</option>)}</select></label>
          <button className="refresh-button" disabled={refreshing} onClick={() => void refresh(false)} title="Refresh dashboard"><RefreshCw className={refreshing ? "spinning" : ""} size={18} /><span>Refresh</span></button>
        </div>
      </header>

      <div className="update-strip"><Clock3 size={14} /><span>{lastUpdated ? `Updated ${lastUpdated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}` : "Waiting for first update"}</span><i /> Auto-refresh every 30 seconds</div>

      {errors.length > 0 && <div className="error-banner"><AlertCircle size={19} /><div><strong>{errors.some((error) => error.includes("BACKEND_UNAVAILABLE")) ? "Backend unavailable" : "Some live data could not be refreshed"}</strong><span>{errors.join(" · ")}</span></div><button onClick={() => void refresh(false)}>Retry</button></div>}

      {loading ? <div className="dashboard-loading"><RefreshCw className="spinning" /><strong>Connecting to FloodGuard services</strong><span>Loading live operational data…</span></div> : (
        <div className="page-content">
          {view === "overview" && <OverviewPage data={data} locationId={locationId} onLocationChange={setLocationId} onRefresh={() => refresh(false)} />}
          {view === "gis" && <GISPage data={data} locationId={locationId} onLocationChange={setLocationId} />}
          {view === "incidents" && <IncidentTable incidents={data.incidents} full />}
          {view === "reports" && <CitizenReportsPanel reports={data.reports} full />}
          {view === "activity" && <ActivityTimeline events={data.events} full />}
          {view === "simulation" && <div className="single-page-grid"><SimulationPanel status={data.simulation} system={data.system} selectedLocation={locationId} onChanged={() => refresh(false)} /></div>}
        </div>
      )}
    </AppShell>
  );
}
