import { createHash } from "node:crypto";
import { access, mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const stationCatalogPath = join(frontendRoot, "src/components/monitoringSites.ts");
const terrainRoot = join(frontendRoot, "public/station-terrain");
const manifestPath = join(terrainRoot, "manifest.json");
const terrainSource = "https://elevation-tiles-prod.s3.amazonaws.com/terrarium";
const minZoom = 9;
const maxZoom = 13;
const tileRadius = 1;
const concurrency = 6;
const retryLimit = 4;
const dryRun = process.argv.includes("--dry-run");

function stationCatalog(source) {
  const rows = source.match(/const rows:\s*SiteRow\[\]\s*=\s*\[([\s\S]*?)\n\];/);
  if (!rows) throw new Error(`Could not locate the monitoring station table in ${stationCatalogPath}`);

  const rowPattern = /^\s*\["([^"]+)",\s*"([^"]+)",\s*"[^"]+",\s*"[^"]+",\s*(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)/gm;
  const stations = [...rows[1].matchAll(rowPattern)].map((match) => ({
    id: match[1],
    name: match[2],
    longitude: Number(match[3]),
    latitude: Number(match[4]),
  }));
  if (stations.length < 20) throw new Error(`Only found ${stations.length} monitoring stations; refusing to update an incomplete terrain catalog.`);
  return stations;
}

function tileFor(longitude, latitude, zoom) {
  const scale = 2 ** zoom;
  const x = Math.floor(((longitude + 180) / 360) * scale);
  const latitudeRadians = (latitude * Math.PI) / 180;
  const y = Math.floor(((1 - Math.asinh(Math.tan(latitudeRadians)) / Math.PI) / 2) * scale);
  return { x, y };
}

function stationTileKeys(stations) {
  const keys = new Set();
  for (const station of stations) {
    for (let zoom = minZoom; zoom <= maxZoom; zoom += 1) {
      const { x, y } = tileFor(station.longitude, station.latitude, zoom);
      const scale = 2 ** zoom;
      for (let dx = -tileRadius; dx <= tileRadius; dx += 1) {
        for (let dy = -tileRadius; dy <= tileRadius; dy += 1) {
          const tileX = ((x + dx) % scale + scale) % scale;
          const tileY = y + dy;
          if (tileY >= 0 && tileY < scale) keys.add(`${zoom}/${tileX}/${tileY}.png`);
        }
      }
    }
  }
  return [...keys].sort((a, b) => {
    const [az, ax, ay] = a.split("/").map(Number);
    const [bz, bx, by] = b.split("/").map(Number);
    return az - bz || ax - bx || ay - by;
  });
}

function pngMetadata(bytes, key) {
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  if (bytes.length < 64 || !bytes.subarray(0, 8).equals(signature)) {
    throw new Error(`Terrain tile ${key} is not a valid PNG.`);
  }
  return { sha256: createHash("sha256").update(bytes).digest("hex"), bytes: bytes.length };
}

async function exists(path) {
  try { await access(path); return true; }
  catch { return false; }
}

async function downloadTile(key) {
  let lastError;
  for (let attempt = 0; attempt < retryLimit; attempt += 1) {
    try {
      const response = await fetch(`${terrainSource}/${key}`, { signal: AbortSignal.timeout(30000) });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const bytes = Buffer.from(await response.arrayBuffer());
      const metadata = pngMetadata(bytes, key);
      const tilePath = join(terrainRoot, ...key.split("/"));
      await mkdir(dirname(tilePath), { recursive: true });
      await writeFile(tilePath, bytes);
      return metadata;
    } catch (error) {
      lastError = error;
      if (attempt + 1 < retryLimit) await new Promise((resolveDelay) => setTimeout(resolveDelay, 750 * 2 ** attempt));
    }
  }
  throw new Error(`Could not download ${key}: ${lastError instanceof Error ? lastError.message : String(lastError)}`);
}

const stations = stationCatalog(await readFile(stationCatalogPath, "utf8"));
const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
if (!manifest.tiles || typeof manifest.tiles !== "object") throw new Error("Terrain manifest has no tile index.");
const requestedKeys = stationTileKeys(stations);
const work = [];

for (const key of requestedKeys) {
  const tilePath = join(terrainRoot, ...key.split("/"));
  if (manifest.tiles[key] && await exists(tilePath)) continue;
  if (!manifest.tiles[key] && await exists(tilePath)) {
    manifest.tiles[key] = pngMetadata(await readFile(tilePath), key);
    continue;
  }
  work.push(key);
}

console.log(`${stations.length} stations; ${requestedKeys.length} needed DEM tiles; ${work.length} downloads.`);
if (dryRun) process.exit(0);

let next = 0;
let completed = 0;
const worker = async () => {
  while (true) {
    const index = next++;
    if (index >= work.length) return;
    const key = work[index];
    manifest.tiles[key] = await downloadTile(key);
    completed += 1;
    if (completed % 25 === 0 || completed === work.length) {
      console.log(`Downloaded ${completed}/${work.length} station terrain tiles.`);
    }
  }
};
await Promise.all(Array.from({ length: concurrency }, worker));

manifest.stations = Object.fromEntries(stations.map(({ id, longitude, latitude }) => [id, [longitude, latitude]]));
manifest.station_tile_coverage = {
  source: terrainSource,
  min_zoom: minZoom,
  max_zoom: maxZoom,
  radius_tiles: tileRadius,
  note: "Locally cached Terrarium DEM tiles around every monitoring station; the app still streams outside these station footprints.",
};
const temporaryManifest = `${manifestPath}.tmp`;
await writeFile(temporaryManifest, `${JSON.stringify(manifest, null, 2)}\n`);
await rename(temporaryManifest, manifestPath);
console.log(`Updated ${manifestPath} with terrain for all ${stations.length} stations.`);
