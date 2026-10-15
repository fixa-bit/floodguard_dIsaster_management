import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { previewAreas, previewPoint } from "../src/components/tenYearPreviewData.ts";

const appUrl = process.env.DASHBOARD_URL ?? "http://localhost:3000";
const browser = await chromium.launch({ executablePath: process.env.EDGE_PATH ?? "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
const errors = [];
const writes = [];

try {
  await mkdir(new URL("../screenshots/", import.meta.url), { recursive: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1050 } });
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => { if (request.method() !== "GET" && request.method() !== "OPTIONS") writes.push(`${request.method()} ${request.url()}`); });
  await page.goto(appUrl, { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "Predictive Risk Views", exact: true }).click();
  const near = page.getByRole("tab", { name: "Near-Term Screening", exact: true });
  const outlook = page.getByRole("tab", { name: "10-Year Outlook", exact: true });
  await near.waitFor({ timeout: 50000 });
  assert.equal(await page.locator("#risk-panel-near-term .multiview-card:visible").count(), 5);
  assert.equal(await page.locator(".outlook-map-canvas canvas").count(), 0, "Maps do not mount in the inactive tab");
  await outlook.click();
  await page.locator('.outlook-map-canvas[data-ready="true"]').nth(1).waitFor({ timeout: 50000 });
  assert.equal(await page.locator(".ten-year-outlook").getAttribute("data-is-hypothetical"), "true");
  assert.equal(await page.getByText("Hypothetical preview", { exact: true }).isVisible(), true);

  async function consistent(selection, hazard, scenario, year) {
    const expected = previewPoint(selection, hazard, scenario, year);
    await page.waitForFunction(({ year, value }) => {
      const chart = document.querySelector(".outlook-chart-panel");
      return chart?.dataset.selectedYear === String(year) && chart?.dataset.selectedValue === String(value);
    }, { year, value: expected.value });
    assert.equal(parseFloat(await page.getByTestId("outlook-future").innerText()), expected.value);
    assert.equal(parseFloat(await page.getByTestId("outlook-baseline").innerText()), expected.baseline);
    assert.equal(parseFloat(await page.getByTestId("outlook-change").innerText()), Number((expected.value - expected.baseline).toFixed(1)));
    assert.equal(Number(await page.locator("[data-map-example-index]").nth(1).getAttribute("data-map-example-index")), expected.value);
  }
  await consistent("all", "riverine", "moderate", 2036);
  await page.getByLabel("Example area", { exact: true }).selectOption("jhang");
  await page.getByLabel("Planning year", { exact: true }).selectOption("2030");
  await consistent("jhang", "riverine", "moderate", 2030);
  for (const scenario of ["lowest", "highest"]) {
    await page.getByLabel("Example scenario", { exact: true }).selectOption(scenario);
    await consistent("jhang", "riverine", scenario, 2030);
    assert.match(await page.locator("#outlook-scenario-description").innerText(), /hypothetical|not a physical upper bound/i);
  }
  await page.getByLabel("Example scenario", { exact: true }).selectOption("higher");
  await consistent("jhang", "riverine", "higher", 2030);
  await page.getByLabel("Flood type", { exact: true }).selectOption("urban");
  await consistent("jhang", "urban", "higher", 2030);
  await page.getByLabel("Example scenario", { exact: true }).selectOption("stable");
  await consistent("jhang", "urban", "stable", 2030);
  assert.equal(parseFloat(await page.getByTestId("outlook-change").innerText()), 0);

  await page.getByLabel("Example scenario", { exact: true }).selectOption("moderate");
  const currentPane = page.getByRole("region", { name: "Current example map", exact: true });
  await page.waitForFunction(() => [...document.querySelectorAll('.outlook-map-canvas')].every((map) => map.dataset.moving !== "true"));
  const oldZoom = Number(await currentPane.locator(".outlook-map-canvas").getAttribute("data-zoom"));
  await currentPane.getByRole("button", { name: "Zoom in", exact: true }).click();
  await page.waitForFunction((old) => {
    const maps = [...document.querySelectorAll(".outlook-map-canvas")];
    return maps.length === 2 && Number(maps[0].dataset.zoom) > old + 0.9 && maps[0].dataset.zoom === maps[1].dataset.zoom && maps[0].dataset.center === maps[1].dataset.center;
  }, oldZoom);
  await page.getByRole("button", { name: "Reset view", exact: true }).click();
  await page.getByLabel("Example area", { exact: true }).selectOption("all");
  await page.waitForFunction(() => [...document.querySelectorAll('.outlook-map-canvas')].every((map) => map.dataset.focus === "all" && map.dataset.moving !== "true"));

  // Click an actual rendered location pin, using the map's current Mercator camera.
  const dadu = previewAreas.find((area) => area.id === "dadu");
  const position = await currentPane.locator(".outlook-map-canvas").evaluate((container, coordinates) => {
    const [lng, lat] = container.dataset.center.split(",").map(Number);
    const world = 512 * 2 ** Number(container.dataset.zoom);
    const mercatorY = (latitude) => (1 - Math.log(Math.tan(Math.PI / 4 + latitude * Math.PI / 360)) / Math.PI) / 2;
    return { x: container.clientWidth / 2 + (coordinates[0] - lng) / 360 * world,
      y: container.clientHeight / 2 + (mercatorY(coordinates[1]) - mercatorY(lat)) * world };
  }, dadu.coordinates);
  await currentPane.locator(".maplibregl-canvas").click({ position });
  await page.waitForFunction(() => document.querySelector('.outlook-controls select').value === "dadu");
  await consistent("dadu", "urban", "moderate", 2030);
  await page.getByRole("button", { name: "Inputs & Method", exact: true }).click();
  assert.equal(await page.locator("#outlook-inputs-method").getAttribute("open"), "");
  for (const title of ["Datasets and fields used in this preview", "Engineered features", "Model or method used now", "Outputs shown", "Limitations", "Future scope"]) {
    assert.equal(await page.getByRole("heading", { name: title, exact: true }).isVisible(), true);
  }
  assert.match(await page.locator(".outlook-method-notice").innerText(), /No trained prediction model/);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await page.locator("#outlook-inputs-method > summary").click();
  await page.getByText("View example values", { exact: true }).click();
  assert.equal(await page.locator(".outlook-values tbody tr").count(), 11);
  await page.getByText("View example values", { exact: true }).click();
  await page.getByLabel("Example area", { exact: true }).selectOption("all");
  await page.getByLabel("Flood type", { exact: true }).selectOption("riverine");
  await page.getByLabel("Planning year", { exact: true }).selectOption("2036");
  await consistent("all", "riverine", "moderate", 2036);
  await page.screenshot({ path: fileURLToPath(new URL("../screenshots/ten-year-hypothetical-desktop.png", import.meta.url)), fullPage: true });
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.waitForFunction(() => [...document.querySelectorAll('.outlook-map-canvas')].every((map) => Number(map.dataset.zoom) < 3.7));
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await page.screenshot({ path: fileURLToPath(new URL("../screenshots/ten-year-hypothetical-compact.png", import.meta.url)), fullPage: true });
  await near.click();
  assert.equal(await page.locator(".outlook-map-canvas canvas").count(), 0, "Inactive comparison maps release WebGL canvases");
  await page.getByRole("button", { name: "Inputs & model", exact: true }).click();
  await page.getByRole("dialog").waitFor();
  await page.getByRole("button", { name: "Close inputs and model", exact: true }).click();
  await outlook.click();
  await page.locator('.outlook-map-canvas[data-ready="true"]').nth(1).waitFor({ timeout: 50000 });
  await consistent("all", "riverine", "moderate", 2036);
  assert.deepEqual(writes, [], "The preview cannot write observations, alerts, incidents, or other backend data");
  assert.deepEqual(errors, [], "No browser runtime errors");
  console.log("PASS: existing sub-tab; area/hazard/scenario/year consistency; synchronized map zoom and pin selection; methodology and values; desktop/compact layout; inactive-map cleanup; preserved near-term dialog; zero backend writes or runtime errors.");
} finally {
  await browser.close();
}
