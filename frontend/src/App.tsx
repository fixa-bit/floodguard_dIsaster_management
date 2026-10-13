import { AlertCircle, BellRing, ChevronDown, Clock3, RefreshCw, X } from "lucide-react";
import { useState } from "react";

import { ActivityTimeline } from "./components/ActivityTimeline";
import { AppShell, type ViewId } from "./components/AppShell";
import { CitizenReportsPanel } from "./components/CitizenReportsPanel";
import { IncidentTable } from "./components/IncidentTable";
import { AlertTable } from "./components/AlertTable";
import { SimulationPanel } from "./components/SimulationPanel";
import { FloodRiskMultiView } from "./components/FloodRiskMultiView";
import { SourceFloodForecastTab } from "./components/SourceFloodForecastTab";
import { RiverMonitoringView } from "./components/RiverMonitoringView";
import { LOCATIONS, type LocationId } from "./config";
import { useDashboardData } from "./hooks/useDashboardData";
import { OverviewPage } from "./pages/OverviewPage";
import { GISPage } from "./pages/GISPage";
import { api } from "./services/api";
import type { MonitoringSimulationResult } from "./types/api";

const viewTitles: Record<ViewId, { title: string; subtitle: string }> = {
  overview: { title: "Operational Overview", subtitle: "Live flood intelligence and emergency coordination" },
  gis: { title: "GIS Operations", subtitle: "National hazard screening and operational geography" },
  rainfall: { title: "Rainfall Heatmap", subtitle: "Observed and forecast rainfall across Pakistan" },
  predictive: { title: "Predictive Risk Views", subtitle: "Early-stage risk screening with illustrative forecast series" },
  upstream: { title: "Upstream Source Flood Watch", subtitle: "Upper-basin stations, discharge forecasts, and past trends" },
  monitoring: { title: "River Monitoring", subtitle: "Barrages, headworks and river station readings" },
  alerts: { title: "Alerts", subtitle: "Monitoring alerts and recorded threshold crossings" },
  incidents: { title: "Incident Management", subtitle: "Review active and historical emergency incidents" },
  reports: { title: "Citizen Reports", subtitle: "Field observations awaiting authority verification" },
  activity: { title: "System Activity", subtitle: "Automated decisions, monitoring changes, and response events" },
  simulation: { title: "Simulation", subtitle: "Monitoring test scenarios" },
};

export default function App() {
  const [view, setView] = useState<ViewId>("overview");
  const [locationId, setLocationId] = useState<LocationId>("JHG_001");
  const includeLiveData = ["overview", "gis", "rainfall", "predictive"].includes(view);
  const { data, loading, errors, lastUpdated, autoRefreshMs, refresh, refreshOperations } = useDashboardData(locationId, includeLiveData);
  const [simulationNotice, setSimulationNotice] = useState<MonitoringSimulationResult | null>(null);
  const [selectedIncidentId, setSelectedIncidentId] = useState<number | null>(null);
  const pendingSimulationAlerts = simulationNotice ? data.alerts.filter((alert) => alert.event_metadata.run_id === simulationNotice.run_id && alert.event_metadata.approval_status !== "approved").length : 0;
  const location = LOCATIONS.find((item) => item.id === locationId)!;
  const heading = viewTitles[view];

  return (
    <AppShell activeView={view} onViewChange={(next) => { setSelectedIncidentId(null); setView(next); if (["alerts", "incidents"].includes(next)) void refreshOperations(); }}>
      <header className="topbar">
        <div><p className="eyebrow">Emergency Command Dashboard</p><h1>{heading.title}</h1><span>{heading.subtitle}</span></div>
        <div className="topbar-actions">
          <label className="location-select"><span>Operational area</span><div><strong>{location.name}</strong><small>{location.river} River · {location.id}</small><ChevronDown size={17} /></div><select aria-label="Operational location" value={locationId} onChange={(event) => setLocationId(event.target.value as LocationId)}>{LOCATIONS.map((item) => <option value={item.id} key={item.id}>{item.name} ({item.id})</option>)}</select></label>
        </div>
      </header>

      <div className="update-strip"><Clock3 size={14} /><span>{lastUpdated ? `Updated ${lastUpdated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}` : "Waiting for first update"}</span><i /> River layer refresh every {Math.round(autoRefreshMs / 60000)} minutes</div>

      {errors.length > 0 && <div className="error-banner" role="alert"><AlertCircle size={19} /><div><strong>{includeLiveData ? "Some dashboard data could not be refreshed" : "Some operational data could not be refreshed"}</strong><span>{errors.join(" · ")}</span></div><button onClick={() => void refresh(false)}>Retry</button></div>}

      {simulationNotice && <div className="simulation-alert-banner" role="alert"><BellRing size={20} /><div><strong>SIMULATED FLOW: {simulationNotice.station_name}</strong><span>{simulationNotice.alerts.length} threshold alerts saved / {pendingSimulationAlerts} awaiting review</span></div><button type="button" className="secondary-button" onClick={() => setView("alerts")}>View alerts</button><button type="button" className="icon-button" title="Dismiss simulation alert" aria-label="Dismiss simulation alert" onClick={() => setSimulationNotice(null)}><X size={17} /></button></div>}

      {loading && !["overview", "gis", "rainfall", "simulation", "alerts", "incidents"].includes(view) ? <div className="dashboard-loading"><RefreshCw className="spinning" /><strong>Connecting to FloodGuard services</strong><span>Loading live operational data…</span></div> : (
        <div className="page-content">
          {view === "overview" && <OverviewPage data={data} locationId={locationId} onLocationChange={setLocationId} onRefresh={() => refresh(false)} />}
          {view === "gis" && <GISPage data={data} locationId={locationId} onLocationChange={setLocationId} />}
          {view === "rainfall" && <GISPage key="rainfall" data={data} locationId={locationId} onLocationChange={setLocationId} rainfall />}
          {view === "predictive" && <FloodRiskMultiView data={data} />}
          {view === "upstream" && <SourceFloodForecastTab />}
          {view === "monitoring" && <RiverMonitoringView />}
          {view === "alerts" && <AlertTable alerts={data.alerts} onOpenIncident={(id) => { setSelectedIncidentId(id); setView("incidents"); }} onApprove={async (id) => { await api.approveSimulatedAlert(id); await refreshOperations(); }} />}
          {view === "incidents" && <IncidentTable incidents={data.incidents} initialIncidentId={selectedIncidentId} full />}
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
          {view === "simulation" && <SimulationPanel onCompleted={(result) => { setSimulationNotice(result.alerts.length ? result : null); void refreshOperations(result); }} onOpenAlerts={() => setView("alerts")} onOpenIncidents={() => { setSelectedIncidentId(null); setView("incidents"); }} />}
        </div>
      )}
    </AppShell>
  );
}
