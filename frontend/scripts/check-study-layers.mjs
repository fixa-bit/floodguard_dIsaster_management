import assert from "node:assert/strict";
import { booleanPointInPolygon } from "@turf/boolean-point-in-polygon";
import { clipToCatchment, correspondingStudyLayers, districtAtCoordinate } from "../src/components/studyLayers.ts";
const collection = (...features) => ({ type: "FeatureCollection", features });
const point = (longitude, latitude) => ({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [longitude, latitude] } });
const district = { type: "Feature", properties: { name: "Selected district" }, geometry: { type: "Polygon", coordinates: [
  [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]], [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]],
] } };
const source = collection({ type: "Feature", id: "river", properties: { flow: 325 }, geometry: { type: "LineString", coordinates: [[-1, 5], [11, 5]] } },
  point(1, 1), point(5, 5), point(20, 20));
const snapshot = structuredClone(source);
const clipped = clipToCatchment(source, district);
assert.equal(clipped.features.length, 2, "Only the river and inside point survive");
const river = clipped.features[0];
assert.deepEqual(river.geometry, { type: "MultiLineString", coordinates: [[[0, 5], [4, 5]], [[6, 5], [10, 5]]] });
assert.equal(river.id, "river");
assert.deepEqual(river.properties, { flow: 325 });
assert.deepEqual(source, snapshot, "Original source is preserved for restoration");
assert.equal(clipToCatchment(source, district), clipped, "Clipped data is identity-cached");
const polygon = { type: "Feature", id: "rainfall", properties: { rain: 22 }, geometry: { type: "Polygon", coordinates: [[[-1, -1], [11, -1], [11, 11], [-1, 11], [-1, -1]]] } };
const masked = clipToCatchment(collection(polygon), district).features[0];
assert.equal(booleanPointInPolygon([5, 5], masked), false, "Rainfall mask preserves basin holes");
assert.equal(booleanPointInPolygon([1, 1], masked), true);
assert.equal(booleanPointInPolygon([-0.5, 1], masked), false, "No rainfall outside basin");
assert.equal(masked.properties.rain, 22);
const multi = { type: "Feature", properties: {}, geometry: { type: "MultiLineString", coordinates: [[[1, 1], [9, 1]], [[20, 20], [30, 30]]] } };
assert.deepEqual(clipToCatchment(collection(multi), district).features[0].geometry, { type: "LineString", coordinates: [[1, 1], [9, 1]] });
assert.equal(districtAtCoordinate({ longitude: 1, latitude: 1 }, collection(district, polygon)).features.length, 1);
assert.equal(districtAtCoordinate({ longitude: 5, latitude: 5 }, collection(district)).features.length, 0);
assert.equal(clipToCatchment(source, null).features.length, 0, "No catchment means no fallback area");
const flags = correspondingStudyLayers([
  { layer: "districts", collection: collection(district) },
  { layer: "reports", collection: clipToCatchment(collection(point(1, 1)), district) },
  { layer: "incidents", collection: clipToCatchment(collection(point(20, 20)), district) },
  { layer: "gauges", collection: null },
  { layer: "water", collection: clipped },
]);
assert.deepEqual(flags, { districts: true, reports: true, water: true });
console.log("PASS: exact basin clipping for points, crossing/reentering rivers, multiline features, rainfall polygons and holes; one district, preserved IDs/values, immutable sources and cached restoration.");
