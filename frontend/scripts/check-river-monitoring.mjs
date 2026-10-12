import assert from "node:assert/strict";
import { chromium } from "playwright";
import { mapTestUrl } from "./map-test-url.mjs";

const browser = await chromium.launch({ executablePath: "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  await page.goto(mapTestUrl(process.env.FRONTEND_URL ?? "http://127.0.0.1:3000/"), { waitUntil: "domcontentloaded" });
  await page.locator(".overview-command-canvas").waitFor({ timeout: 60000 });
  await page.locator(".sidebar nav").getByRole("button", { name: "GIS Operations" }).click();
  const mapLayers = page.getByRole("button", { name: "Toggle map layers", exact: true });
  if (await mapLayers.getAttribute("aria-expanded") === "false") await mapLayers.click();
  const monitoringToggle = page.getByLabel("River monitoring", { exact: true });
  if (!(await monitoringToggle.isChecked())) await monitoringToggle.check();
  const map = page.locator(".national-map");
  await page.getByText("22 matching stations", { exact: true }).waitFor({ timeout: 60000 });
  await page.waitForFunction(() => JSON.parse(document.querySelector(".national-map")?.dataset.monitoringStations ?? "[]").length > 0, null, { timeout: 60000 });
  await page.waitForTimeout(1000);
  const markers = JSON.parse(await map.getAttribute("data-monitoring-stations"));
  assert.ok(markers.length > 0, "No visible monitoring marker rendered");
  await page.getByLabel("Monitoring station", { exact: true }).selectOption("MARALA");
  const inspector = page.getByRole("complementary", { name: "River station details" });
  await page.waitForTimeout(500);
  console.log("Visible marker sample:", markers[0], "Marala marker:", JSON.parse(await map.getAttribute("data-monitoring-stations")).find((item) => item.id === "MARALA"), "Inspector:", await inspector.locator("h3").allTextContents());
  await page.screenshot({ path: "river-marker-click.png", fullPage: true });
  await inspector.getByRole("heading", { name: "Marala", exact: true }).waitFor();
  for (const label of ["Current discharge", "Forecast discharge", "24h change", "Expected peak time", "Hydrograph", "Rainfall context", "Upstream stations"]) assert.ok((await inspector.innerText()).includes(label));
  if (!(await inspector.locator(".river-rain-strip div").count())) {
    await inspector.getByRole("button", { name: "Refresh", exact: true }).click();
    await page.waitForFunction(() => document.querySelector(".river-rain-strip div"), null, { timeout: 60000 });
  }
  const plot = inspector.locator(".source-forecast-chart");
  assert.ok(await plot.locator("path").count());
  const mapBounds = await map.boundingBox();
  const panelBounds = await inspector.boundingBox();
  assert.ok(panelBounds.x >= mapBounds.x + mapBounds.width - 1, "Inspector covers map");
  await page.screenshot({ path: "river-monitoring-desktop.png", fullPage: true });
  await page.getByLabel("Monitoring station", { exact: true }).selectOption("PANJNAD");
  await inspector.getByRole("heading", { name: "Panjnad", exact: true }).waitFor();
  assert.equal(await inspector.locator(".river-station-chain").count(), 2);
  await inspector.locator(".river-upstream-stations").getByRole("button", { name: "Trimmu", exact: true }).click();
  await inspector.getByRole("heading", { name: "Trimmu", exact: true }).waitFor();
  await page.getByLabel("Monitoring river", { exact: true }).selectOption("Ravi");
  await page.getByText("4 matching stations", { exact: true }).waitFor({ timeout: 60000 });
  await page.getByLabel("Monitoring station", { exact: true }).selectOption("JASSAR");
  await inspector.getByRole("heading", { name: "Jassar", exact: true }).waitFor();
  await page.getByLabel("River monitoring", { exact: true }).uncheck();
  await page.waitForFunction(() => JSON.parse(document.querySelector(".national-map")?.dataset.monitoringStations ?? "[]").length === 0);
  await page.getByLabel("River monitoring", { exact: true }).check();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(300);
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  const mobileMap = await map.boundingBox();
  const mobilePanel = await inspector.boundingBox();
  assert.ok(mobilePanel.y >= mobileMap.y + mobileMap.height - 1, "Mobile inspector covers map");
  await page.screenshot({ path: "river-monitoring-mobile.png", fullPage: true });
  await inspector.getByRole("button", { name: "Close station details" }).click();
  assert.equal(await inspector.count(), 0);
  console.log("22 station source, visible marker rendering, station rainfall details, shared Panjnad, upstream links, river filter, layer toggle, and desktop/mobile layout passed");
} finally {
  await browser.close();
}
