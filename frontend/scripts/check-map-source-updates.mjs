import assert from "node:assert/strict";
import { updateMapSource, sourceUpdateCount } from "../src/components/mapSourceUpdates.ts";
import { loadMapAsset } from "../src/components/mapAssets.ts";

const geometry = { type: "FeatureCollection", features: [{ type: "Feature", properties: { value: 1 }, geometry: { type: "Point", coordinates: [74, 32] } }] };
const snapshot = structuredClone(geometry);
const source = { writes: [], serialize: () => ({ data: geometry }), setData(data) { this.writes.push(data); } };
assert.equal(updateMapSource(undefined, geometry), false);
assert.equal(updateMapSource(source, geometry), false, "Initial source must not be serialized twice");
for (let i = 0; i < 100; i++) assert.equal(updateMapSource(source, geometry), false);
assert.equal(source.writes.length, 0, "Unrelated refreshes must not rebuild static geometry");
const changed = { ...geometry, features: [{ ...geometry.features[0], properties: { value: 2 } }] };
assert.equal(updateMapSource(source, changed), true);
assert.equal(updateMapSource(source, changed), false);
assert.equal(sourceUpdateCount(source), 1);
assert.equal(source.writes[0], changed, "Changed values must reach the worker unchanged");
assert.deepEqual(geometry, snapshot);
const replacementSource = { writes: [], serialize: () => ({ data: geometry }), setData(data) { this.writes.push(data); } };
assert.equal(updateMapSource(replacementSource, changed), true, "A recreated map has an independent cache");

const originalFetch = globalThis.fetch;
let downloads = 0;
globalThis.fetch = async (url) => {
  downloads++;
  if (url === "retry" && downloads === 2) throw new Error("Temporary failure");
  return { ok: true, json: async () => geometry };
};
try {
  const first = loadMapAsset("inventory");
  assert.equal(loadMapAsset("inventory"), first, "Concurrent requests must share the download");
  assert.equal(await first, geometry);
  assert.equal(await loadMapAsset("inventory"), geometry);
  assert.equal(downloads, 1, "View changes must reuse parsed boundary data");
  await assert.rejects(loadMapAsset("retry"), /Temporary failure/);
  assert.equal(await loadMapAsset("retry"), geometry);
  assert.equal(downloads, 3, "Failed downloads must remain retryable");
} finally { globalThis.fetch = originalFetch; }
console.log("PASS: 100 unchanged source updates skipped; changed values and new maps update correctly; asset downloads are shared, cached and retryable.");
