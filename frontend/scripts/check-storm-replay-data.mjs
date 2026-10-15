import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { currentRoutes, distanceKm, inspectReplayLine, polygonParts, REPLAY_PEAK_MINUTE, replayLevel, replayScenarios, routePoint, waterPolygons } from "../src/components/stormReplayData.ts";

const square = (x1, y1, x2, y2) => [[x1, y1], [x2, y1], [x2, y2], [x1, y2], [x1, y1]];
const withHole = { type: "Polygon", coordinates: [square(0, 0, 4, 4), square(1, 1, 3, 3)] };
const line = [[-2, 2], [6, 2]];
const result = inspectReplayLine(line, [withHole]);
assert(Math.abs(result.wetKm / result.lengthKm - .25) < .002, "Inspection excludes polygon holes and dry portions of a crossing");
assert.equal(inspectReplayLine(line, []).wetKm, 0, "No footprint cannot produce water overlap");
assert.equal(inspectReplayLine([[0, 0]], [withHole]), null);
assert.equal(inspectReplayLine([[0, 0], [0, 0]], [withHole]).lengthKm, 0);
assert.equal(polygonParts({ type: "GeometryCollection", geometries: [withHole, { type: "LineString", coordinates: [[0, 0], [1, 1]] }] }).length, 1);
assert(Math.abs(distanceKm([0, 0], [1, 0]) - 111.195) < .01);
for (const scenario of replayScenarios) {
  assert.equal(replayLevel(0, scenario.id), 0);
  assert.equal(replayLevel(360, scenario.id), 0);
  assert.equal(replayLevel(REPLAY_PEAK_MINUTE, scenario.id), scenario.peak);
  let previous = 0;
  for (let minute = 0; minute <= REPLAY_PEAK_MINUTE; minute++) {
    const level = replayLevel(minute, scenario.id);
    assert(level >= previous && level <= scenario.peak, "Rising example stays within its declared ordinal levels"); previous = level;
  }
  for (let minute = REPLAY_PEAK_MINUTE; minute <= 360; minute++) {
    const level = replayLevel(minute, scenario.id);
    assert(level <= previous && level >= 0, "Recession cannot grow the footprint"); previous = level;
  }
}
for (const id of ["jhang", "multan", "lahore", "rawalpindi", "charsadda", "sukkur", "dadu", "badin"]) {
  const original = await readFile(new URL(`../src/data/outlook-exposure/${id}.geojson`, import.meta.url), "utf8");
  const data = JSON.parse(original);
  assert.equal(waterPolygons(data, 0).length, 0);
  if (!data.supported) assert.equal(waterPolygons(data, 5).length, 0);
  for (const route of currentRoutes(data)) {
    assert(route.length > 0);
    for (const fraction of [0, .5, .999, 1.5]) {
      const point = routePoint(route, fraction);
      assert(point.point.every(Number.isFinite) && point.normal.every(Number.isFinite));
    }
  }
  inspectReplayLine([[data.bounds[0], data.bounds[1]], [data.bounds[2], data.bounds[3]]], waterPolygons(data, 5));
  assert.equal(JSON.stringify(data), JSON.stringify(JSON.parse(original)), `${id}: presentation helpers cannot mutate population, water, or source totals`);
}
console.log("PASS: independent line-overlap cases including holes/dry/zero-length lines, all scenarios' rise/retreat, all eight districts' geometry and immutable source data.");
