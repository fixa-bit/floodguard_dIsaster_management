import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import { booleanPointInPolygon } from "@turf/boolean-point-in-polygon";
import { monitoringCategories, monitoringSites } from "../src/components/monitoringSites.ts";
import { clipToCatchment } from "../src/components/studyLayers.ts";

assert.equal(monitoringSites.features.length, 28);
assert.equal(new Set(monitoringSites.features.map((feature) => feature.id)).size, 28);
assert.equal(new Set(monitoringCategories.map((category) => category.shape)).size, 4);
assert.equal(new Set(monitoringCategories.map((category) => category.color)).size, 1, "Category icons must not encode flood risk with color");
assert.deepEqual(monitoringCategories.map((category) => category.shape), ["barrier", "tower", "dam", "merge"]);
assert.deepEqual(monitoringCategories.map(({ id }) => monitoringSites.features.filter((feature) => feature.properties.category === id).length), [15, 6, 3, 4]);
const stations = JSON.parse(execFileSync("python", ["-c", "import ast,json,sys; tree=ast.parse(open(sys.argv[1]).read()); print(json.dumps(next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='STATIONS' for t in n.targets))))",
  new URL("../../app/gis/river_stations.py", import.meta.url).pathname.replace(/^\/(\w:)/, "$1")], { encoding: "utf8" }));
for (const feature of monitoringSites.features) {
  assert.ok(feature.properties.source.startsWith("https://"));
  if (feature.properties.stationId) {
    const station = stations.find(([id]) => id === feature.properties.stationId);
    assert.ok(station, feature.id);
    assert.deepEqual(feature.geometry.coordinates, [station[4], station[3]], `Canonical coordinate for ${feature.id}`);
  }
  if (feature.properties.category === "confluences") assert.equal(feature.properties.stationId, null);
}
assert.equal(monitoringSites.features.find((feature) => feature.id === "KALABAGH").properties.category, "upstream");
const catchments = JSON.parse(await readFile(new URL("../src/data/pakistan/catchment_areas.geojson", import.meta.url), "utf8"));
const catchment = catchments.features.find((feature) => booleanPointInPolygon([73.0479, 33.6844], feature));
const scoped = clipToCatchment(monitoringSites, catchment);
assert.ok(scoped.features.length < 28);
for (const feature of scoped.features) assert.ok(booleanPointInPolygon(feature, catchment));
assert.equal(clipToCatchment(monitoringSites, null).features.length, 0);
console.log("28 unique monitoring sites; four symbols; canonical station coordinates; catchment scope verified.");
