import assert from "node:assert/strict";
import { parseMapCoordinate, indexCoordinatePolygons, lookupCoordinatePolygons } from "../src/components/coordinateLookup.ts";

assert.deepEqual(parseMapCoordinate(" 33.6844 ", "73.0479"), { latitude: 33.6844, longitude: 73.0479 });
assert.deepEqual(parseMapCoordinate("0", "0"), { latitude: 0, longitude: 0 });
for (const [lat, lon] of [["", "0"], ["0", " "], ["NaN", "0"], ["1", "Infinity"], ["91", "0"], ["0", "181"], ["-86", "0"]]) {
  assert.throws(() => parseMapCoordinate(lat, lon));
}
const collection = { type: "FeatureCollection", features: [{ type: "Feature", properties: { name: "District with a hole", severity: "HIGH", risk_probability: 0.7 },
  geometry: { type: "Polygon", coordinates: [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]], [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]] } }] };
const snapshot = structuredClone(collection);
const index = indexCoordinatePolygons([{ kind: "District", collection, nameKey: "name", fields: [["risk_probability", "Risk"], ["missing", "Missing"]] }]);
assert.equal(lookupCoordinatePolygons({ latitude: 3, longitude: 3 }, index)[0].name, "District with a hole");
assert.deepEqual(index[0].match.fields, [["Risk", "70%"]]);
assert.equal(lookupCoordinatePolygons({ latitude: 5, longitude: 5 }, index).length, 0);
assert.equal(lookupCoordinatePolygons({ latitude: 15, longitude: 15 }, index).length, 0);
assert.equal(lookupCoordinatePolygons({ latitude: 0, longitude: 0 }, index).length, 1);
assert.deepEqual(collection, snapshot);
const multi = { type: "FeatureCollection", features: [{ type: "Feature", properties: { name: "Two islands" },
  geometry: { type: "MultiPolygon", coordinates: [collection.features[0].geometry.coordinates,
    [[[20, 20], [22, 20], [22, 22], [20, 22], [20, 20]]]] } }] };
const multiIndex = indexCoordinatePolygons([{ kind: "District", collection: multi, nameKey: "name", fields: [] }]);
assert.equal(lookupCoordinatePolygons({ latitude: 21, longitude: 21 }, multiIndex).length, 1);
assert.equal(lookupCoordinatePolygons({ latitude: 15, longitude: 15 }, multiIndex).length, 0);
assert.equal(lookupCoordinatePolygons({ latitude: 5, longitude: 5 }, multiIndex).length, 0);
console.log("PASS: coordinate validation, zero values, map limits, polygon holes, edges, missing values and immutable lookup.");
