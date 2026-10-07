import { NationalRiskMapLoader } from "../components/NationalRiskMapLoader";
import type { DashboardData } from "../hooks/useDashboardData";
import type { LocationId } from "../config";


export function GISPage({ data, locationId, onLocationChange, rainfall = false }: { data: DashboardData; locationId: LocationId; onLocationChange: (location: LocationId) => void; rainfall?: boolean }) {
  return <NationalRiskMapLoader nationalRisk={data.nationalRisk} waterIntelligence={data.waterIntelligence} locationWeather={data.locationWeather} locationRivers={data.locationRivers} incidents={data.incidents} reports={data.reports} resources={data.resources} selectedLocation={locationId} onLocationChange={onLocationChange} expanded initialRainfallEnabled={rainfall} />;
}

