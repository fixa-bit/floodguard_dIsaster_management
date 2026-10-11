import assert from "node:assert/strict";
import { mkdir, readFile } from "node:fs/promises";
import { chromium } from "playwright";
import { mapTestUrl } from "./map-test-url.mjs";
import { booleanPointInPolygon } from "@turf/boolean-point-in-polygon";

const browser = await chromium.launch({
  executablePath: process.env.EDGE_PATH ?? "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  headless: true,
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
const districtBoundaries = JSON.parse(await readFile(new URL("../src/data/pakistan/pakistan_districts.geojson", import.meta.url), "utf8"));
page.on("pageerror", (error) => errors.push(error.message));
const diagnostics = () => page.locator(".national-map").evaluate((element) => ({ ...element.dataset }));
const waitVisible = () => page.waitForFunction(() => {
  const data = document.querySelector(".national-map")?.dataset;
  return data?.districtBoundarySource === "district-display"
    && data.districtBoundariesVisibility === "visible"
    && Number(data.districtSourceFeatures) > 0
    && JSON.parse(data.districtNames ?? "[]").length > 0;
}, null, { timeout: 60000 });

try {
  await mkdir("screenshots", { recursive: true });
  await page.route("**/api/v1/gis/national-risk", (route) => route.fulfill({ json: {
    type: "FeatureCollection", metadata: { coverage: "test districts", feature_count: 145, returned_feature_count: 145,
      data_mode: "simulation", scenario: "NORMAL", observed_at: new Date().toISOString(), cache_status: "fresh", boundary_source: "Original screening polygons" },
    features: districtBoundaries.features.filter((feature) => feature.properties.district).map((feature) => {
      const districtName = feature.properties.district;
      const testCoordinates = districtName === "Killa Saifullah" ? [68.4059375, 31.0502105]
        : districtName === "Zhob" ? [68.7797700, 31.2232138] : [73.1, 32.1];
      if (["Killa Saifullah", "Zhob"].includes(districtName)) {
        assert.equal(booleanPointInPolygon(testCoordinates, feature), true, `${districtName}: click test point must be inside the canonical polygon`);
      }
      return { ...feature, id: feature.properties.id, properties: {
      district_id: feature.properties.id, district_name: districtName, longitude: testCoordinates[0], latitude: testCoordinates[1],
      risk_probability: 0.7, confidence: 0.8, severity: "HIGH", status: "watch", top_risk_factors: [],
    } };
    }),
  } }));
  await page.goto(mapTestUrl(process.env.DASHBOARD_URL ?? "http://localhost:3000"), { waitUntil: "domcontentloaded" });
  const toggle = page.getByRole("checkbox", { name: "District names & boundaries", exact: true });
  await toggle.waitFor({ timeout: 60000 });
  assert.equal(await toggle.isChecked(), false);
  await toggle.check();
  await page.getByRole("checkbox", { name: "District screening", exact: true }).check();
  await waitVisible();
  await page.waitForFunction(() => JSON.parse(document.querySelector(".national-map")?.dataset.districtClickTargets ?? "[]").some((feature) => feature.name === "Killa Saifullah"), null, { timeout: 60000 });
  assert.equal((await diagnostics()).districtBoundarySource, "district-display", "District outlines must use static display geometry independent of risk coverage");
  assert.equal((await diagnostics()).admin1BoundaryVisibility, "visible", "National outline must remain visible with districts");
  assert.equal((await diagnostics()).screeningOutlineVisibility, "none", "Conflicting white strokes should not duplicate purple borders");
  assert.equal((await diagnostics()).unnamedDistricts, "0", "Unnamed territory context must not become a district border");
  console.log("Initial district names:", JSON.parse((await diagnostics()).districtNames));
  const mapBounds = await page.locator(".national-map").boundingBox();
  const saifullahTarget = JSON.parse((await diagnostics()).districtClickTargets).find((feature) => feature.name === "Killa Saifullah");
  await page.mouse.move(mapBounds.x + saifullahTarget.x, mapBounds.y + saifullahTarget.y);
  for (let step = 0; step < 4; step++) {
    await page.mouse.wheel(0, -500);
    await page.waitForTimeout(350);
  }
  await page.waitForFunction((previous) => {
    const target = JSON.parse(document.querySelector(".national-map")?.dataset.districtClickTargets ?? "[]").find((feature) => feature.name === "Killa Saifullah");
    return target && (target.x !== previous.x || target.y !== previous.y);
  }, saifullahTarget, { timeout: 60000 });
  await page.waitForFunction(() => {
    const names = JSON.parse(document.querySelector(".national-map")?.dataset.renderedDistrictNames ?? "[]");
    return names.includes("Killa Saifullah") && names.includes("Zhob");
  }, null, { timeout: 60000 });
  for (const districtName of ["Killa Saifullah", "Zhob"]) {
    const target = JSON.parse((await diagnostics()).districtClickTargets).find((feature) => feature.name === districtName);
    await page.mouse.click(mapBounds.x + target.x, mapBounds.y + target.y);
    assert.equal(await page.locator(".district-inspector h3").textContent(), districtName, `${districtName}: map click must open matching district data`);
    await page.getByRole("button", { name: "Close district details" }).click();
  }
  // Purple district geography remains independent of risk shading and rainfall.
  await page.getByRole("checkbox", { name: "District screening", exact: true }).uncheck();
  await page.getByRole("button", { name: "Next 72 hours", exact: true }).click();
  await waitVisible();
  await page.mouse.move(mapBounds.x + mapBounds.width * 0.7, mapBounds.y + mapBounds.height * 0.6);
  await page.mouse.wheel(0, -400);
  await page.waitForTimeout(500);
  await waitVisible();
  await toggle.uncheck();
  assert.equal((await diagnostics()).screeningOutlineVisibility, "none", "Disabled screening must remain disabled");
  await page.waitForFunction(() => {
    const data = document.querySelector(".national-map")?.dataset;
    return data?.districtBoundariesVisibility === "none";
  }, null, { timeout: 60000 });
  await toggle.check();
  await waitVisible();
  assert.equal((await diagnostics()).unnamedDistricts, "0");
  assert.equal((await diagnostics()).admin1BoundaryVisibility, "visible");
  await page.getByRole("checkbox", { name: "District screening", exact: true }).check();
  await toggle.uncheck();
  assert.equal((await diagnostics()).screeningOutlineVisibility, "visible", "White outline returns when purple overlay is off");
  await toggle.check();
  assert.equal((await diagnostics()).screeningOutlineVisibility, "none");
  await page.screenshot({ path: "screenshots/district-layer-desktop.png" });
  const suk = JSON.parse((await diagnostics()).monitoringStations ?? "[]").find((station) => station.id === "SUKKUR");
  if (suk) {
    await page.getByRole("checkbox", { name: "Rainfall heatmap", exact: true }).uncheck();
    const bounds = await page.locator(".national-map").boundingBox();
    await page.mouse.move(bounds.x + suk.x, bounds.y + suk.y);
    await page.mouse.wheel(0, -1000);
    await page.waitForTimeout(1200);
    for (let step = 0; step < 3; step++) {
      const station = JSON.parse((await diagnostics()).monitoringStations ?? "[]").find((item) => item.id === "SUKKUR");
      if (station) await page.mouse.move(bounds.x + station.x, bounds.y + station.y);
      await page.mouse.wheel(0, -600);
      await page.waitForTimeout(800);
    }
    await waitVisible();
    await page.screenshot({ path: "screenshots/district-alignment-sukkur.png" });
    await page.getByRole("button", { name: "Next 72 hours", exact: true }).click();
  }

  await page.setViewportSize({ width: 390, height: 844 });
  const layers = page.getByRole("button", { name: "Toggle map layers", exact: true });
  await page.waitForTimeout(250);
  if (await layers.getAttribute("aria-expanded") === "false") await layers.click();
  await toggle.scrollIntoViewIfNeeded();
  await toggle.uncheck();
  await toggle.check();
  await waitVisible();
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await layers.click();
  const mobileMap = await page.locator(".national-map").boundingBox();
  await page.mouse.move(mobileMap.x + mobileMap.width * 0.55, mobileMap.y + mobileMap.height * 0.6);
  await page.mouse.wheel(0, -400);
  await page.waitForTimeout(1000);
  await waitVisible();
  await page.screenshot({ path: "screenshots/district-layer-mobile.png" });
  assert.deepEqual(errors, []);
  console.log("PASS: district names and boundaries toggle together, remain independent of rainfall and risk shading, preserve district clicks, and work on mobile.");
} catch (error) {
  console.log("District diagnostics:", await diagnostics(), errors);
  await page.screenshot({ path: "screenshots/district-layer-failure.png" });
  throw error;
} finally {
  await browser.close();
}
