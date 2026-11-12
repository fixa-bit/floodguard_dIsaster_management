import * as maplibregl from "maplibre-gl";
import { inBatches, persistentTileBytes, prunePersistentCaches, untilAborted } from "./tileCache";

// Satellite basemap tiles served through a local cache: recently used tiles stay
// in memory, and every tile is kept in persistent browser storage so stops seen
// before (this session or earlier today) appear without waiting on the network.

const upstream = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/";
/** Tile URL template for the Esri World Imagery basemap, via the local cache. */
export const cachedImageryTiles = "cached-imagery://{z}/{y}/{x}";

// Esri serves these tiles with a one-day max-age, so the stored copies live in a
// cache named for the current day and earlier days' caches are deleted.
const cacheName = `floodguard-imagery-${new Date().toISOString().slice(0, 10)}`;
prunePersistentCaches("floodguard-imagery-", cacheName);

// With ?mapDiagnostics=1, counts how many tiles the map got instantly versus had to wait for.
const stats = { requests: 0, instant: 0, waited: 0, waitedMs: 0 };
if (new URLSearchParams(window.location.search).get("mapDiagnostics") === "1") {
  (window as unknown as { __imageryStats: typeof stats }).__imageryStats = stats;
}

const maxMemoryTiles = 600;
const memory = new Map<string, Promise<ArrayBuffer>>();
function imageryBytes(key: string) {
  const hit = memory.get(key);
  if (hit) { memory.delete(key); memory.set(key, hit); return hit; }
  const pending = persistentTileBytes(upstream + key, cacheName);
  memory.set(key, pending);
  pending.catch(() => { if (memory.get(key) === pending) memory.delete(key); });
  for (const stale of memory.keys()) { if (memory.size <= maxMemoryTiles) break; memory.delete(stale); }
  return pending;
}

maplibregl.addProtocol("cached-imagery", async (params, controller) => {
  const key = params.url.replace("cached-imagery://", "");
  if (!/^\d+\/\d+\/\d+$/.test(key)) throw new Error("Invalid imagery tile request");
  const started = performance.now();
  // Copy: the map may transfer the buffer to a worker, which would empty the cached one.
  const data = (await untilAborted(imageryBytes(key), controller.signal)).slice(0);
  const waited = performance.now() - started;
  stats.requests++;
  if (waited < 40) stats.instant++; else { stats.waited++; stats.waitedMs += Math.round(waited); }
  return { data };
});

/** Loads imagery tiles (keys "z/x/y") into the caches ahead of the camera. */
export function preloadImageryTiles(keys: string[], concurrency = 12) {
  const tiles = [...new Set(keys)].map((key) => { const [z, x, y] = key.split("/"); return `${z}/${y}/${x}`; });
  return inBatches(tiles, imageryBytes, concurrency);
}
