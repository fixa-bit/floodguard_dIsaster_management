// Hand-authored example values for the planning UI. These are never model outputs.
export const PREVIEW_BASE_YEAR = 2026;
export const PREVIEW_END_YEAR = 2036;
export const PREVIEW_VERSION = "hypothetical-outlook-v2";

export const previewHazards = [
  { id: "riverine", label: "Riverine flooding", rainWeight: 0.55, landWeight: 0.1 },
  { id: "flash", label: "Flash flooding", rainWeight: 0.65, landWeight: 0.15 },
  { id: "urban", label: "Urban flooding", rainWeight: 0.45, landWeight: 0.4 },
] as const;

export const previewScenarios = [
  { id: "lowest", label: "Lowest scenario", rainStress: -15, landStress: -10, description: "Illustrates reduced rainfall and built-up stress over time. A hypothetical improving-conditions example, not a prediction or guarantee of safety." },
  { id: "stable", label: "Stable conditions", rainStress: 0, landStress: 0, description: "Keeps the constructed baseline index unchanged throughout the decade." },
  { id: "moderate", label: "Moderate stress", rainStress: 30, landStress: 20, description: "Illustrates a moderate increase in rainfall and built-up stress over the decade." },
  { id: "higher", label: "Higher stress", rainStress: 60, landStress: 40, description: "Illustrates a larger increase in rainfall and built-up stress over the decade." },
  { id: "highest", label: "Highest scenario", rainStress: 90, landStress: 60, description: "The greatest stress among these five examples. It is not a physical upper bound or a worst-case climate forecast; the example index remains capped at 100." },
] as const;

export type PreviewHazard = typeof previewHazards[number]["id"];
export type PreviewScenario = typeof previewScenarios[number]["id"];

export const previewAreas = [
  { id: "jhang", name: "Jhang", province: "Punjab", coordinates: [72.3187, 31.2681], sensitivity: 1.1, baseline: { riverine: 44, flash: 28, urban: 35 } },
  { id: "multan", name: "Multan", province: "Punjab", coordinates: [71.5249, 30.1575], sensitivity: 0.95, baseline: { riverine: 48, flash: 24, urban: 41 } },
  { id: "lahore", name: "Lahore", province: "Punjab", coordinates: [74.3587, 31.5204], sensitivity: 1.05, baseline: { riverine: 32, flash: 21, urban: 54 } },
  { id: "rawalpindi", name: "Rawalpindi", province: "Punjab", coordinates: [73.0169, 33.5651], sensitivity: 1.15, baseline: { riverine: 35, flash: 52, urban: 48 } },
  { id: "charsadda", name: "Charsadda", province: "Khyber Pakhtunkhwa", coordinates: [71.731, 34.148], sensitivity: 1.2, baseline: { riverine: 56, flash: 61, urban: 30 } },
  { id: "sukkur", name: "Sukkur", province: "Sindh", coordinates: [68.8574, 27.7244], sensitivity: 1.15, baseline: { riverine: 58, flash: 26, urban: 34 } },
  { id: "dadu", name: "Dadu", province: "Sindh", coordinates: [67.7769, 26.7303], sensitivity: 1.25, baseline: { riverine: 60, flash: 45, urban: 24 } },
  { id: "badin", name: "Badin", province: "Sindh", coordinates: [68.8384, 24.6559], sensitivity: 1, baseline: { riverine: 55, flash: 22, urban: 28 } },
] as const;

export type PreviewAreaId = typeof previewAreas[number]["id"];
export type PreviewSelection = PreviewAreaId | "all";
export interface PreviewPoint {
  year: number;
  baseline: number;
  value: number;
  lower: number;
  upper: number;
  isHypothetical: true;
}

const rounded = (value: number) => Math.round(value * 10) / 10;
const bounded = (value: number) => Math.min(100, Math.max(0, value));

export function previewPoint(selection: PreviewSelection, hazard: PreviewHazard, scenario: PreviewScenario, year: number): PreviewPoint {
  if (!Number.isInteger(year) || year < PREVIEW_BASE_YEAR || year > PREVIEW_END_YEAR) throw new Error("Year is outside the example planning period");
  const areas = selection === "all" ? previewAreas : previewAreas.filter((area) => area.id === selection);
  const hazardConfig = previewHazards.find((item) => item.id === hazard);
  const scenarioConfig = previewScenarios.find((item) => item.id === scenario);
  if (!areas.length || !hazardConfig || !scenarioConfig) throw new Error("Unknown example selection");
  const progress = (year - PREVIEW_BASE_YEAR) / (PREVIEW_END_YEAR - PREVIEW_BASE_YEAR);
  const points = areas.map((area) => {
    const baseline = area.baseline[hazard];
    const stress = hazardConfig.rainWeight * scenarioConfig.rainStress + hazardConfig.landWeight * scenarioConfig.landStress;
    const value = bounded(baseline + area.sensitivity * stress * progress);
    const spread = 3 + 6 * progress;
    return { baseline, value, lower: bounded(value - spread), upper: bounded(value + spread) };
  });
  const mean = (field: "baseline" | "value" | "lower" | "upper") => rounded(points.reduce((sum, point) => sum + point[field], 0) / points.length);
  return { year, baseline: mean("baseline"), value: mean("value"), lower: mean("lower"), upper: mean("upper"), isHypothetical: true };
}

export function previewSeries(selection: PreviewSelection, hazard: PreviewHazard, scenario: PreviewScenario): PreviewPoint[] {
  return Array.from({ length: PREVIEW_END_YEAR - PREVIEW_BASE_YEAR + 1 }, (_, index) => previewPoint(selection, hazard, scenario, PREVIEW_BASE_YEAR + index));
}

export function previewAreaName(selection: PreviewSelection) {
  return selection === "all" ? "All 8 example areas" : previewAreas.find((area) => area.id === selection)!.name;
}

export function previewBand(value: number) {
  return value < 35 ? "Lower" : value < 65 ? "Moderate" : "Higher";
}

export function formatPreviewChange(value: number) {
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}`;
}
