import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { chromium } from "playwright";
import { mapTestUrl } from "./map-test-url.mjs";

const browser = await chromium.launch({ executablePath: process.env.EDGE_PATH ?? "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
const staticNames = ["Pakistan boundary", "Glaciers & upstream drainage", "Boundary alignment test", "District names & boundaries", "Catchment areas", "Rivers, lakes & dams", "Risk locations"];
const dynamicNames = ["District screening", "River status & model forecasts", "River monitoring", "Google Flood Hub", "Incidents", "Citizen reports", "Response resources", "Rainfall heatmap"];
try {
  await mkdir("screenshots", { recursive: true });
  await page.goto(mapTestUrl(process.env.DASHBOARD_URL ?? "http://localhost:3000"), { waitUntil: "domcontentloaded" });
  const staticGroup = page.locator('[data-layer-category="static"]');
  const dynamicGroup = page.locator('[data-layer-category="dynamic"]');
  await staticGroup.waitFor({ timeout: 60000 });
  for (const name of staticNames) assert.equal(await staticGroup.getByRole("checkbox", { name, exact: true }).count(), 1);
  for (const name of dynamicNames) assert.equal(await dynamicGroup.getByRole("checkbox", { name, exact: true }).count(), 1);
  assert.equal(await staticGroup.getByRole("checkbox").count(), staticNames.length);
  assert.equal(await dynamicGroup.getByRole("checkbox").count(), dynamicNames.length);
  assert.equal(await staticGroup.getByRole("combobox", { name: "Catchment area", exact: true }).count(), 1);
  assert.equal(await dynamicGroup.getByRole("combobox", { name: "Monitoring station", exact: true }).count(), 1);
  const geometry = staticGroup.getByRole("checkbox", { name: "Rivers, lakes & dams", exact: true });
  const forecasts = dynamicGroup.getByRole("checkbox", { name: "River status & model forecasts", exact: true });
  for (const name of [...staticNames, ...dynamicNames]) {
    assert.equal(await page.getByRole("checkbox", { name, exact: true }).isChecked(), name === "Pakistan boundary");
  }
  await geometry.check();
  await forecasts.check();
  await page.waitForFunction(() => document.querySelector(".national-map")?.dataset.waterGeometryVisibility === "visible");
  await geometry.uncheck();
  await page.waitForFunction(() => {
    const data = document.querySelector(".national-map").dataset;
    return data.waterGeometryVisibility === "none" && data.waterForecastVisibility === "visible";
  });
  await geometry.check();
  await forecasts.uncheck();
  await page.waitForFunction(() => {
    const data = document.querySelector(".national-map").dataset;
    return data.waterGeometryVisibility === "visible" && data.waterForecastVisibility === "none";
  });
  await forecasts.check();
  await staticGroup.locator("summary").click();
  assert.equal(await geometry.isVisible(), false);
  assert.equal(await forecasts.isVisible(), true);
  await staticGroup.locator("summary").click();
  await staticGroup.locator("summary").scrollIntoViewIfNeeded();
  await page.screenshot({ path: "screenshots/layer-categories-desktop.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  const panel = page.getByRole("button", { name: "Toggle map layers", exact: true });
  if (await panel.getAttribute("aria-expanded") !== "true") await panel.click();
  await dynamicGroup.locator("summary").scrollIntoViewIfNeeded();
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({ path: "screenshots/layer-categories-mobile.png" });
  assert.deepEqual(errors, []);
  console.log("PASS: every layer is in its static/dynamic category; water geometry and forecasts toggle independently; groups collapse independently; mobile layout fits.");
} finally { await browser.close(); }
