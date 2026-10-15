import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { cinematicPopulation, densityFocus, riverFocus } from "../src/components/simulationCinematicData.ts";

for (const id of ["jhang", "multan", "lahore", "rawalpindi", "charsadda", "sukkur", "dadu", "badin"]) {
  const data = JSON.parse(await readFile(new URL(`../src/data/outlook-exposure/${id}.geojson`, import.meta.url), "utf8"));
  const original = JSON.stringify(data);
  const columns = cinematicPopulation(data);
  assert.equal(columns.features.length, data.population.features.length, "Every original population cell has one display glyph");
  assert.equal(new Set(columns.features.map((feature) => feature.id)).size, columns.features.length);
  assert.equal(columns.features.reduce((total, feature) => total + feature.properties.population_2025, 0), data.population.features.reduce((total, feature) => total + feature.properties.population_2025, 0), "Glyph creation preserves modeled population counts");
  assert(densityFocus(data)?.every(Number.isFinite), "Population focus uses a real populated cell");
  assert.equal(Boolean(riverFocus(data, [72.3187, 31.2681])), data.supported, "Missing river data never invents a camera target");
  assert.equal(JSON.stringify(data), original, "Cinematic presentation cannot mutate source grids, extents, or exposure estimates");
}
console.log("PASS: cinematic glyphs preserve cell identities and population counts; camera targets use existing inputs; source grids and estimates remain unchanged for all eight districts.");
