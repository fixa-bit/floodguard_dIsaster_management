import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { gzipSync, gunzipSync } from "node:zlib";
import { createHash } from "node:crypto";
import { loadMapAsset } from "../src/components/mapAssets.ts";
import { preview } from "vite";

for (const name of ["glaciers", "pakistan_districts", "kashmir_districts"]) {
  const raw = await readFile(new URL(`../src/data/pakistan/${name}.geojson`, import.meta.url));
  const digest = createHash("sha256").update(raw).digest("hex").slice(0, 16);
  const file = `${name}-${digest}.geojson.gz`;
  assert.ok((await readdir(new URL("../dist/assets/", import.meta.url))).includes(file));
  const compressed = await readFile(new URL(`../dist/assets/${file}`, import.meta.url));
  assert.deepEqual(gunzipSync(compressed), raw, "Compression must preserve every coordinate and mapping value");
  assert.ok(compressed.length < raw.length * 0.5, "Initial transfer must be substantially smaller");
  console.log(`${name}: ${(raw.length / 1e6).toFixed(2)} MB -> ${(compressed.length / 1e6).toFixed(2)} MB (${(100 * (1 - compressed.length / raw.length)).toFixed(1)}% smaller)`);
}

const originalFetch = globalThis.fetch;
const originalCaches = globalThis.caches;
const data = { type: "FeatureCollection", features: [{ geometry: { type: "Point", coordinates: [74.5809550000709, 31.59423500020307] }, properties: { value: 42 } }] };
const bytes = gzipSync(JSON.stringify(data));
const stored = new Map();
const cache = {
  async match(url) { return stored.get(url)?.clone(); },
  async put(url, response) { stored.set(url, new Response(await response.arrayBuffer())); },
  async delete(url) { return stored.delete(url); },
};
globalThis.caches = { open: async () => cache };
let downloads = 0;
globalThis.fetch = async () => { downloads++; return new Response(bytes); };
try {
  const firstUrl = "http://localhost/assets/glaciers-1111111111111111.geojson.gz";
  assert.deepEqual(await loadMapAsset(firstUrl), data);
  for (let i = 0; i < 100 && !stored.has(firstUrl); i++) await new Promise((resolve) => setTimeout(resolve, 5));
  assert.ok(stored.has(firstUrl), "Compressed response must be persisted");
  const freshPage = await import("../src/components/mapAssets.ts?fresh-page");
  assert.deepEqual(await freshPage.loadMapAsset(firstUrl), data);
  assert.equal(downloads, 1, "A fresh page must use persistent cache without downloading");
  await freshPage.loadMapAsset("http://localhost/assets/glaciers-2222222222222222.geojson.gz");
  assert.equal(downloads, 2, "A new content version must download fresh data");
  const corrupt = "http://localhost/assets/glaciers-3333333333333333.geojson.gz";
  stored.set(corrupt, new Response("broken data"));
  assert.deepEqual(await loadMapAsset(corrupt), data);
  assert.equal(downloads, 3, "A corrupt cached entry must recover from the network");
  const decoded = "http://localhost/assets/glaciers-4444444444444444.geojson.gz";
  globalThis.fetch = async () => new Response(JSON.stringify(data));
  assert.deepEqual(await loadMapAsset(decoded), data, "HTTP-decoded responses must not be decompressed twice");
} finally {
  globalThis.fetch = originalFetch;
  if (originalCaches === undefined) delete globalThis.caches;
  else globalThis.caches = originalCaches;
}
console.log("PASS: exact geometry round trips; gzip decoding, persistent cache, version invalidation, corrupt-cache recovery and HTTP-decoded responses work.");

const server = await preview({ preview: { host: "127.0.0.1", port: 3012, strictPort: true } });
try {
  const files = (await readdir(new URL("../dist/assets/", import.meta.url))).filter((name) => name.endsWith(".geojson.gz"));
  for (const file of files) {
    const url = `http://127.0.0.1:3012/assets/${file}`;
    const response = await fetch(url);
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("content-type"), "application/gzip");
    assert.equal(response.headers.get("cache-control"), "public, max-age=31536000, immutable");
    const raw = Buffer.from(await response.arrayBuffer());
    assert.deepEqual(raw, await readFile(new URL(`../dist/assets/${file}`, import.meta.url)));
    const revalidated = await fetch(url, { headers: { "If-None-Match": response.headers.get("etag") } });
    assert.equal(revalidated.status, 304);
  }
  console.log("PASS: production preview serves compressed bytes with immutable caching and 304 ETag revalidation.");
} finally {
  server.httpServer.closeAllConnections();
  await new Promise((resolve, reject) => server.httpServer.close((error) => error ? reject(error) : resolve()));
}
