import assert from "node:assert/strict";
import { chromium } from "playwright";
import { mapTestUrl } from "./map-test-url.mjs";

const severities = ["EXTREME", "SEVERE", "ABOVE_NORMAL", "NO_FLOODING", "UNKNOWN"];
const labels = ["Extreme", "Danger", "Warning", "Normal", "No data"];
// Fixtures are used only by this browser check, never by the application.
const fixture = {
  type: "FeatureCollection",
  features: severities.map((severity, index) => ({
    type: "Feature", id: `fixture-${index}`,
    geometry: { type: "Point", coordinates: [66 + index * 2, 29 + index] },
    properties: {
      id: `fixture-${index}`, name: `Test gauge ${index}`, river: "Indus",
      severity, severity_label: labels[index], country_code: "PK",
      issued_at: "2026-10-10T10:00:00Z", forecast_start: "2026-10-10T10:00:00Z",
      forecast_end: "2026-10-17T10:00:00Z", trend: "RISE", source: "Test source",
      quality_verified: true, source_url: "https://sites.research.google/floods/",
    },
  })),
  metadata: { status: "live", message: null, fetched_at: "2026-10-10T10:00:00Z", source: "Google Flood Forecasting API", license: "CC BY 4.0" },
};

const browser = await chromium.launch({ executablePath: "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let response = fixture;
  await page.route("**/api/v1/gis/google-flood-hub", (route) => route.fulfill({ json: response }));
  await page.goto(mapTestUrl(process.env.FRONTEND_URL ?? "http://127.0.0.1:3001/"), { waitUntil: "domcontentloaded" });
  await page.locator(".overview-command-canvas").waitFor({ timeout: 60000 });
  await page.locator(".sidebar nav").getByRole("button", { name: "GIS Operations" }).click();
  const map = page.locator(".national-map");
  await page.getByLabel("Google Flood Hub", { exact: true }).check();
  await page.waitForFunction(() => JSON.parse(document.querySelector(".national-map")?.dataset.floodHubMarkers ?? "[]").length >= 5, null, { timeout: 60000 });
  const markers = JSON.parse(await map.getAttribute("data-flood-hub-markers"));
  assert.equal(new Set(markers.map((item) => item.id)).size, 5);
  for (const label of labels) assert.ok(await page.getByText(`Google: ${label}`, { exact: true }).isVisible());
  const marker = markers.find((item) => item.id === "fixture-2");
  await map.click({ position: { x: marker.x, y: marker.y } });
  await page.locator(".floodhub-inspector h3").getByText("Test gauge 2", { exact: true }).waitFor();
  assert.ok((await page.locator(".floodhub-inspector").innerText()).includes("Warning"));
  await page.getByRole("button", { name: "Close Flood Hub details" }).click();
  await page.getByLabel("Show normal conditions").uncheck();
  await page.waitForFunction(() => !JSON.parse(document.querySelector(".national-map")?.dataset.floodHubMarkers ?? "[]").some((item) => item.severity === "NO_FLOODING"));
  await page.screenshot({ path: "google-flood-desktop.png", fullPage: true });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Toggle map layers" }).click();
  await page.getByLabel("Show normal conditions").check();
  await page.screenshot({ path: "google-flood-mobile.png", fullPage: true });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  await page.getByLabel("Google Flood Hub", { exact: true }).uncheck();
  response = { ...fixture, features: [], metadata: { ...fixture.metadata, status: "not_configured", fetched_at: null, message: "Google Flood Hub is not connected. API access is required." } };
  await page.getByLabel("Google Flood Hub", { exact: true }).check();
  await page.getByText("Google Flood Hub is not connected. API access is required.", { exact: true }).waitFor();
  await page.waitForFunction(() => JSON.parse(document.querySelector(".national-map")?.dataset.floodHubMarkers ?? "[]").length === 0);
  assert.deepEqual(errors, []);
  console.log("Passed: five severity markers, actual marker click, normal filter, desktop/mobile layout, and missing-access state (fixture data).");
} finally {
  await browser.close();
}
