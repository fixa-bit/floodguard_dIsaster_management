import { AlertCircle, BellRing, ChevronDown, Clock3, Compass, History, RefreshCw, X } from "lucide-react";
import { useCallback, useRef, useState } from "react";

import { ActivityTimeline } from "./components/ActivityTimeline";
import { AlarmAutomation } from "./components/AlarmAutomation";
import { AppShell, type ViewId } from "./components/AppShell";
import { CitizenReportsPanel } from "./components/CitizenReportsPanel";
import { IncidentTable } from "./components/IncidentTable";
import { AlertTable } from "./components/AlertTable";
import { SimulationPanel } from "./components/SimulationPanel";
import { FloodRiskMultiView } from "./components/FloodRiskMultiView";
import { SourceFloodForecastTab } from "./components/SourceFloodForecastTab";
import { RiverMonitoringView } from "./components/RiverMonitoringView";
import { PortalTour } from "./components/PortalTour";
import { ReportsCenter } from "./components/ReportsCenter";
import { LOCATIONS, type LocationId } from "./config";
import { useDashboardData } from "./hooks/useDashboardData";
import { OverviewPage } from "./pages/OverviewPage";
import { GISPage } from "./pages/GISPage";
import { api } from "./services/api";
import { type StaleSource, useStaleSources } from "./services/lastGoodCache";
import type { MonitoringSimulationResult } from "./types/api";

const viewTitles: Record<ViewId, { title: string; subtitle: string }> = {
  overview: { title: "Operational Overview", subtitle: "Live flood intelligence and emergency coordination" },
  gis: { title: "GIS Operations", subtitle: "Relief and assessment: hazard, field reports and relief facilities around any place" },
  rainfall: { title: "Rainfall Heatmap", subtitle: "Observed and forecast rainfall across Pakistan" },
  predictive: { title: "Predictive Risk Views", subtitle: "Real model output where a model exists; dummy output is marked on every graph" },
  upstream: { title: "Upstream Source Flood Watch", subtitle: "Upper-basin stations, discharge forecasts, and past trends" },
  monitoring: { title: "River Monitoring", subtitle: "Barrages, headworks and river station readings" },
  alerts: { title: "Alerts & Alarms", subtitle: "Threshold alerts, and the n8n flood alarm workflow: live runs, duty roster, alert channels and alarms" },
  incidents: { title: "Incident Management", subtitle: "Review active and historical emergency incidents" },
  reports: { title: "Citizen Reports", subtitle: "Field observations awaiting authority verification" },
  activity: { title: "System Activity", subtitle: "Automated decisions, monitoring changes, and response events" },
  simulation: { title: "Simulation", subtitle: "Monitoring test scenarios" },
  "situation-reports": { title: "Flood Reports", subtitle: "View daily flood reports and reports for individual flood events" },
  "alarm-automation": { title: "Alerts & Alarms", subtitle: "Threshold alerts, and the n8n flood alarm workflow: live runs, duty roster, alert channels and alarms" },
};

/** "Saved 15:20: River gauge (JHG_001), Alerts · Saved yesterday …" grouped by save time. */
function staleSummary(sources: StaleSource[]): string {
  const groups = new Map<string, string[]>();
  for (const item of [...sources].sort((a, b) => b.savedAt - a.savedAt)) {
    const time = savedTime(item.savedAt);
    groups.set(time, [...(groups.get(time) ?? []), item.label]);
  }
  return [...groups].map(([time, labels]) => `Saved ${time}: ${labels.join(", ")}`).join(" · ");
}

function savedTime(savedAt: number): string {
  const saved = new Date(savedAt);
  const time = saved.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return saved.toDateString() === new Date().toDateString() ? time : `${saved.toLocaleDateString([], { day: "numeric", month: "short" })} ${time}`;
}

export default function App() {
  const [view, setView] = useState<ViewId>("overview");
  const [tourOpen, setTourOpen] = useState(false);
  const tourButton = useRef<HTMLButtonElement>(null);
  const [locationId, setLocationId] = useState<LocationId>("JHG_001");
  const includeLiveData = ["overview", "gis", "rainfall", "predictive"].includes(view);
  const { data, loading, errors, lastUpdated, autoRefreshMs, refresh, refreshOperations } = useDashboardData(locationId, includeLiveData);
  const staleSources = useStaleSources();
  const [simulationNotice, setSimulationNotice] = useState<MonitoringSimulationResult | null>(null);
  const [selectedIncidentId, setSelectedIncidentId] = useState<number | null>(null);
  const pendingSimulationAlerts = simulationNotice ? data.alerts.filter((alert) => alert.event_metadata.run_id === simulationNotice.run_id && alert.event_metadata.approval_status !== "approved").length : 0;
  const location = LOCATIONS.find((item) => item.id === locationId)!;
  // Alerts & Alarms can also show the whole of Pakistan instead of one operational area.
  // It opens on the whole country; choosing an area narrows it.
  const [wholePakistan, setWholePakistan] = useState(true);
  const alarmsView = view === "alerts" || view === "alarm-automation";
  const showWholePakistan = alarmsView && wholePakistan;
  const heading = viewTitles[view];
  const navigateToTourView = useCallback((next: ViewId) => {
    setSelectedIncidentId(null);
    setView(next);
    if (["alerts", "incidents", "alarm-automation"].includes(next)) void refreshOperations();
  }, [refreshOperations]);
  const closeTour = useCallback(() => {
    setTourOpen(false);
    window.requestAnimationFrame(() => tourButton.current?.focus());
  }, []);

  return (
    <AppShell activeView={view} onViewChange={navigateToTourView}>
      <header className="topbar">
        <div><p className="eyebrow">Emergency Command Dashboard</p><h1 data-tour-target="page-title">{heading.title}</h1><span>{heading.subtitle}</span></div>
        <div className="topbar-actions">
          <button ref={tourButton} type="button" className="portal-tour-trigger" aria-haspopup="dialog" aria-expanded={tourOpen} onClick={() => setTourOpen(true)}><Compass size={17} /><span>Portal tour</span></button>
          <label className="location-select"><span>Operational area</span><div data-tour-target="tour-location-control">{showWholePakistan ? <><strong>Whole Pakistan</strong><small>All areas</small></> : <><strong>{location.name}</strong><small>{location.river} River · {location.id}</small></>}<ChevronDown size={17} /></div><select data-tour-target="tour-location-select" aria-label="Operational location" value={showWholePakistan ? "PK" : locationId} onChange={(event) => { if (event.target.value === "PK") { setWholePakistan(true); return; } setWholePakistan(false); setLocationId(event.target.value as LocationId); }}>{alarmsView && <option value="PK">Whole Pakistan</option>}{LOCATIONS.map((item) => <option value={item.id} key={item.id}>{item.name} ({item.id})</option>)}</select></label>
        </div>
      </header>

      <div className="update-strip"><Clock3 size={14} /><span>{lastUpdated ? `Updated ${lastUpdated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}` : "Waiting for first update"}</span><i /> River layer refresh every {Math.round(autoRefreshMs / 60000)} minutes</div>

      {(errors.length > 0 || staleSources.length > 0) && <div className="status-banners">
        {errors.length > 0 && <div className="error-banner" role="alert"><AlertCircle size={19} /><div><strong>{includeLiveData ? "Some dashboard data could not be refreshed" : "Some operational data could not be refreshed"}</strong><span>{errors.join(" · ")}</span></div><button onClick={() => void refresh(false)}>Retry</button></div>}
        {staleSources.length > 0 && <div className="error-banner stale-data-banner" role="status"><History size={19} /><div><strong>Live source unavailable: showing the last data that loaded</strong><span>{staleSummary(staleSources)}</span></div><button onClick={() => void refresh(false)}>Retry</button></div>}
      </div>}

      {simulationNotice && <div className="simulation-alert-banner" role="alert"><BellRing size={20} /><div><strong>SIMULATED FLOW: {simulationNotice.station_name}</strong><span>{simulationNotice.alerts.length} threshold alerts saved / {pendingSimulationAlerts} awaiting review</span></div><button type="button" className="secondary-button" onClick={() => setView("alerts")}>View alerts</button><button type="button" className="icon-button" title="Dismiss simulation alert" aria-label="Dismiss simulation alert" onClick={() => setSimulationNotice(null)}><X size={17} /></button></div>}

      {loading && !["overview", "gis", "rainfall", "simulation", "alerts", "incidents", "situation-reports", "alarm-automation"].includes(view) ? <div className="dashboard-loading"><RefreshCw className="spinning" /><strong>Connecting to FloodGuard services</strong><span>Loading live operational data…</span></div> : (
        <div className="page-content">
          {view === "overview" && <OverviewPage data={data} locationId={locationId} onLocationChange={setLocationId} onRefresh={() => refresh(false)} />}
          {view === "gis" && <GISPage data={data} locationId={locationId} onLocationChange={setLocationId} />}
          {view === "rainfall" && <GISPage key="rainfall" data={data} locationId={locationId} onLocationChange={setLocationId} rainfall />}
          {view === "predictive" && <FloodRiskMultiView data={data} />}
          {view === "upstream" && <SourceFloodForecastTab />}
          {view === "monitoring" && <RiverMonitoringView />}
          {/* Alerts live in the Alerts & Alarms page, as its first tab (the page opens on it). */}
          {(view === "alerts" || view === "alarm-automation") && <AlarmAutomation initialTab="alerts" area={wholePakistan ? null : location}
            renderAlerts={(shown) => { const inArea = data.alerts.filter(shown); return <AlertTable alerts={inArea}
              emptyNote={!inArea.length && data.alerts.length ? `No alerts within 150 km of ${location.name}. ${data.alerts.length} alert${data.alerts.length === 1 ? " is" : "s are"} elsewhere: choose Whole Pakistan under Operational area to see ${data.alerts.length === 1 ? "it" : "them"}.` : undefined} onOpenIncident={(id) => { setSelectedIncidentId(id); setView("incidents"); }} onApprove={async (id) => { await api.approveSimulatedAlert(id); await refreshOperations(); }} />; }} />}
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
          {view === "situation-reports" && <ReportsCenter />}
          {view === "simulation" && <SimulationPanel onCompleted={(result) => { setSimulationNotice(result.alerts.length ? result : null); void refreshOperations(result); }} onOpenAlerts={() => setView("alerts")} onOpenIncidents={() => { setSelectedIncidentId(null); setView("incidents"); }} />}
        </div>
      )}
      {tourOpen && <PortalTour open onClose={closeTour} onNavigate={navigateToTourView} />}
    </AppShell>
  );
}
