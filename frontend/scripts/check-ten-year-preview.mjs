import assert from "node:assert/strict";
import { PREVIEW_BASE_YEAR, PREVIEW_END_YEAR, previewAreas, previewHazards, previewPoint, previewScenarios, previewSeries } from "../src/components/tenYearPreviewData.ts";

// Check relationships that must remain true when the example fixture is edited.
for (const hazard of previewHazards) {
  for (const area of previewAreas) {
    const stable = previewSeries(area.id, hazard.id, "stable");
    assert(stable.every((point) => point.value === point.baseline), "Stable conditions cannot introduce a change");
    for (const scenario of previewScenarios) {
      const series = previewSeries(area.id, hazard.id, scenario.id);
      assert.equal(series.length, 11);
      assert.equal(series[0].year, PREVIEW_BASE_YEAR);
      assert.equal(series.at(-1).year, PREVIEW_END_YEAR);
      assert.equal(series[0].value, area.baseline[hazard.id], "Every scenario starts at the same constructed baseline");
      for (const point of series) {
        assert.equal(point.isHypothetical, true, "Hypothetical provenance survives every calculation");
        assert(point.lower >= 0 && point.upper <= 100 && point.lower <= point.value && point.value <= point.upper, "Example ranges and values stay bounded");
      }
    }
    for (let year = PREVIEW_BASE_YEAR; year <= PREVIEW_END_YEAR; year++) {
      const ordered = previewScenarios.map((scenario) => previewPoint(area.id, hazard.id, scenario.id, year).value);
      assert(ordered.every((value, index) => index === 0 || ordered[index - 1] <= value), "Lowest through highest scenarios remain ordered for every year, area, and flood type");
    }
    assert(previewPoint(area.id, hazard.id, "lowest", PREVIEW_END_YEAR).value < area.baseline[hazard.id], "The improving-conditions example reduces the constructed baseline");
    assert(previewPoint(area.id, hazard.id, "highest", PREVIEW_END_YEAR).value > area.baseline[hazard.id], "The highest-stress example increases the constructed baseline");
  }
  for (const scenario of previewScenarios) {
    const summary = previewPoint("all", hazard.id, scenario.id, PREVIEW_END_YEAR);
    const values = previewAreas.map((area) => previewPoint(area.id, hazard.id, scenario.id, PREVIEW_END_YEAR).value);
    assert(summary.value >= Math.min(...values) && summary.value <= Math.max(...values), "Aggregate remains within constituent example values");
  }
}
assert.throws(() => previewPoint("jhang", "riverine", "moderate", 2025));
assert.throws(() => previewPoint("jhang", "riverine", "moderate", 2037));
assert.throws(() => previewPoint("jhang", "riverine", "moderate", 2030.5));
assert.throws(() => previewPoint("unknown", "riverine", "moderate", 2030));
assert.throws(() => previewPoint("jhang", "unknown", "moderate", 2030));
assert.throws(() => previewPoint("jhang", "riverine", "unknown", 2030));
console.log("PASS: hypothetical provenance, stable baseline, scenario ordering, bounded ranges, aggregate consistency, and invalid-selection guards.");
