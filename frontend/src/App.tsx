import { AlertCircle, ChevronDown, Clock3, RefreshCw } from "lucide-react";
import { useState } from "react";

import { ActivityTimeline } from "./components/ActivityTimeline";
import { AppShell, type ViewId } from "./components/AppShell";
import { CitizenReportsPanel } from "./components/CitizenReportsPanel";
import { IncidentTable } from "./components/IncidentTable";
import { SimulationPanel } from "./components/SimulationPanel";
import { FloodRiskMultiView } from "./components/FloodRiskMultiView";
import { SourceFloodForecastTab } from "./components/SourceFloodForecastTab";
import { RiverMonitoringView } from "./components/RiverMonitoringView";
import { LOCATIONS, type LocationId } from "./config";
import { useDashboardData } from "./hooks/useDashboardData";
import { OverviewPage } from "./pages/OverviewPage";
import { GISPage } from "./pages/GISPage";
import { api } from "./services/api";

const viewTitles: Record<ViewId, { title: string; subtitle: string }> = {
  overview: { title: "Operational Overview", subtitle: "Live flood intelligence and emergency coordination" },
  gis: { title: "GIS Operations", subtitle: "National hazard screening and operational geography" },
  rainfall: { title: "Rainfall Heatmap", subtitle: "Observed and forecast rainfall across Pakistan" },
  predictive: { title: "Predictive Risk Views", subtitle: "Flood forecasts by hazard type and horizon" },
  upstream: { title: "Upstream Source Flood Watch", subtitle: "Upper-basin stations, discharge forecasts, and past trends" },
  monitoring: { title: "River Monitoring", subtitle: "Barrages, headworks and river station readings" },
  incidents: { title: "Incident Management", subtitle: "Review active and historical emergency incidents" },
  reports: { title: "Citizen Reports", subtitle: "Field observations awaiting authority verification" },
  activity: { title: "System Activity", subtitle: "Automated decisions, monitoring changes, and response events" },
  simulation: { title: "Simulation", subtitle: "Controlled scenario testing isolated from operational feeds" },
};

export default function App() {
  const [view, setView] = useState<ViewId>("overview");
  const [locationId, setLocationId] = useState<LocationId>("JHG_001");
  const { data, loading, errors, lastUpdated, autoRefreshMs, refresh } = useDashboardData(locationId);
  const location = LOCATIONS.find((item) => item.id === locationId)!;
  const heading = viewTitles[view];

  return (
    <AppShell activeView={view} onViewChange={setView}>
      <header className="topbar">
        <div><p className="eyebrow">Emergency Command Dashboard</p><h1>{heading.title}</h1><span>{heading.subtitle}</span></div>
        <div className="topbar-actions">
          <label className="location-select"><span>Operational area</span><div><strong>{location.name}</strong><small>{location.river} River · {location.id}</small><ChevronDown size={17} /></div><select aria-label="Operational location" value={locationId} onChange={(event) => setLocationId(event.target.value as LocationId)}>{LOCATIONS.map((item) => <option value={item.id} key={item.id}>{item.name} ({item.id})</option>)}</select></label>
        </div>
      </header>

      <div className="update-strip"><Clock3 size={14} /><span>{lastUpdated ? `Updated ${lastUpdated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}` : "Waiting for first update"}</span><i /> River layer refresh every {Math.round(autoRefreshMs / 60000)} minutes</div>

      {errors.length > 0 && <div className="error-banner"><AlertCircle size={19} /><div><strong>{errors.some((error) => error.includes("BACKEND_UNAVAILABLE")) ? "Backend unavailable" : "Some live data could not be refreshed"}</strong><span>{errors.join(" · ")}</span></div><button onClick={() => void refresh(false)}>Retry</button></div>}

      {loading && !["overview", "gis", "rainfall"].includes(view) ? <div className="dashboard-loading"><RefreshCw className="spinning" /><strong>Connecting to FloodGuard services</strong><span>Loading live operational data…</span></div> : (
        <div className="page-content">
          {view === "overview" && <OverviewPage data={data} locationId={locationId} onLocationChange={setLocationId} onRefresh={() => refresh(false)} />}
          {view === "gis" && <GISPage data={data} locationId={locationId} onLocationChange={setLocationId} />}
          {view === "rainfall" && <GISPage key="rainfall" data={data} locationId={locationId} onLocationChange={setLocationId} rainfall />}
          {view === "predictive" && <FloodRiskMultiView data={data} />}
          {view === "upstream" && <SourceFloodForecastTab />}
          {view === "monitoring" && <RiverMonitoringView />}
          {view === "incidents" && <IncidentTable incidents={data.incidents} full />}
          {view === "reports" && (
            <CitizenReportsPanel
              reports={data.reports}
              full
              onCreateReport={async (payload) => { const created = await api.createCitizenReport(payload); void refresh(false); return created; }}
              onToggleImportant={async (reportId) => { const updated = await api.toggleCitizenReportImportant(reportId); void refresh(false); return updated; }}
              onCloseReport={async (reportId) => { const closed = await api.closeCitizenReport(reportId); void refresh(false); return closed; }}
            />
          )}
          {view === "activity" && <ActivityTimeline events={data.events} full />}
          {view === "simulation" && <div className="single-page-grid"><SimulationPanel status={data.simulation} system={data.system} selectedLocation={locationId} onChanged={() => refresh(false)} /></div>}
        </div>
      )}
    </AppShell>
  );
}
