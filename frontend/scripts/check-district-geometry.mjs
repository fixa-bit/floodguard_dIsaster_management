import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { alignDistrictScreeningGeometry, districtDisplayGeometry } from "../src/components/districtGeometry.ts";

const boundaries = JSON.parse(await readFile(new URL("../src/data/pakistan/pakistan_districts.geojson", import.meta.url), "utf8"));
const context = JSON.parse(await readFile(new URL("../src/data/pakistan/kashmir_districts.geojson", import.meta.url), "utf8"));
const display = districtDisplayGeometry(boundaries, context);
for (const name of ["Bagh", "Muzaffarabad", "Neelum", "Mirpur", "Srinagar", "Jammu", "Kargil"]) {
  assert.ok(display.features.some((feature) => feature.properties.district_name === name), `${name} must be present without risk data`);
}
assert.equal(display.features.length, 167);
assert.ok(display.features.every((feature) => feature.properties.district_name && feature.properties.risk_probability === undefined));
assert.equal(districtDisplayGeometry(null, null).features.length, 0);
console.log("PASS: 167 named district display polygons, including AJ&K and wider Kashmir, are independent of live risk data.");
const backend = JSON.parse(await readFile(new URL("../../app/gis/data/pakistan_districts.geojson", import.meta.url), "utf8"));
const risk = { type: "FeatureCollection", metadata: { boundary_source: "original model boundaries" },
  features: backend.features.map((feature, index) => ({ ...feature, id: String(index),
    properties: { district_name: feature.properties.shapeName, risk_probability: 0.7, longitude: 73.1, latitude: 32.1 } })) };
const snapshot = structuredClone(risk);
const aligned = alignDistrictScreeningGeometry(risk, boundaries);
for (const name of ["Sargodha", "Khushab", "Hafizabad", "Mandi Bahauddin", "Sukkur", "Ghotki"]) {
  const source = boundaries.features.find((feature) => feature.properties.district === name);
  const result = aligned.features.find((feature) => feature.properties.district_name === name);
  assert.deepEqual(result.geometry, source.geometry, `${name}: risk fill must follow purple border exactly`);
  assert.equal(result.properties.display_geometry_match, true);
  assert.equal(result.properties.risk_probability, 0.7);
  assert.equal(result.properties.longitude, 73.1);
}
assert.deepEqual(risk, snapshot, "Provider features must not be mutated");
assert.deepEqual(aligned.metadata, risk.metadata, "Model provenance must be retained");
assert.equal(alignDistrictScreeningGeometry(null, boundaries), null);
assert.equal(alignDistrictScreeningGeometry(risk, null), risk);
const unmatched = risk.features.find((feature) => feature.properties.district_name === "Azad Kashmir");
assert.equal(aligned.features.find((feature) => feature.id === unmatched.id), unmatched, "Do not assign a combined region's risk to individual districts");
const sargodha = boundaries.features.find((feature) => feature.properties.district === "Sargodha");
const ambiguous = { ...boundaries, features: [...boundaries.features, sargodha] };
assert.equal(alignDistrictScreeningGeometry(risk, ambiguous).features.find((feature) => feature.properties.district_name === "Sargodha").geometry,
  risk.features.find((feature) => feature.properties.district_name === "Sargodha").geometry);
console.log(`PASS: ${aligned.features.filter((feature) => feature.properties.display_geometry_match).length} uniquely matched districts share display geometry; values, provenance, unmatched regions and provider data preserved.`);
