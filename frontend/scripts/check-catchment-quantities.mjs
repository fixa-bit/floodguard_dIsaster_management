import assert from "node:assert/strict";
import { mkdir, readFile } from "node:fs/promises";
import { booleanPointInPolygon } from "@turf/boolean-point-in-polygon";
import { chromium } from "playwright";
import { mapTestUrl } from "./map-test-url.mjs";

const url = process.env.DASHBOARD_URL ?? "http://127.0.0.1:3000/";
const basins = JSON.parse(await readFile(new URL("../src/data/pakistan/catchment_areas.geojson", import.meta.url), "utf8"));
assert.equal(basins.metadata.boundary_type, "hydrological_sub_basin");
assert.equal(basins.features.length, 54);
const browser = await chromium.launch({ executablePath: "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
try {
  await mkdir(new URL("../screenshots/", import.meta.url), { recursive: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let monitoring;
  await page.route("**/river/monitoring", async (route) => {
    const response = await route.fetch();
    monitoring = await response.json();
    monitoring.stations = monitoring.stations.map((station, index) => ({
      ...station,
      current_discharge_cumecs: index === 0 ? 1000 : index === 1 ? 2000 : index === 2 ? null : 0,
      forecast_discharge_cumecs: index === 0 ? 5000 : index === 1 ? 8000 : 0,
      expected_peak_cumecs: index === 0 ? 10000 : index === 1 ? 12000 : 0,
    }));
    await route.fulfill({ response, json: monitoring });
  });
  await page.goto(mapTestUrl(url), { waitUntil: "domcontentloaded" });
  await page.locator(".overview-command-canvas").waitFor({ timeout: 60000 });
  await page.locator(".sidebar nav").getByRole("button", { name: "GIS Operations" }).click();
  await page.waitForFunction(() => JSON.parse(document.querySelector(".national-map")?.dataset.monitoringStations ?? "[]").length >= 19, null, { timeout: 60000 });
  console.log("Monitoring stations loaded");
  const map = page.locator(".national-map");
  const markers = async () => JSON.parse(await map.getAttribute("data-monitoring-stations"));
  await page.getByLabel("Water quantity", { exact: true }).selectOption("current");
  await page.waitForFunction(() => JSON.parse(document.querySelector(".national-map").dataset.monitoringStations).some((station) => station.id === "TARBELA" && station.value === 1000));
  assert.ok((await markers()).some((station) => station.label.includes("Unavailable")), "Missing readings must remain unavailable");
  await page.getByLabel("Minimum discharge", { exact: true }).fill("1500");
  await page.waitForFunction(() => {
    const stations = JSON.parse(document.querySelector(".national-map").dataset.monitoringStations);
    return stations.length === 1 && stations[0].id === "KALABAGH";
  });
  await page.getByLabel("Water quantity units", { exact: true }).selectOption("cusecs");
  assert.ok(Math.abs(Number(await page.getByLabel("Minimum discharge").inputValue()) - 52972.00008225) < .001);
  await page.waitForFunction(() => JSON.parse(document.querySelector(".national-map").dataset.monitoringStations)[0]?.label.includes("70,629.3 cusecs"));
  await page.getByLabel("Minimum discharge").fill("0");
  await page.getByLabel("Water quantity", { exact: true }).selectOption("forecast");
  await page.waitForFunction(() => JSON.parse(document.querySelector(".national-map").dataset.monitoringStations).some((station) => station.id === "TARBELA" && station.value === 5000));
  await page.getByLabel("Water quantity", { exact: true }).selectOption("peak");
  await page.waitForFunction(() => JSON.parse(document.querySelector(".national-map").dataset.monitoringStations).some((station) => station.id === "TARBELA" && station.value === 10000));
  await page.getByLabel("Water quantity", { exact: true }).selectOption("current");
  console.log("Quantity and threshold controls passed");
  await page.locator(".operational-layer-options summary").click();
  await page.getByLabel("Catchment areas", { exact: true }).check();
  await page.waitForFunction(() => Number(document.querySelector(".national-map").dataset.renderedCatchments) > 0);
  const tarbela = monitoring.stations.find((station) => station.id === "TARBELA");
  const basin = basins.features.find((feature) => booleanPointInPolygon([tarbela.longitude, tarbela.latitude], feature));
  assert.ok(basin, "Tarbela must fall inside a sourced catchment");
  const expected = monitoring.stations.filter((station) => booleanPointInPolygon([station.longitude, station.latitude], basin));
  await page.getByLabel("Catchment area", { exact: true }).selectOption(basin.properties.basin_id);
  const inspector = page.getByRole("complementary", { name: "Catchment details" });
  await inspector.getByRole("heading", { name: basin.properties.name, exact: true }).waitFor();
  assert.equal(await inspector.locator(".catchment-station-reading").count(), expected.length);
  await page.waitForFunction((ids) => {
    const markers = JSON.parse(document.querySelector(".national-map").dataset.monitoringStations);
    return markers.length && markers.every((marker) => ids.includes(marker.id));
  }, expected.map((station) => station.id));
  const mapBounds = await map.boundingBox();
  const inspectorBounds = await inspector.boundingBox();
  assert.ok(inspectorBounds.x >= mapBounds.x + mapBounds.width - 1, "Catchment inspector must not cover the map");
  await page.screenshot({ path: "screenshots/catchment-quantities-desktop.png", fullPage: true });
  console.log("Catchment membership and desktop layout passed");
  await inspector.getByRole("button", { name: /Tarbela/ }).click();
  const stationInspector = page.getByRole("complementary", { name: "River station details" });
  await stationInspector.getByRole("heading", { name: "Tarbela", exact: true }).waitFor();
  assert.ok((await stationInspector.innerText()).includes("35,314.7 cusecs"));
  await stationInspector.getByRole("button", { name: "Close station details" }).click();
  await page.getByLabel("Catchment area", { exact: true }).selectOption(basin.properties.basin_id);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForFunction(() => {
    const map = document.querySelector(".national-map");
    const marker = JSON.parse(map.dataset.monitoringStations ?? "[]").find((station) => station.id === "TARBELA");
    return marker && marker.y > 60 && marker.y < map.clientHeight - 140;
  }, null, { timeout: 60000 });
  const mobileMap = await map.boundingBox();
  const mobileInspector = await inspector.boundingBox();
  assert.ok(mobileInspector.y >= mobileMap.y + mobileMap.height - 1, "Mobile catchment inspector must sit below map");
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Mobile page must not overflow");
  assert.equal(await page.getByRole("button", { name: "Toggle map layers" }).getAttribute("aria-expanded"), "false");
  await page.screenshot({ path: "screenshots/catchment-quantities-mobile.png", fullPage: true });
  await page.getByRole("button", { name: "Toggle map layers" }).click();
  await page.getByLabel("Catchment areas", { exact: true }).uncheck();
  assert.equal(await inspector.count(), 0);
  await page.waitForFunction(() => Number(document.querySelector(".national-map").dataset.renderedCatchments) === 0);
  await page.getByLabel("Water quantity", { exact: true }).selectOption("status");
  assert.ok(await page.getByLabel("Minimum discharge").isDisabled());
  assert.deepEqual(errors, []);
  console.log("Catchment boundaries, station membership, quantity switching, missing readings, unit conversion, threshold preservation, and desktop/mobile layouts passed");
} finally {
  await browser.close();
}
