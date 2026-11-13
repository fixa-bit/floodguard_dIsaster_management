// Builds the monitoring tour's local tile pack, so the tour never downloads a
// tile while the camera moves.
//
//   node scripts/build-tour-tile-pack.mjs --plan [--url http://127.0.0.1:3000] [--viewport 1920x945]
//     With the dev server running, opens the app in headless Edge, lets the tour
//     land at a few stops (the tour measures which tiles a stop view covers), then
//     asks the app for every tile the 3D and 2D tours draw: each stop with its
//     hold, each flight between stops at every level of detail, the first flight
//     in from the overview, and the coarse backdrop. Writes public/station-imagery/plan.json.
//
//   node scripts/build-tour-tile-pack.mjs [--dry-run]
//     Downloads the planned tiles that are missing: Sentinel-2 cloudless imagery
//     (EOX, CC BY 4.0) into public/station-imagery, Terrarium elevation into
//     public/station-terrain. Existing tiles are never downloaded again.
import { createHash } from "node:crypto";
import { access, mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const imageryRoot = join(frontendRoot, "public/station-imagery");
const terrainRoot = join(frontendRoot, "public/station-terrain");
const planPath = join(imageryRoot, "plan.json");
const imageryManifestPath = join(imageryRoot, "manifest.json");
const terrainManifestPath = join(terrainRoot, "manifest.json");
const imagerySource = "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/g";   // /{z}/{y}/{x}.jpg
const terrainSource = "https://elevation-tiles-prod.s3.amazonaws.com/terrarium";   // /{z}/{x}/{y}.png
const concurrency = 6;
const retryLimit = 4;

const argument = (name, fallback) => {
  const index = process.argv.indexOf(name);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
};
const exists = (path) => access(path).then(() => true, () => false);
const byTile = (a, b) => {
  const [az, ax, ay] = a.split("/").map(Number), [bz, bx, by] = b.split("/").map(Number);
  return az - bz || ax - bx || ay - by;
};

async function plan() {
  const { chromium } = await import("playwright");
  const url = new URL(argument("--url", "http://127.0.0.1:3000/"));
  url.searchParams.set("mapDiagnostics", "1");
  const [width, height] = argument("--viewport", "1920x945").split("x").map(Number);
  const browser = await chromium.launch({
    channel: "msedge", headless: true,
    // The real graphics card: a software renderer is too slow to run the tour.
    args: ["--use-angle=d3d11", "--enable-gpu", "--ignore-gpu-blocklist"],
  });
  try {
    const context = await browser.newContext({ viewport: { width, height } });
    const page = await context.newPage();
    const ready = async () => {
      await page.goto(url.href, { waitUntil: "domcontentloaded" });
      await page.waitForFunction(() => !document.querySelector(".station-monitoring-toggle")?.disabled && window.__monitoringTourTiles, null, { timeout: 240000 });
      await page.waitForTimeout(6000);   // the opening globe flight settles on the overview
    };
    const arrivals = async (count) => {
      for (let index = 0; index < count; index++) {
        await page.waitForFunction(() => (window.__floodguardMap.getContainer().dataset.monitoringArrival ?? "") !== "", null, { timeout: 120000 });
        console.log(`  landed at ${await page.evaluate(() => window.__floodguardMap.getContainer().dataset.cameraStation)}`);
        if (index + 1 < count) await page.waitForFunction(() => (window.__floodguardMap.getContainer().dataset.monitoringArrival ?? "") === "", null, { timeout: 60000 });
      }
    };
    await ready();
    console.log("Measuring stop views (3D close-up and catchment stops, then a 2D stop)...");
    await page.locator(".station-monitoring-toggle").click();
    await arrivals(4);   // the first three stops are close-ups, the fourth a catchment view
    await page.locator(".station-monitoring-view button", { hasText: "2D map" }).click();
    await arrivals(1);
    await page.locator(".station-monitoring-toggle").click();
    // A fresh page starts at the overview, where the tour's first flight begins; the measurements stay in local storage.
    await ready();
    const tours = await page.evaluate(() => ["3d", "2d"].map((view) => window.__monitoringTourTiles(view)));
    if (!tours.every((tour) => tour.measured)) throw new Error("The tour did not measure its stop views; the plan would be incomplete.");
    const imagery = [...new Set(tours.flatMap((tour) => tour.imagery))].sort(byTile);
    const terrain = [...new Set(tours.flatMap((tour) => tour.terrain))].filter((key) => Number(key.split("/")[0]) <= 13).sort(byTile);
    await mkdir(imageryRoot, { recursive: true });
    await writeFile(planPath, `${JSON.stringify({ viewport: `${width}x${height}`, created: new Date().toISOString(), imagery, terrain })}\n`);
    console.log(`Planned ${imagery.length} imagery tiles and ${terrain.length} terrain tiles; wrote ${planPath}.`);
  } finally {
    await browser.close();
  }
}

async function download(url, check) {
  let lastError;
  for (let attempt = 0; attempt < retryLimit; attempt++) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(30000) });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const bytes = Buffer.from(await response.arrayBuffer());
      check(bytes);
      return bytes;
    } catch (error) {
      lastError = error;
      if (attempt + 1 < retryLimit) await new Promise((resolveDelay) => setTimeout(resolveDelay, 750 * 2 ** attempt));
    }
  }
  throw new Error(`Could not download ${url}: ${lastError instanceof Error ? lastError.message : String(lastError)}`);
}

async function inParallel(items, work, label) {
  let next = 0, completed = 0;
  const failures = [];
  await Promise.all(Array.from({ length: concurrency }, async () => {
    while (next < items.length) {
      const item = items[next++];
      try { await work(item); } catch (error) { failures.push(`${item}: ${error.message}`); }
      completed++;
      if (completed % 250 === 0 || completed === items.length) console.log(`  ${label}: ${completed}/${items.length}`);
    }
  }));
  return failures;
}

const isJpeg = (bytes) => { if (bytes.length < 100 || bytes[0] !== 0xff || bytes[1] !== 0xd8) throw new Error("not a JPEG"); };
const isPng = (bytes) => { if (bytes.length < 64 || !bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) throw new Error("not a PNG"); };

/** Runs of consecutive rows per zoom and column: the compact index the app reads. */
function packIndex(keys) {
  const tiles = {};
  for (const key of [...keys].sort(byTile)) {
    const [z, x, y] = key.split("/").map(Number);
    const runs = ((tiles[z] ??= {})[x] ??= []);
    const last = runs.at(-1);
    if (last && last[1] === y - 1) last[1] = y; else runs.push([y, y]);
  }
  return tiles;
}

/**
 * The planned tiles and their neighbours from zoom 8 up: the camera's real path
 * (from wherever it actually is) drifts from the planned one by a tile or so.
 */
function withMargin(keys) {
  const tiles = new Set(keys);
  for (const key of keys) {
    const [z, x, y] = key.split("/").map(Number), scale = 2 ** z;
    if (z < 8) continue;
    for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
      if (y + dy >= 0 && y + dy < scale) tiles.add(`${z}/${(x + dx + scale) % scale}/${y + dy}`);
    }
  }
  return [...tiles].sort(byTile);
}

async function build() {
  const dryRun = process.argv.includes("--dry-run");
  if (!await exists(planPath)) throw new Error(`No plan at ${planPath}; run with --plan first (the dev server must be running).`);
  const plannedExactly = JSON.parse(await readFile(planPath, "utf8"));
  const planned = { ...plannedExactly, imagery: withMargin(plannedExactly.imagery), terrain: withMargin(plannedExactly.terrain) };
  const imageryFile = (key) => join(imageryRoot, ...key.split("/")) + ".jpg";
  const imageryWork = [];
  for (const key of planned.imagery) if (!await exists(imageryFile(key))) imageryWork.push(key);
  const terrainManifest = JSON.parse(await readFile(terrainManifestPath, "utf8"));
  const terrainWork = [];
  for (const key of planned.terrain) {
    const file = `${key}.png`;
    if (terrainManifest.tiles[file] && await exists(join(terrainRoot, ...file.split("/")))) continue;
    terrainWork.push(file);
  }
  console.log(`Imagery: ${planned.imagery.length} planned, ${imageryWork.length} to download. Terrain: ${planned.terrain.length} planned, ${terrainWork.length} to download.`);
  if (dryRun) return;

  const imageryFailures = await inParallel(imageryWork, async (key) => {
    const [z, x, y] = key.split("/");
    const bytes = await download(`${imagerySource}/${z}/${y}/${x}.jpg`, isJpeg);
    await mkdir(dirname(imageryFile(key)), { recursive: true });
    await writeFile(imageryFile(key), bytes);
  }, "imagery");
  const present = [];
  for (const key of planned.imagery) if (await exists(imageryFile(key))) present.push(key);
  await writeFile(imageryManifestPath, `${JSON.stringify({
    source: `${imagerySource}/{z}/{y}/{x}.jpg`,
    credit: "Sentinel-2 cloudless - https://s2maps.eu by EOX IT Services GmbH (Contains modified Copernicus Sentinel data 2016 & 2017)",
    license: "CC BY 4.0",
    purpose: "Satellite imagery for every stop and flight of the monitoring tour, so the tour never downloads tiles while the camera moves.",
    recorded_viewport: planned.viewport,
    count: present.length,
    tiles: packIndex(present),
  })}\n`);

  const terrainFailures = await inParallel(terrainWork, async (file) => {
    const bytes = await download(`${terrainSource}/${file}`, isPng);
    const path = join(terrainRoot, ...file.split("/"));
    await mkdir(dirname(path), { recursive: true });
    await writeFile(path, bytes);
    terrainManifest.tiles[file] = { sha256: createHash("sha256").update(bytes).digest("hex"), bytes: bytes.length };
  }, "terrain");
  terrainManifest.monitoring_tour_coverage = {
    ...terrainManifest.monitoring_tour_coverage,
    source: terrainSource,
    tiles: planned.terrain.length,
    recorded_viewport: planned.viewport,
    note: "3D terrain-mesh tiles for every stop and every flight of the monitoring tour, planned by scripts/build-tour-tile-pack.mjs. Hillshade tiles are not included.",
  };
  const temporary = `${terrainManifestPath}.tmp`;
  await writeFile(temporary, `${JSON.stringify(terrainManifest, null, 2)}\n`);
  await rename(temporary, terrainManifestPath);

  console.log(`Imagery pack: ${present.length}/${planned.imagery.length} tiles. Terrain: ${terrainWork.length - terrainFailures.length} added.`);
  for (const failure of [...imageryFailures, ...terrainFailures].slice(0, 20)) console.warn(`  failed ${failure}`);
  if (imageryFailures.length || terrainFailures.length) process.exitCode = 1;
}

await (process.argv.includes("--plan") ? plan() : build());
