import assert from "node:assert/strict";
import { mkdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const browser = await chromium.launch({ executablePath: process.env.EDGE_PATH ?? "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
const errors = [], writes = [];
let page;
try {
  await mkdir(new URL("../screenshots/", import.meta.url), { recursive: true });
  page = await browser.newPage({ viewport: { width: 1600, height: 1050 } });
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => { if (!["GET", "OPTIONS"].includes(request.method())) writes.push(`${request.method()} ${request.url()}`); });
  await page.route("**/api/v1/**", (route) => {
    if (new URL(route.request().url()).pathname.endsWith("/simulation/monitoring/stations")) return route.fulfill({ json: [{ code: "TAUNSA", name: "Taunsa", river: "Indus", thresholds: [] }] });
    return route.fulfill({ status: 503, json: { error: { code: "PREVIEW_TEST", message: "Operational feeds excluded from visual preview check" } } });
  });
  await page.goto(process.env.FRONTEND_URL ?? "http://127.0.0.1:3000/", { waitUntil: "domcontentloaded" });
  await page.locator('.sidebar nav').getByRole("button", { name: "Simulation", exact: true }).click();
  await page.getByLabel("Station", { exact: true }).waitFor();
  const monitoring = page.getByRole("tab", { name: "Monitoring scenario", exact: true });
  const spread = page.getByRole("tab", { name: "Flood spread & population", exact: true });
  assert.equal(await monitoring.getAttribute("aria-selected"), "true");
  assert.equal(await page.locator('.simulation-flood-visualization canvas').count(), 0, "Maps do not mount in the monitoring form");
  await page.getByRole("button", { name: "Custom test thresholds", exact: true }).click();
  await page.getByRole("slider", { name: "Reading 1 value", exact: true }).evaluate((element) => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(element, "432000");
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await spread.click();
  const root = page.locator('.simulation-flood-visualization');
  const maps = root.locator('.outlook-map-canvas');
  const slider = page.getByRole("slider", { name: "Example flood level", exact: true });
  await root.locator('.outlook-map-canvas[data-ready="true"]').nth(1).waitFor({ timeout: 50000 });
  async function checkLevel(id, level) {
    const data = JSON.parse(await readFile(new URL(`../src/data/outlook-exposure/${id}.geojson`, import.meta.url), "utf8"));
    await page.waitForFunction(({ id, level, population }) => {
      const panel = document.querySelector('.simulation-flood-visualization');
      const impact = panel?.querySelector('.outlook-exposure-impact');
      const maps = [...panel?.querySelectorAll('.outlook-map-canvas') ?? []];
      return panel?.querySelector('.outlook-exposure')?.dataset.exposureArea === id && Number(impact?.dataset.estimatedPeople) === population && maps[1]?.dataset.floodLevel === String(level);
    }, { id, level, population: data.levels[level].exposed_population });
    assert.equal(await slider.inputValue(), String(level));
  }
  await checkLevel("jhang", 2);
  assert.equal(await maps.count(), 2, "Exactly two maps are used for the comparison");
  assert.equal(await root.locator('[data-map-example-index]').count(), 0, "The simulation does not display invented ten-year indices");
  assert.match(await root.locator('.simulation-spread-context').innerText(), /Taunsa.*district is selected separately/s);
  assert.match(await root.locator('.outlook-exposure-notice').innerText(), /not calibrated/);
  assert.equal(await maps.nth(0).getAttribute("data-water-visible"), "none");
  await page.getByRole("button", { name: /^Highest flood scenario/ }).click();
  await checkLevel("jhang", 5);
  await page.getByRole("button", { name: /^Lowest flood scenario/ }).click();
  await checkLevel("jhang", 0);
  assert.equal(await page.getByTestId("outlook-exposed-population").innerText(), "0");
  await page.getByRole("button", { name: "Play spread", exact: true }).click();
  await page.waitForFunction(() => Number(document.querySelector('#simulation-flood-level').value) >= 1);
  await page.getByRole("button", { name: "Pause spread", exact: true }).click();
  const paused = Number(await slider.inputValue());
  await page.waitForTimeout(1550);
  await checkLevel("jhang", paused);
  await page.getByRole("button", { name: "Play spread", exact: true }).click();
  await slider.focus();
  await slider.press("End");
  await checkLevel("jhang", 5);
  assert.equal(await page.getByRole("button", { name: "Play spread", exact: true }).getAttribute("aria-pressed"), "false", "Manual selection stops playback");
  await page.getByRole("button", { name: "Play spread", exact: true }).click();
  await checkLevel("jhang", 0);
  await page.waitForFunction(() => document.querySelector('#simulation-flood-level').value === "5", undefined, { timeout: 12000 });
  assert.equal(await page.getByRole("button", { name: "Play spread", exact: true }).getAttribute("aria-pressed"), "false", "Playback ends at the widest level");
  await page.getByRole("button", { name: "Reset spread to level zero", exact: true }).click();
  await checkLevel("jhang", 0);
  await page.getByRole("button", { name: /^Use flood level 3:/ }).click();
  await checkLevel("jhang", 3);
  await page.getByRole("button", { name: "Motion on", exact: true }).click();
  await page.waitForFunction(() => [...document.querySelectorAll('.simulation-flood-visualization .outlook-map-canvas')].every((map) => map.dataset.moving !== "true"));
  const oldZoom = Number(await maps.nth(0).getAttribute("data-zoom"));
  await page.getByRole("region", { name: "Baseline population map", exact: true }).getByRole("button", { name: "Zoom in", exact: true }).click();
  await page.waitForFunction((oldZoom) => {
    const maps = [...document.querySelectorAll('.simulation-flood-visualization .outlook-map-canvas')];
    return Number(maps[0]?.dataset.zoom) > oldZoom + .9 && maps[0]?.dataset.zoom === maps[1]?.dataset.zoom && maps[0]?.dataset.center === maps[1]?.dataset.center;
  }, oldZoom);
  await page.getByRole("button", { name: "Reset view", exact: true }).click();
  await page.waitForFunction(() => [...document.querySelectorAll('.simulation-flood-visualization .outlook-map-canvas')].every((map) => map.dataset.moving !== "true"));
  const data = JSON.parse(await readFile(new URL('../src/data/outlook-exposure/jhang.geojson', import.meta.url), "utf8"));
  const centers = data.population.features.filter((cell) => cell.properties.population_2025 > 0 && cell.geometry.type === "Polygon" && cell.geometry.coordinates[0].length === 5).map((cell) => {
    const ring = cell.geometry.coordinates[0].slice(0, 4);
    return [ring.reduce((sum, point) => sum + point[0], 0) / 4, ring.reduce((sum, point) => sum + point[1], 0) / 4];
  });
  await maps.nth(1).scrollIntoViewIfNeeded();
  const positions = await maps.nth(1).evaluate((container, centers) => {
    const [lng, lat] = container.dataset.center.split(",").map(Number);
    const world = 512 * 2 ** Number(container.dataset.zoom);
    const mercatorY = (value) => (1 - Math.log(Math.tan(Math.PI / 4 + value * Math.PI / 360)) / Math.PI) / 2;
    return centers.map(([x, y]) => ({ x: container.clientWidth / 2 + (x - lng) / 360 * world, y: container.clientHeight / 2 + (mercatorY(y) - mercatorY(lat)) * world }))
      .filter(({ x, y }) => x > 40 && x < container.clientWidth - 40 && y > 40 && y < container.clientHeight - 60)
      .sort((a, b) => Math.hypot(a.x - container.clientWidth / 2, a.y - container.clientHeight / 2) - Math.hypot(b.x - container.clientWidth / 2, b.y - container.clientHeight / 2)).slice(0, 10);
  }, centers);
  for (const position of positions) {
    await maps.nth(1).locator('canvas').click({ position });
    try { await page.locator('.outlook-population-popup').waitFor({ timeout: 500 }); break; } catch { /* Await source-worker rendering. */ }
  }
  assert.equal(await page.locator('.outlook-population-popup').count(), 1, "Population cells are inspectable in Simulation");
  await page.getByRole("button", { name: "Close popup", exact: true }).click();
  await root.locator('.ten-year-outlook-header').scrollIntoViewIfNeeded();
  await root.screenshot({ path: fileURLToPath(new URL('../screenshots/simulation-flood-visualization.png', import.meta.url)) });
  await page.getByRole("button", { name: "Population map", exact: true }).click();
  await page.waitForFunction(() => [...document.querySelectorAll('.simulation-flood-visualization .outlook-map-canvas')].every((map) => map.dataset.populationVisible === "none"));
  await page.getByRole("button", { name: "Population map", exact: true }).click();
  await page.getByRole("button", { name: "Flood spread", exact: true }).click();
  assert.equal(await page.getByRole("button", { name: "Play spread", exact: true }).isDisabled(), true);
  await page.getByRole("button", { name: "Flood spread", exact: true }).click();
  await checkLevel("jhang", 3);
  await page.getByLabel("Simulation preview district").selectOption("lahore");
  await checkLevel("lahore", 3);
  await page.getByLabel("Simulation preview district").selectOption("badin");
  await page.getByText("Badin: population available; water spread unavailable.", { exact: true }).waitFor();
  assert.equal(await slider.isDisabled(), true);
  assert.equal(await page.getByRole("button", { name: "Play spread", exact: true }).isDisabled(), true);
  assert.equal(await page.getByTestId("outlook-exposed-population").innerText(), "Unavailable");
  await page.getByLabel("Simulation preview district").selectOption("jhang");
  await checkLevel("jhang", 3);
  await page.emulateMedia({ reducedMotion: "reduce" });
  assert.equal(await page.getByRole("button", { name: "Play spread", exact: true }).isDisabled(), true);
  await slider.focus(); await slider.press("Home");
  await checkLevel("jhang", 0);
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.getByRole("button", { name: "Motion off", exact: true }).click();
  await page.getByRole("button", { name: "Play spread", exact: true }).click();
  await page.evaluate(() => { Object.defineProperty(document, "hidden", { configurable: true, value: true }); document.dispatchEvent(new Event("visibilitychange")); });
  await page.waitForFunction(() => document.querySelector('.simulation-flood-visualization').dataset.playing === "false");
  const hiddenLevel = await slider.inputValue();
  await page.waitForTimeout(1550);
  assert.equal(await slider.inputValue(), hiddenLevel, "A hidden browser document cannot keep advancing levels");
  await page.evaluate(() => { delete document.hidden; document.dispatchEvent(new Event("visibilitychange")); });
  await page.locator('.simulation-spread-method > summary').click();
  assert.match(await page.locator('.simulation-spread-method').innerText(), /no calibrated connection/i);
  await page.locator('.simulation-spread-method > summary').click();
  await page.setViewportSize({ width: 1024, height: 768 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await root.screenshot({ path: fileURLToPath(new URL('../screenshots/simulation-flood-visualization-compact.png', import.meta.url)) });
  await monitoring.click();
  assert.equal(await page.locator('.simulation-flood-visualization canvas').count(), 0, "Changing Simulation sub-tabs releases both map canvases");
  assert.equal(await page.getByRole("slider", { name: "Reading 1 value", exact: true }).inputValue(), "432000", "Draft monitoring values survive preview exploration");
  assert.equal(await page.getByLabel("Station", { exact: true }).inputValue(), "TAUNSA");
  await monitoring.focus(); await monitoring.press("ArrowRight");
  assert.equal(await spread.getAttribute("aria-selected"), "true", "Sub-tabs support keyboard navigation");
  await root.locator('.outlook-map-canvas[data-ready="true"]').nth(1).waitFor({ timeout: 50000 });
  await page.locator('.sidebar nav').getByRole("button", { name: "Alerts", exact: true }).click();
  assert.equal(await page.locator('.simulation-flood-visualization canvas').count(), 0, "Leaving Simulation releases maps and playback timers");
  assert.deepEqual(writes, [], "Preview controls do not submit monitoring runs or write operational data");
  assert.deepEqual(errors, [], "No browser runtime errors");
  console.log("PASS: Simulation sub-tabs, preserved draft form, synchronized zoomable maps, population cells, level slider/presets/chart/summary consistency, playback/pause/restart/end/manual takeover, missing-data and reduced-motion behavior, document-visibility cleanup, compact layout, zero backend writes and runtime errors.");
} catch (error) {
  if (page && !page.isClosed()) await page.screenshot({ path: fileURLToPath(new URL('../screenshots/simulation-flood-visualization-failure.png', import.meta.url)), fullPage: true }).catch(() => {});
  throw error;
} finally { await browser.close(); }
