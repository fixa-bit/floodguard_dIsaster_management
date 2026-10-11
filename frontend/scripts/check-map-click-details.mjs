import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { chromium } from "playwright";
import { mapTestUrl } from "./map-test-url.mjs";

const boundaries = JSON.parse(await readFile(new URL("../src/data/pakistan/pakistan_districts.geojson", import.meta.url), "utf8"));
const district = boundaries.features.find((feature) => feature.properties.district === "Islamabad");
assert.ok(district);
const risk = { type: "FeatureCollection", metadata: { feature_count: 1, returned_feature_count: 1,
  data_mode: "simulation", observed_at: new Date().toISOString(), cache_status: "fresh" }, features: [{ ...district,
  properties: { district_id: "test-islamabad", district_name: "Islamabad", longitude: 73.0479, latitude: 33.6844,
    risk_probability: 0.7, confidence: 0.8, severity: "HIGH", status: "watch", top_risk_factors: [] } }] };
const browser = await chromium.launch({ executablePath: process.env.EDGE_PATH ?? "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/v1/**", (route) => route.fulfill({ status: 503, json: { detail: "Unavailable test feed" } }));
  await page.route("**/api/v1/gis/national-risk", (route) => route.fulfill({ json: risk }));
  await page.goto(mapTestUrl(process.env.DASHBOARD_URL ?? "http://localhost:3000"), { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.querySelector(".national-map")?.dataset.districtSourceFeatures === "167", null, { timeout: 90000 });
  const locate = async () => {
    await page.getByRole("textbox", { name: "Target latitude", exact: true }).fill("33.6844");
    await page.getByRole("textbox", { name: "Target longitude", exact: true }).fill("73.0479");
    await page.getByRole("button", { name: "Locate coordinates", exact: true }).click();
    await page.waitForFunction(() => Number(document.querySelector(".national-map")?.dataset.coordinateZoom) >= 9.9, null, { timeout: 60000 });
    return page.getByRole("img", { name: "Located coordinate", exact: true }).boundingBox();
  };
  const panel = page.getByRole("complementary", { name: "District details", exact: true });
  const shading = page.getByRole("checkbox", { name: "District screening", exact: true });
  const names = page.getByRole("checkbox", { name: "District names & boundaries", exact: true });
  for (const enabled of [false, true, false]) {
    await shading.setChecked(enabled);
    await names.setChecked(enabled);
    const marker = await locate();
    await page.getByRole("button", { name: "Deselect location", exact: true }).click();
    await page.mouse.click(marker.x + marker.width / 2, marker.y + marker.height - 4);
    await panel.getByRole("heading", { name: "Islamabad", exact: true }).waitFor();
    await panel.getByText("70%", { exact: true }).waitFor();
    await panel.getByText("watch", { exact: true }).waitFor();
    if (!enabled) await page.screenshot({ path: "screenshots/map-click-details-restored.png" });
    await page.getByRole("button", { name: "Close district details", exact: true }).click();
  }
  await page.setViewportSize({ width: 390, height: 844 });
  const controls = page.getByRole("button", { name: "Toggle map layers", exact: true });
  if (await controls.getAttribute("aria-expanded") !== "true") await controls.click();
  const mobileMarker = await locate();
  await page.getByRole("button", { name: "Close coordinate details", exact: true }).click();
  assert.equal(await page.getByRole("img", { name: "Located coordinate", exact: true }).count(), 1);
  await page.mouse.click(mobileMarker.x + mobileMarker.width / 2, mobileMarker.y + mobileMarker.height - 4);
  await panel.getByRole("heading", { name: "Islamabad", exact: true }).waitFor();
  await panel.getByText("70%", { exact: true }).waitFor();
  assert.equal(await page.getByRole("img", { name: "Located coordinate", exact: true }).count(), 1);
  await page.screenshot({ path: "screenshots/map-click-details-restored-mobile.png" });
  assert.deepEqual(errors, []);
  console.log("PASS: original district screening details open after coordinate deselection on desktop/mobile, with shading and district labels both off or on; risk values are preserved.");
} finally { await browser.close(); }
