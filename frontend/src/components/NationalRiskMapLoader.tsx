import { lazy, Suspense } from "react";
import type { ReactNode } from "react";

import type { LocationId } from "../config";
import type { CitizenReport, Incident, NationalRiskCollection, ResourceGroups, RiverResponse, WaterIntelligenceCollection, WeatherResponse } from "../types/api";


const LazyNationalRiskMap = lazy(() => import("./NationalRiskMap").then((module) => ({ default: module.NationalRiskMap })));

interface NationalRiskMapLoaderProps {
  nationalRisk: NationalRiskCollection | null;
  waterIntelligence: WaterIntelligenceCollection | null;
  locationWeather: WeatherResponse[];
  locationRivers: RiverResponse[];
  incidents: Incident[];
  reports: CitizenReport[];
  resources: ResourceGroups;
  selectedLocation: LocationId;
  onLocationChange: (location: LocationId) => void;
  expanded?: boolean;
  initialRainfallEnabled?: boolean;
  mapOverlay?: ReactNode;
}

export function NationalRiskMapLoader(props: NationalRiskMapLoaderProps) {
  return <Suspense fallback={<div className="map-loading"><strong>Loading national GIS workspace</strong><span>Preparing district boundaries and operational layers</span></div>}><LazyNationalRiskMap {...props} /></Suspense>;
}

