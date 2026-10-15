import assert from "node:assert/strict";
import { mkdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const browser = await chromium.launch({ executablePath: process.env.EDGE_PATH ?? "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
const errors = [], writes = [], assets = [];
try {
  await mkdir(new URL("../screenshots/", import.meta.url), { recursive: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1050 } });
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    if (!["GET", "OPTIONS"].includes(request.method())) writes.push(`${request.method()} ${request.url()}`);
    if (/\/(jhang|multan|lahore|rawalpindi|charsadda|sukkur|dadu|badin)-[a-f0-9]+\.geojson\.gz/.test(request.url())) assets.push(request.url());
  });
  await page.goto(process.env.DASHBOARD_URL ?? "http://localhost:3000", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "Predictive Risk Views", exact: true }).click();
  await page.getByRole("tab", { name: "10-Year Outlook", exact: true }).click({ timeout: 50000 });
  await page.locator('.outlook-map-canvas[data-ready="true"]').nth(1).waitFor({ timeout: 50000 });
  assert.equal(assets.length, 0, "Population grids are not fetched until a layer is enabled");
  await page.getByRole("button", { name: "Flood spread", exact: true }).click();
  await page.waitForFunction(() => document.querySelector('.outlook-exposure').dataset.exposureArea === "jhang");
  assert.equal(await page.getByLabel("Example area", { exact: true }).inputValue(), "jhang");
  await page.getByRole("button", { name: "Population map", exact: true }).click();
  await page.waitForFunction(() => [...document.querySelectorAll('.outlook-map-canvas')].every((map) => map.dataset.populationVisible === "visible"));
  assert.equal(await page.locator('.outlook-map-canvas').nth(0).getAttribute('data-water-visible'), "none");
  assert.equal(await page.locator('.outlook-map-canvas').nth(1).getAttribute('data-water-visible'), "visible");

  const slider = page.getByRole("slider", { name: "Example flood level", exact: true });
  async function checkLevel(id, level) {
    const data = JSON.parse(await readFile(new URL(`../src/data/outlook-exposure/${id}.geojson`, import.meta.url), "utf8"));
    await page.waitForFunction(({ id, level, expected }) => {
      const panel = document.querySelector('.outlook-exposure');
      const impact = document.querySelector('.outlook-exposure-impact');
      const maps = [...document.querySelectorAll('.outlook-map-canvas')];
      return panel?.dataset.exposureArea === id && panel?.dataset.exposureLevel === String(level)
        && Number(impact?.dataset.estimatedPeople) === expected && maps[1]?.dataset.floodLevel === String(level);
    }, { id, level, expected: data.levels[level].exposed_population });
    return data;
  }
  await slider.focus();
  await slider.press("Home");
  await checkLevel("jhang", 0);
  assert.equal(await page.getByTestId("outlook-exposed-population").innerText(), "0");
  await slider.press("End");
  await checkLevel("jhang", 5);
  await page.getByRole("button", { name: /^Use flood level 3:/ }).click();
  await checkLevel("jhang", 3);
  assert.equal(await slider.inputValue(), "3");
  const lowestPreset = page.getByRole("button", { name: /^Lowest flood scenario/ });
  const highestPreset = page.getByRole("button", { name: /^Highest flood scenario/ });
  await highestPreset.click();
  await checkLevel("jhang", 5);
  assert.equal(await highestPreset.getAttribute("aria-pressed"), "true");
  assert.equal(await lowestPreset.getAttribute("aria-pressed"), "false");
  await lowestPreset.click();
  await checkLevel("jhang", 0);
  assert.equal(await lowestPreset.getAttribute("aria-pressed"), "true");
  assert.equal(await page.getByLabel("Example scenario", { exact: true }).inputValue(), "moderate", "Spread presets do not change the separate outlook scenario");
  await page.getByRole("button", { name: /^Use flood level 3:/ }).click();
  // The water scenario must not silently turn into a 2036 population forecast.
  await page.getByLabel("Planning year", { exact: true }).selectOption("2026");
  for (const scenario of ["lowest", "highest", "higher"]) {
    await page.getByLabel("Example scenario", { exact: true }).selectOption(scenario);
    await checkLevel("jhang", 3);
  }
  await page.getByLabel("Flood type", { exact: true }).selectOption("urban");
  await checkLevel("jhang", 3);
  assert.match(await page.locator('.outlook-exposure-notice').innerText(), /fixed WorldPop 2025 baseline/);

  // A failed first district request clears old results and is recoverable.
  let rejectMultan = true;
  await page.route(/\/multan-[a-f0-9]+\.geojson\.gz/, (route) => rejectMultan ? route.abort() : route.continue());
  await page.getByLabel("Example area", { exact: true }).selectOption("multan");
  await page.getByRole("button", { name: "Retry layers", exact: true }).waitFor();
  assert.equal(await page.locator('.outlook-exposure-impact').count(), 0, "No stale Jhang exposure is displayed for Multan");
  rejectMultan = false;
  await page.getByRole("button", { name: "Retry layers", exact: true }).click();
  await checkLevel("multan", 3);
  await page.unroute(/\/multan-[a-f0-9]+\.geojson\.gz/);
  for (const id of ["lahore", "rawalpindi", "charsadda", "sukkur", "dadu", "jhang"]) {
    await page.getByLabel("Example area", { exact: true }).selectOption(id);
    await checkLevel(id, 3);
  }
  await page.getByLabel("Example area", { exact: true }).selectOption("badin");
  await page.getByText("Badin: population available; water spread unavailable.", { exact: true }).waitFor();
  assert.equal(await slider.isDisabled(), true);
  assert.equal(await lowestPreset.isDisabled(), true);
  assert.equal(await highestPreset.isDisabled(), true);
  assert.equal(await page.getByTestId("outlook-exposed-population").innerText(), "Unavailable");
  await page.waitForFunction(() => [...document.querySelectorAll('.outlook-map-canvas')].every((map) => map.dataset.waterVisible === "none" && map.dataset.populationVisible === "visible"));
  await page.getByLabel("Example area", { exact: true }).selectOption("all");
  await page.getByRole("button", { name: "Explore Jhang", exact: true }).waitFor();
  assert.equal(await page.locator('.outlook-exposure-impact').count(), 0);
  await page.getByRole("button", { name: "Explore Jhang", exact: true }).click();
  await checkLevel("jhang", 3);

  await page.getByRole("button", { name: "Motion on", exact: true }).click();
  await page.waitForFunction(() => [...document.querySelectorAll('.outlook-map-canvas')].every((map) => map.dataset.focus === "jhang" && map.dataset.moving !== "true"));
  // Click actual populated grid cells using the current camera, independent of
  // control height, viewport layout, or a fixed guess about where Jhang renders.
  const mapCanvas = page.locator('.outlook-map-canvas').nth(1);
  await mapCanvas.scrollIntoViewIfNeeded();
  const jhang = JSON.parse(await readFile(new URL('../src/data/outlook-exposure/jhang.geojson', import.meta.url), "utf8"));
  const centers = jhang.population.features.filter((cell) => cell.properties.population_2025 > 0 && cell.geometry.type === "Polygon" && cell.geometry.coordinates[0].length === 5).map((cell) => {
    const ring = cell.geometry.coordinates[0].slice(0, 4);
    return [ring.reduce((total, point) => total + point[0], 0) / 4, ring.reduce((total, point) => total + point[1], 0) / 4];
  });
  const positions = await mapCanvas.evaluate((container, centers) => {
    const [lng, lat] = container.dataset.center.split(",").map(Number);
    const world = 512 * 2 ** Number(container.dataset.zoom);
    const mercatorY = (latitude) => (1 - Math.log(Math.tan(Math.PI / 4 + latitude * Math.PI / 360)) / Math.PI) / 2;
    return centers.map(([x, y]) => ({ x: container.clientWidth / 2 + (x - lng) / 360 * world, y: container.clientHeight / 2 + (mercatorY(y) - mercatorY(lat)) * world }))
      .filter(({ x, y }) => x > 40 && x < container.clientWidth - 40 && y > 40 && y < container.clientHeight - 60)
      .sort((a, b) => Math.hypot(a.x - container.clientWidth / 2, a.y - container.clientHeight / 2) - Math.hypot(b.x - container.clientWidth / 2, b.y - container.clientHeight / 2)).slice(0, 10);
  }, centers);
  assert(positions.length, "The selected map camera includes known populated cells");
  for (const position of positions) {
    await mapCanvas.locator('canvas').click({ position });
    try {
      await page.locator('.outlook-population-popup').waitFor({ timeout: 500 });
      break;
    } catch { /* A source worker can still be finishing after a district change. */ }
  }
  assert.equal(await page.locator('.outlook-population-popup').count(), 1, "Map cells are inspectable");
  assert.match(await page.locator('.outlook-population-popup').innerText(), /WorldPop 2025/);
  await page.getByRole("button", { name: "Close popup", exact: true }).click();

  await page.locator('.ten-year-outlook-header').scrollIntoViewIfNeeded();
  await page.screenshot({ path: fileURLToPath(new URL("../screenshots/outlook-flood-population.png", import.meta.url)), fullPage: true });
  await page.getByRole("button", { name: "Population map", exact: true }).click();
  await page.getByRole("button", { name: "Flood spread", exact: true }).click();
  await page.waitForFunction(() => [...document.querySelectorAll('.outlook-map-canvas')].every((map) => map.dataset.waterVisible === "none" && map.dataset.populationVisible === "none"));
  assert.equal(await page.getByLabel("Hypothetical index legend", { exact: true }).isVisible(), true);
  await page.getByRole("button", { name: "Population map", exact: true }).click();
  await page.getByRole("button", { name: "Flood spread", exact: true }).click();
  await checkLevel("jhang", 3);
  await page.setViewportSize({ width: 1024, height: 768 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await page.screenshot({ path: fileURLToPath(new URL("../screenshots/outlook-flood-population-compact.png", import.meta.url)), fullPage: true });
  await page.getByRole("tab", { name: "Near-Term Screening", exact: true }).click();
  assert.equal(await page.locator('.outlook-map-canvas canvas').count(), 0, "Existing canvases are reused and released on leaving the outlook");
  assert.deepEqual(errors, [], "No browser runtime errors");
  assert.deepEqual(writes, [], "The experiment never writes operational data");
  console.log("PASS: lazy real-data layers, flood slider/zero/maximum/chart selection, synchronized map overlays, all eight districts, missing coverage, retry/stale-data handling, fixed population-year semantics, cell popups, compact layout, canvas cleanup, zero runtime errors or backend writes.");
} finally {
  await browser.close();
}
