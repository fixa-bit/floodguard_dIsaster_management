import { apiFetch } from './api';
import { API_BASE_URL } from '../config';

export type FloodSource = 'historical_reference' | 'sample' | 'provided' | 'segmentation';
export interface AdminPopulation {
  id: string; name: string; level: string; known_population_total: number;
  estimated_exposed_population: number | null; percentage_exposed_of_known_population: number | null;
  known_flood_area_fraction: number | null;
}
export interface PopulationSummary {
  analysis_id: string; region: string; flood: { kind: string; is_sample: boolean; label: string; analyzed_extent_area_km2: number; observation_period?: string };
  population: { estimated_exposed_population: number | null; known_population_total: number; percentage_exposed_of_known_population: number | null; flood_area_with_known_population_fraction: number | null; status: string };
  administrative: Record<string, AdminPopulation[]>;
  administrative_availability: Record<string, string>;
  density_distribution: { density_min_people_km2: number; density_max_people_km2: number | null; exposed_population: number }[];
  settlements: { affected_count: number | null };
  layers: Record<string, string>; bounds: [number, number, number, number]; notes: string[];
}
export interface PopulationOverlay { summary: PopulationSummary; visible: Record<string, boolean>; adminLevel: string }
export interface PopulationJob { status: string; analysis_id: string; error?: { message: string }; summary_url?: string }
export const artifactUrl = (path: string) => API_BASE_URL.replace(/\/api\/v1\/?$/, '') + path;
export const populationApi = {
  regions: () => apiFetch<{ regions: { region: string }[] }>('/exposure/regions'),
  latest: (region: string, signal?: AbortSignal) => apiFetch<PopulationSummary | null>(`/population/regions/${region}/latest`, { signal }),
  start: (region: string, flood_source: FloodSource, flood_extent?: object) => apiFetch<PopulationJob>('/population/analyses', { method: 'POST', body: JSON.stringify({region, flood_source, ...(flood_extent ? { flood_extent } : {})}) }),
  status: (region: string, id: string, signal?: AbortSignal) => apiFetch<PopulationJob>(`/population/analyses/${region}/${id}/status`, { signal }),
  summary: (region: string, id: string, signal?: AbortSignal) => apiFetch<PopulationSummary>(`/population/analyses/${region}/${id}`, { signal }),
};
