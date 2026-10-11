import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { chromium } from "playwright";
import { mapTestUrl } from "./map-test-url.mjs";
import { booleanPointInPolygon } from "@turf/boolean-point-in-polygon";
import { bbox } from "@turf/bbox";

const districts = JSON.parse(await readFile(new URL("../src/data/pakistan/pakistan_districts.geojson", import.meta.url), "utf8"));
const district = districts.features.find((feature) => feature.properties.district === "Islamabad");
const catchments = JSON.parse(await readFile(new URL("../src/data/pakistan/catchment_areas.geojson", import.meta.url), "utf8"));
const catchment = catchments.features.find((feature) => booleanPointInPolygon([73.0479, 33.6844], feature));
const outside = [[73.3, 33.9], [73.3, 33.48], [72.8, 33.9], [72.8, 33.48]].find((point) => !booleanPointInPolygon(point, catchment));
assert.ok(outside, "Fixture must include a nearby point in a different catchment");
const risk = { type: "FeatureCollection", metadata: { feature_count: 1, returned_feature_count: 1, data_mode: "simulation",
  observed_at: new Date().toISOString(), cache_status: "fresh" }, features: [{ ...district, properties: {
  district_id: "test-islamabad", district_name: "Islamabad", longitude: 73.0479, latitude: 33.6844,
  risk_probability: 0.7, severity: "HIGH", confidence: 0.8, status: "watch", top_risk_factors: [],
} }] };
const waterFeature = (id, data_class, geometry) => ({ type: "Feature", id, geometry, properties: {
  id, name: id, feature_kind: "river", water_system: "Test river", data_class, data_status: "test",
  telemetry_status: "unavailable", description: "Test fixture", monitoring_station_id: null,
} });
const water = { type: "FeatureCollection", metadata: { water_feature_count: 4, observed_station_count: 2, model_forecast_count: 1,
  feature_count: 7, returned_feature_count: 7, generated_at: new Date().toISOString(), data_mode: "simulation" }, features: [
  waterFeature("Nearby river", "gis_feature", { type: "LineString", coordinates: [[73, 33.6], [73.1, 33.75]] }),
  waterFeature("Nearby gauge", "observed_station", { type: "Point", coordinates: [73.05, 33.68] }),
  waterFeature("Nearby model", "model_forecast", { type: "Point", coordinates: [73.055, 33.69] }),
  waterFeature("Crossing river", "gis_feature", { type: "LineString", coordinates: [[73.0479, 33.6844], outside] }),
  waterFeature("Outside gauge", "observed_station", { type: "Point", coordinates: outside }),
  waterFeature("Outside barrage", "gis_feature", { type: "Point", coordinates: outside }),
  waterFeature("Inside barrage", "gis_feature", { type: "Point", coordinates: [73.05, 33.68] }),
] };
const [west, south, east, north] = bbox(catchment);
const rainfall = { type: "FeatureCollection", metadata: { source: "test", generated_at: new Date().toISOString(), cache_status: "fresh", missing_samples: 0, warning: null },
  features: [{ type: "Feature", properties: { accumulations_mm: { last_24h: 25 } }, geometry: { type: "Point", coordinates: [73.0479, 33.6844] } }],
  coverage: { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [[[west - 1, south - 1], [east + 1, south - 1], [east + 1, north + 1], [west - 1, north + 1], [west - 1, south - 1]]] } }] } };
const browser = await chromium.launch({ executablePath: process.env.EDGE_PATH ?? "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/v1/**", (route) => route.fulfill({ status: 503, json: { detail: "Unavailable test feed" } }));
  await page.route("**/api/v1/gis/national-risk", (route) => route.fulfill({ json: risk }));
  await page.route("**/api/v1/gis/water-intelligence", (route) => route.fulfill({ json: water }));
  await page.route("**/api/v1/gis/rainfall", (route) => route.fulfill({ json: rainfall }));
  await page.goto(mapTestUrl(process.env.DASHBOARD_URL ?? "http://localhost:3000"), { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.querySelector(".national-map")?.dataset.districtSourceFeatures === "167", null, { timeout: 90000 });
  const controls = page.locator(".map-layer-control");
  const panel = page.getByRole("complementary", { name: "Coordinate details", exact: true });
  const layer = (name) => page.getByRole("checkbox", { name, exact: true });
  const assertNormalStartup = async () => {
    assert.equal(await page.getByRole("button", { name: "Select coordinates on map", exact: true }).getAttribute("aria-pressed"), "false");
    assert.equal(await page.locator(".national-map.coordinate-picking").count(), 0);
    assert.notEqual(await page.locator(".national-map canvas").evaluate((element) => getComputedStyle(element).cursor), "crosshair");
    assert.equal(await page.getByRole("img", { name: "Located coordinate", exact: true }).count(), 0);
    assert.equal(await panel.count(), 0);
    assert.equal(await page.getByRole("textbox", { name: "Target latitude", exact: true }).inputValue(), "");
    assert.equal(await page.getByRole("textbox", { name: "Target longitude", exact: true }).inputValue(), "");
    assert.equal(await page.getByRole("checkbox", { name: "Enable corresponding layers", exact: true }).count(), 0);
    assert.equal(await layer("Pakistan boundary").isChecked(), true);
    const mapData = await page.locator(".national-map").evaluate((element) => ({ ...element.dataset }));
    assert.equal(mapData.locatedCoordinate, undefined);
    assert.equal(mapData.studyCatchment, "off");
  };
  await assertNormalStartup();
  const locate = async (latitude, longitude) => {
    await page.getByRole("textbox", { name: "Target latitude", exact: true }).fill(String(latitude));
    await page.getByRole("textbox", { name: "Target longitude", exact: true }).fill(String(longitude));
    await page.getByRole("button", { name: "Locate coordinates", exact: true }).click();
    await page.waitForFunction(({ latitude, longitude }) => {
      const data = document.querySelector(".national-map")?.dataset;
      const point = JSON.parse(data?.locatedCoordinate ?? "null");
      return point?.latitude === latitude && point?.longitude === longitude && Number(data.coordinateZoom) >= 9.9;
    }, { latitude, longitude }, { timeout: 60000 });
  };
  const added = ["District names & boundaries", "District screening", "Catchment areas", "River status & model forecasts", "River monitoring", "Rainfall heatmap"];
  await layer("Rivers, lakes & dams").check();
  await locate(33.6844, 73.0479);
  await panel.getByRole("checkbox", { name: "Enable corresponding layers", exact: true }).check();
  await page.waitForFunction(() => document.querySelector(".national-map")?.dataset.waterForecastVisibility === "visible");
  for (const name of added) assert.equal(await layer(name).isChecked(), true, name);
  const data = await page.locator(".national-map").evaluate((element) => ({ ...element.dataset }));
  assert.equal(data.studyCatchment, catchment.properties.basin_id);
  const counts = JSON.parse(data.studyCounts);
  assert.equal(counts["district-display"], 1, "Only corresponding district");
  assert.equal(counts["catchment-areas"], 1, "Only corresponding catchment");
  assert.equal(counts["observed-water-stations"], 1, "Outside gauge excluded");
  const scopedWater = JSON.parse(data.studyWater);
  assert.deepEqual(scopedWater.bodies.features.map((feature) => feature.id), ["Inside barrage"], "Outside barrage excluded");
  const crossing = scopedWater.lines.features.find((feature) => feature.id === "Crossing river");
  assert.ok(crossing);
  const paths = crossing.geometry.type === "LineString" ? [crossing.geometry.coordinates] : crossing.geometry.coordinates;
  for (const path of paths) {
    assert.notDeepEqual(path.at(-1), outside, "River must stop at catchment boundary");
    for (let index = 1; index < path.length; index++) assert.ok(booleanPointInPolygon([(path[index - 1][0] + path[index][0]) / 2, (path[index - 1][1] + path[index][1]) / 2], catchment));
  }
  await page.waitForFunction(() => Number(document.querySelector(".national-map")?.dataset.rainfallCells) > 0);
  const alpha = await page.locator(".national-map").evaluate(async (element, points) => {
    const img = new Image(); img.src = element.dataset.studyRainfallImage; await img.decode();
    const canvas = document.createElement("canvas"); canvas.width = img.width; canvas.height = img.height;
    const context = canvas.getContext("2d"); context.drawImage(img, 0, 0);
    const mercatorY = (latitude) => { const sin = Math.sin(latitude * Math.PI / 180); return 0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI); };
    return points.map(([longitude, latitude]) => {
      const x = Math.floor((longitude - 55.5) / 28 * canvas.width);
      const y = Math.floor((mercatorY(latitude) - mercatorY(39)) / (mercatorY(22) - mercatorY(39)) * canvas.height);
      return context.getImageData(x, y, 1, 1).data[3];
    });
  }, [[73.0479, 33.6844], [73.0479, north + 0.5]]);
  assert.ok(alpha[0] > 0, "Rainfall visible inside selected catchment");
  assert.equal(alpha[1], 0, "Rainfall transparent outside selected catchment");
  assert.equal(await layer("Glaciers & upstream drainage").isChecked(), false);
  assert.equal(await layer("Boundary alignment test").isChecked(), false);
  assert.equal(await layer("Google Flood Hub").isChecked(), false);
  await page.screenshot({ path: "screenshots/study-layers-desktop.png" });
  await page.getByRole("button", { name: "Close coordinate details", exact: true }).click();
  assert.equal(await controls.getByRole("checkbox", { name: "Enable corresponding layers", exact: true }).isChecked(), true);
  await controls.getByRole("checkbox", { name: "Enable corresponding layers", exact: true }).uncheck();
  for (const name of added) assert.equal(await layer(name).isChecked(), false, `${name}: restores previous selection`);
  assert.equal(await layer("Rivers, lakes & dams").isChecked(), true);
  assert.equal(await page.getByRole("img", { name: "Located coordinate", exact: true }).count(), 1);
  await controls.getByRole("checkbox", { name: "Enable corresponding layers", exact: true }).check();
  await locate(51.5074, -0.1278);
  await page.waitForFunction(() => document.querySelector(".national-map")?.dataset.districtBoundariesVisibility === "none");
  for (const name of added) assert.equal(await layer(name).isChecked(), false, `${name}: no unrelated coverage`);
  await locate(33.6844, 73.0479);
  await page.waitForFunction(() => document.querySelector(".national-map")?.dataset.waterForecastVisibility === "visible");
  await page.getByRole("button", { name: "Deselect location", exact: true }).click();
  for (const name of added) assert.equal(await layer(name).isChecked(), false, `${name}: deselection removes study layers`);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForFunction(() => document.querySelector(".map-layer-toggle")?.getAttribute("aria-expanded") === "false");
  await page.getByRole("button", { name: "Toggle map layers", exact: true }).click();
  await locate(33.6844, 73.0479);
  await panel.getByRole("checkbox", { name: "Enable corresponding layers", exact: true }).check();
  await page.screenshot({ path: "screenshots/study-layers-mobile.png" });
  await panel.getByRole("checkbox", { name: "Enable corresponding layers", exact: true }).uncheck();
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.querySelector(".national-map")?.dataset.districtSourceFeatures === "167", null, { timeout: 90000 });
  await page.getByRole("button", { name: "Toggle map layers", exact: true }).click();
  await assertNormalStartup();
  assert.deepEqual(errors, []);
  console.log("PASS: normal desktop/mobile startup and reload without selection or pin; one catchment/district, clipped rivers, scoped rainfall, excluded outside features, restored settings and pin retention.");
} finally { await browser.close(); }
