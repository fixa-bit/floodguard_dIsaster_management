import assert from "node:assert/strict";
import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";
import { mapTestUrl } from "./map-test-url.mjs";

const browser = await chromium.launch({ executablePath: process.env.EDGE_PATH ?? "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
const downloads = [];
const responses = [];
page.on("pageerror", (error) => errors.push(error.message));
page.on("request", (request) => { if (request.resourceType() === "fetch" && request.url().endsWith(".geojson.gz")) downloads.push(request.url()); });
page.on("response", (response) => { if (response.url().endsWith(".geojson.gz")) responses.push(response); });
let release;
const hold = new Promise((resolve) => { release = resolve; });
let releaseFeeds;
const feedsHeld = new Promise((resolve) => { releaseFeeds = resolve; });
try {
  await page.route("**/api/v1/**", async (route) => { await feedsHeld; await route.continue(); });
  await page.route("**/*.geojson.gz", async (route) => { await hold; await route.continue(); });
  await page.goto(mapTestUrl(process.env.DASHBOARD_URL ?? "http://localhost:3000"), { waitUntil: "domcontentloaded" });
  await page.locator(".national-map").waitFor({ timeout: 120000 });
  console.log("Map mounted while dashboard feeds are held; checking boundary-only defaults.");
  for (const checkbox of await page.locator('[data-layer-category] input[type="checkbox"]').all()) {
    const label = await checkbox.evaluate((element) => element.closest("label").textContent.trim());
    assert.equal(await checkbox.isChecked(), label === "Pakistan boundary", label);
  }
  const spinner = page.getByRole("status", { name: "Loading map layers", exact: true });
  assert.equal(await spinner.count(), 0, "Hidden background downloads must not block the map");
  await page.waitForFunction(() => document.querySelector(".national-map")?.dataset.boundaryPainted === "true");
  await mkdir("screenshots", { recursive: true });
  await page.screenshot({ path: "screenshots/map-boundary-default.png" });
  releaseFeeds();
  await page.getByRole("checkbox", { name: "Glaciers & upstream drainage", exact: true }).check();
  await page.getByRole("checkbox", { name: "District names & boundaries", exact: true }).check();
  await page.getByText("Loading glacier inventory...", { exact: true }).waitFor({ timeout: 60000 });
  await page.getByText("Loading district boundaries...", { exact: true }).waitFor();
  await spinner.waitFor({ state: "visible" });
  assert.equal(await page.locator(".national-map").getAttribute("aria-busy"), "true");
  assert.equal(await spinner.locator("svg").evaluate((element) => getComputedStyle(element).animationName), "spin");
  await mkdir("screenshots", { recursive: true });
  await page.screenshot({ path: "screenshots/map-loading-desktop.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  await spinner.waitFor({ state: "visible" });
  const icon = await spinner.locator("svg").boundingBox();
  assert.ok(icon.x >= 0 && icon.x + icon.width <= 390);
  assert.ok(icon.y >= 0 && icon.y + icon.height <= 844);
  await page.screenshot({ path: "screenshots/map-loading-mobile.png" });
  assert.equal(await page.locator(".national-map canvas").count(), 1, "Base map must exist while static downloads are pending");
  release();
  const ready = () => page.waitForFunction(() => Number(document.querySelector(".national-map")?.dataset.glacierFeatures) > 1000, null, { timeout: 120000 });
  await ready();
  await spinner.waitFor({ state: "hidden" });
  assert.equal(await page.locator(".national-map").getAttribute("aria-busy"), "false");
  assert.equal(downloads.length, 3, "Cold start must fetch three compressed static assets");
  for (const response of responses) {
    assert.ok(response.ok());
    assert.equal(response.headers()["content-type"], "application/gzip");
    assert.match(response.headers()["cache-control"], /max-age=31536000.*immutable/);
    assert.ok(response.headers().etag);
  }
  await page.waitForFunction(async (urls) => {
    const cache = await caches.open("floodguard-static-maps-v1");
    return (await Promise.all(urls.map(async (url) => Boolean(await cache.match(url))))).every(Boolean);
  }, downloads);
  await page.reload({ waitUntil: "domcontentloaded" });
  await ready();
  assert.equal(await spinner.count(), 0);
  const beforeToggle = await page.locator(".national-map").getAttribute("data-source-updates");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("checkbox", { name: "Glaciers & upstream drainage", exact: true }).check();
  assert.equal(await spinner.count(), 0, "Warmed geometry must display without a loading wheel");
  await page.waitForFunction(() => Number(document.querySelector(".national-map")?.dataset.renderedGlaciers) > 0);
  assert.equal(await page.locator(".national-map").getAttribute("data-source-updates"), beforeToggle, "Visibility toggle must not reload sources");
  assert.equal(downloads.length, 3, "Full reload must not redownload cached geometry");
  assert.deepEqual(errors, []);
  console.log("PASS: map mounts before feeds; boundary-only defaults; hidden warm-up does not block; enabled pending layers show spinner; cached glacier toggles render without redownload or source updates.");
} catch (error) {
  console.log("Loading-check diagnostics:", downloads, errors, (await page.locator("body").innerText()).slice(0, 1600));
  await mkdir("screenshots", { recursive: true });
  await page.screenshot({ path: "screenshots/map-loading-failure.png" });
  throw error;
} finally { releaseFeeds(); release(); await browser.close(); }
