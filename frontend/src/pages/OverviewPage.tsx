import { AlertCircle } from "lucide-react";

import type { DashboardData } from "../hooks/useDashboardData";
import { CommandStatsDeck } from "../components/CommandStatsDeck";
import { HourlyAnalyticsTicker } from "../components/HourlyAnalyticsTicker";
import { KpiGrid } from "../components/KpiGrid";
import { NationalRiskMapLoader } from "../components/NationalRiskMapLoader";
import type { LocationId } from "../config";

export function OverviewPage({ data, locationId, onLocationChange, onRefresh }: { data: DashboardData; locationId: LocationId; onLocationChange: (location: LocationId) => void; onRefresh: () => Promise<unknown> | void }) {
  const highestRisk = data.summary?.highest_risk_probability ?? data.risk?.flood_probability ?? null;
  return (
    <div className="overview-command-canvas">
      {data.system?.data_mode === "simulation" && <div className="mode-banner mode-banner-danger"><AlertCircle size={18} /><div><strong>SIMULATION MODE</strong><span>Environmental readings and risk calculations are simulated. Do not use for live decisions.</span></div></div>}
      {data.system?.data_mode !== "simulation" && data.system?.active_scenario !== "NORMAL" && <div className="mode-banner mode-banner-warning"><AlertCircle size={18} /><div><strong>Simulation scenario configured</strong><span>Operational feeds remain live; the configured scenario is isolated from live risk calculations.</span></div></div>}
      <NationalRiskMapLoader
        nationalRisk={data.nationalRisk}
        waterIntelligence={data.waterIntelligence}
        locationWeather={data.locationWeather}
        locationRivers={data.locationRivers}
        incidents={data.incidents}
        reports={data.reports}
        resources={data.resources}
        selectedLocation={locationId}
        onLocationChange={onLocationChange}
        expanded
        mapOverlay={
          <div className="overview-map-hud">
            <KpiGrid summary={data.summary} currentRisk={highestRisk} monitoringInterval={data.risk?.monitoring_interval_minutes ?? data.system?.monitoring_interval_minutes ?? null} />
            <CommandStatsDeck data={data} onRefresh={onRefresh} />
          </div>
        }
      />
      <HourlyAnalyticsTicker data={data} />
    </div>
  );
}
