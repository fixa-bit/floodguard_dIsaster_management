import * as maplibregl from "maplibre-gl";
import { inBatches, persistentTileBytes, prunePersistentCaches, untilAborted } from "./tileCache";

// Satellite basemap tiles. Up to zoom 13 the imagery is Sentinel-2 cloudless:
// the tiles the monitoring tour draws (every stop, every flight between them)
// ship with the app in public/station-imagery, so the tour never waits on a
// server; any other tile comes from EOX and is kept in persistent browser
// storage. Closer zooms, which only the free map reaches, are Esri World Imagery.
// Recently used tiles also stay in memory.

/** Tile URL template for the satellite basemap, via the local caches. */
export const cachedImageryTiles = "cached-imagery://{z}/{y}/{x}";
/** Highest zoom drawn from Sentinel-2 (its 10 m pixels are about zoom 13 to 14). */
export const sentinelMaxZoom = 13;
export const imageryAttribution = '<a href="https://s2maps.eu">Sentinel-2 cloudless</a> by EOX IT Services GmbH (contains modified Copernicus Sentinel data 2016 &amp; 2017, CC BY 4.0); closer zooms &copy; Esri, Maxar, Earthstar Geographics';

const sentinel = "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/g/";   // {z}/{y}/{x}.jpg
const esri = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/";   // {z}/{y}/{x}
// The 2016 mosaic never changes, so its stored copies are kept indefinitely.
const sentinelCache = "floodguard-sentinel2-2016";
// Esri serves its tiles with a one-day max-age, so those stored copies live in a
// cache named for the current day and earlier days' caches are deleted.
const esriCache = `floodguard-imagery-${new Date().toISOString().slice(0, 10)}`;
prunePersistentCaches("floodguard-imagery-", esriCache);

// The local pack's index: for each zoom and column, runs of rows [first, last] present.
const packBase = `${import.meta.env.BASE_URL}station-imagery/`;
type PackIndex = Record<string, Record<string, [number, number][]>>;
let packIndex: Promise<PackIndex> | null = null;
const pack = () => packIndex ??= fetch(packBase + "manifest.json")
  .then(async (response) => response.ok ? ((await response.json()) as { tiles?: PackIndex }).tiles ?? {} : {})
  .catch(() => ({}));
const inPack = (index: PackIndex, z: number, x: number, y: number) =>
  index[z]?.[x]?.some(([first, last]) => y >= first && y <= last) ?? false;

// With ?mapDiagnostics=1, counts how many tiles the map got instantly versus had to wait for.
const stats = { requests: 0, instant: 0, waited: 0, waitedMs: 0, fromPack: 0 };
if (new URLSearchParams(window.location.search).get("mapDiagnostics") === "1") {
  (window as unknown as { __imageryStats: typeof stats }).__imageryStats = stats;
}

async function localTile(url: string) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.arrayBuffer();
}

/** One tile's bytes, `key` being "z/y/x": from the local pack, else the persistent cache, else the network. */
async function fetchImagery(key: string) {
  const [z, y, x] = key.split("/").map(Number);
  if (z > sentinelMaxZoom) return persistentTileBytes(esri + key, esriCache);
  if (inPack(await pack(), z, x, y)) {
    stats.fromPack++;
    try { return await localTile(`${packBase}${z}/${x}/${y}.jpg`); } catch { /* pack incomplete on this server: use the network */ }
  }
  return persistentTileBytes(`${sentinel}${key}.jpg`, sentinelCache);
}

const maxMemoryTiles = 1500;
const memory = new Map<string, Promise<ArrayBuffer>>();
function imageryBytes(key: string) {
  const hit = memory.get(key);
  if (hit) { memory.delete(key); memory.set(key, hit); return hit; }
  const pending = fetchImagery(key);
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

/** Highest zoom of the always-ready backdrop imagery that sits under the detailed tiles. */
export const imageryBackdropMaxZoom = 7;
type Region = [west: number, south: number, east: number, north: number];

/** The backdrop's tiles ("z/x/y"): zoom 4 to 7 over `region`, zoom 4 and 5 over the wider `horizon`. */
export function backdropTileKeys(region: Region, horizon: Region = region) {
  const keys: string[] = [];
  const row = (latitude: number, scale: number) => Math.floor((1 - Math.asinh(Math.tan(latitude * Math.PI / 180)) / Math.PI) / 2 * scale);
  for (let z = 4; z <= imageryBackdropMaxZoom; z++) {
    const [west, south, east, north] = z <= 5 ? horizon : region;
    const scale = 2 ** z;
    for (let x = Math.floor((west + 180) / 360 * scale); x <= Math.floor((east + 180) / 360 * scale); x++) {
      for (let y = row(north, scale); y <= row(south, scale); y++) keys.push(`${z}/${x}/${y}`);
    }
  }
  return keys;
}

let backdropLoaded: Promise<void> | null = null;
/**
 * Loads the coarse backdrop imagery once (see `backdropTileKeys`). The map draws
 * it beneath the detailed tiles, so wherever the camera goes there is already a
 * picture to sharpen rather than an empty tile to fill.
 */
export function preloadImageryBackdrop(region: Region, horizon: Region = region) {
  return backdropLoaded ??= preloadImageryTiles(backdropTileKeys(region, horizon), 8);
}

/** Loads imagery tiles (keys "z/x/y") into the caches ahead of the camera. */
export function preloadImageryTiles(keys: string[], concurrency = 12) {
  const tiles = [...new Set(keys)].map((key) => { const [z, x, y] = key.split("/"); return `${z}/${y}/${x}`; });
  return inBatches(tiles, imageryBytes, concurrency);
}
