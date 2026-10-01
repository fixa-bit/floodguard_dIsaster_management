import { AlertCircle } from "lucide-react";

import type { DashboardData } from "../hooks/useDashboardData";
import { ActivityTimeline } from "../components/ActivityTimeline";
import { CitizenReportsPanel } from "../components/CitizenReportsPanel";
import { EnvironmentalPanel } from "../components/EnvironmentalPanel";
import { IncidentTable } from "../components/IncidentTable";
import { KpiGrid } from "../components/KpiGrid";
import { LiveRiskPanel } from "../components/LiveRiskPanel";
import { NationalRiskMapLoader } from "../components/NationalRiskMapLoader";
import { ResourcesPanel } from "../components/ResourcesPanel";
import { SimulationPanel } from "../components/SimulationPanel";
import { SystemStatusPanel } from "../components/SystemStatusPanel";
import type { LocationId } from "../config";

export function OverviewPage({ data, locationId, onLocationChange, onRefresh }: { data: DashboardData; locationId: LocationId; onLocationChange: (location: LocationId) => void; onRefresh: () => Promise<unknown> | void }) {
  const highestRisk = data.summary?.highest_risk_probability ?? data.risk?.flood_probability ?? null;
  return (
    <>
      {data.system?.data_mode === "simulation" && <div className="mode-banner mode-banner-danger"><AlertCircle size={18} /><div><strong>SIMULATION MODE</strong><span>Environmental readings and risk calculations are simulated. Do not use for live decisions.</span></div></div>}
      {data.system?.data_mode !== "simulation" && data.system?.active_scenario !== "NORMAL" && <div className="mode-banner mode-banner-warning"><AlertCircle size={18} /><div><strong>Simulation scenario configured</strong><span>Operational feeds remain live; the configured scenario is isolated from live risk calculations.</span></div></div>}
      <KpiGrid summary={data.summary} currentRisk={highestRisk} monitoringInterval={data.risk?.monitoring_interval_minutes ?? data.system?.monitoring_interval_minutes ?? null} />
      <NationalRiskMapLoader nationalRisk={data.nationalRisk} waterIntelligence={data.waterIntelligence} incidents={data.incidents} reports={data.reports} resources={data.resources} selectedLocation={locationId} onLocationChange={onLocationChange} />
      <div className="overview-primary"><LiveRiskPanel risk={data.risk} /><EnvironmentalPanel weather={data.weather} river={data.river} /></div>
      <div className="overview-wide"><IncidentTable incidents={data.incidents} /></div>
      <div className="overview-secondary"><CitizenReportsPanel reports={data.reports} /><ActivityTimeline events={data.events} /></div>
      <div className="overview-tertiary"><SystemStatusPanel system={data.system} /><SimulationPanel status={data.simulation} system={data.system} selectedLocation={locationId} onChanged={onRefresh} /></div>
      <div className="overview-wide"><ResourcesPanel resources={data.resources} locationId={locationId} /></div>
    </>
  );
}
