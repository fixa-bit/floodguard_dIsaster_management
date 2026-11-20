import { NationalRiskMapLoader } from "../components/NationalRiskMapLoader";
import { useState } from 'react';
import { PopulationAnalysisPanel } from '../components/PopulationAnalysisPanel';
import type { PopulationOverlay } from '../services/population';
import type { DashboardData } from "../hooks/useDashboardData";
import type { LocationId } from "../config";

/**
 * GIS Operations: the map with the relief & assessment panel first, then the flood-affected
 * population analysis under it. The Rainfall heatmap page reuses it with `rainfall`.
 */
export function GISPage({ data, locationId, onLocationChange, rainfall = false }: { data: DashboardData; locationId: LocationId; onLocationChange: (location: LocationId) => void; rainfall?: boolean }) {
  const [populationOverlay, setPopulationOverlay] = useState<PopulationOverlay | null>(null);
  return <>
    <NationalRiskMapLoader nationalRisk={data.nationalRisk} waterIntelligence={data.waterIntelligence} locationWeather={data.locationWeather} locationRivers={data.locationRivers} incidents={data.incidents} reports={data.reports} resources={data.resources} selectedLocation={locationId} onLocationChange={onLocationChange} expanded reliefTools reliefAssessment={!rainfall} initialRainfallEnabled={rainfall} populationOverlay={populationOverlay} />
    {!rainfall && <PopulationAnalysisPanel onChange={setPopulationOverlay} />}
  </>;
}
