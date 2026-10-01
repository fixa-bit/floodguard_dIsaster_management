import { NationalRiskMapLoader } from "../components/NationalRiskMapLoader";
import type { DashboardData } from "../hooks/useDashboardData";
import type { LocationId } from "../config";


export function GISPage({ data, locationId, onLocationChange }: { data: DashboardData; locationId: LocationId; onLocationChange: (location: LocationId) => void }) {
  return <NationalRiskMapLoader nationalRisk={data.nationalRisk} waterIntelligence={data.waterIntelligence} incidents={data.incidents} reports={data.reports} resources={data.resources} selectedLocation={locationId} onLocationChange={onLocationChange} expanded />;
}

