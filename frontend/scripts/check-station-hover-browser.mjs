import assert from "node:assert/strict";
import { chromium } from "playwright";
import { monitoringSites } from "../src/components/monitoringSites.ts";
import { mapTestUrl } from "./map-test-url.mjs";

const browser = await chromium.launch({ executablePath: process.env.EDGE_PATH ?? "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
const now = new Date();
const stations = monitoringSites.features.filter((feature) => feature.properties.stationId).map((feature) => ({
  id: feature.id, name: feature.properties.name, river: feature.properties.river, basin: feature.properties.river,
  longitude: feature.geometry.coordinates[0], latitude: feature.geometry.coordinates[1],
  current_discharge_cumecs: 130, current_source: "FFD observed", observed_at: now.toISOString(),
  change_24h_cumecs: 30, change_source: "FFD observed 24h change", flood_category: "Below low",
  providers: [], facts: [], rainfall: [], flood_types: [], stats: {}, upstream_station_ids: [],
}));
const feed = { stations, chains: {}, refresh_interval_minutes: 60, generated_at: now.toISOString(), refreshing: false };
stations.find((station) => station.id === "TARBELA").observed_at = new Date(now.getTime() - 2 * 3600000).toISOString();
const water = { type: "FeatureCollection", metadata: {}, features: Array.from({ length: 450 }, (_, i) => ({
  type: "Feature", id: `synthetic-${i}`, geometry: { type: "Point", coordinates: [70.88 + (i % 30) * 0.006, 30.55 + Math.floor(i / 30) * 0.006] },
  properties: { name: `Synthetic gauge ${i}`, data_class: "observed_station", feature_kind: "gauge", water_system: "Test river",
    monitoring_station_id: "TAUNSA", telemetry_status: "test", data_status: "test" },
})) };
let historyCalls = 0;
let delayStation = "";
let releaseHistory;
const prepare = async (context) => {
  await context.route("**/api/v1/**", (route) => route.fulfill({ status: 503, json: { detail: "Unavailable test feed" } }));
  await context.route("**/api/v1/river/monitoring", (route) => route.fulfill({ json: feed }));
  await context.route("**/api/v1/gis/water-intelligence", (route) => route.fulfill({ json: water }));
  await context.route("**/api/v1/river/monitoring/*/history", async (route) => {
    historyCalls++;
    const id = route.request().url().split("/").at(-2);
    if (id === delayStation) await new Promise((resolve) => { releaseHistory = resolve; });
    await route.fulfill({ json: { station_id: id, source: "FFD stored observations", samples: [
      { time: new Date(now.getTime() - 24 * 3600000).toISOString(), value: 100 },
      { time: new Date(now.getTime() - 3 * 3600000).toISOString(), value: 125 }, { time: now.toISOString(), value: 130 },
    ] } }).catch(() => {});
  });
};
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await prepare(context);
  const page = await context.newPage(); const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(mapTestUrl("http://localhost:3000"), { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.querySelector(".national-map")?.dataset.priorityMonitoringSites, null, { timeout: 90000 });
  for (const name of ["Major barrages & headworks", "Upstream river stations", "Major dams & reservoirs", "Confluence watch locations"]) await page.getByRole("checkbox", { name, exact: true }).check();
  const locate = async (id) => {
    const site = monitoringSites.features.find((feature) => feature.id === id);
    const [longitude, latitude] = site.geometry.coordinates;
    await page.getByRole("textbox", { name: "Target latitude", exact: true }).fill(String(latitude));
    await page.getByRole("textbox", { name: "Target longitude", exact: true }).fill(String(longitude));
    await page.getByRole("button", { name: "Locate coordinates", exact: true }).click();
    await page.getByRole("button", { name: "Close coordinate details", exact: true }).click();
    await page.waitForFunction(({ id, latitude, longitude }) => {
      const el = document.querySelector(".national-map"); const d = el?.dataset;
      const selected = JSON.parse(d?.locatedCoordinate ?? "null");
      const target = JSON.parse(d?.priorityMonitoringTargets ?? "[]").find((target) => target.id === id);
      return selected?.latitude === latitude && selected.longitude === longitude && Number(d.mapZoom) >= 9.9 && target?.x > 250 && target.x < el.clientWidth - 100 && target.y > 250 && target.y < el.clientHeight - 180;
    }, { id, latitude, longitude }, { timeout: 60000 });
    const target = await page.locator(".national-map").evaluate((el, id) => JSON.parse(el.dataset.priorityMonitoringTargets).find((point) => point.id === id), id);
    const box = await page.locator(".national-map").boundingBox(); return { x: box.x + target.x, y: box.y + target.y };
  };
  const card = page.locator(".station-info-card");
  const assertPosition = async () => {
    await page.waitForFunction(() => { const popup = document.querySelector(".station-info-popup"); return popup && getComputedStyle(popup).opacity === "1"; });
    const box = await card.boundingBox(); assert.ok(box && box.x >= 0 && box.y >= 0 && box.x + box.width <= 1440 && box.y + box.height <= 1000);
    const obstacles = await page.locator(".map-layer-control,.map-command-overlay,.map-legend,.hourly-analytics-ticker").evaluateAll((elements) => elements.map((el) => { const r = el.getBoundingClientRect(); return { left: r.left, top: r.top, right: r.right, bottom: r.bottom }; }));
    for (const obstacle of obstacles) assert.ok(box.x + box.width <= obstacle.left || box.x >= obstacle.right || box.y + box.height <= obstacle.top || box.y >= obstacle.bottom, "Popup must avoid map overlays");
  };
  for (const id of ["TAUNSA", "KALABAGH", "TARBELA", "KABUL_INDUS"]) {
    console.log(`Checking ${id}`);
    const point = await locate(id); const before = historyCalls;
    await page.mouse.move(point.x, point.y);
    await card.waitFor({ state: "visible" }); assert.equal(historyCalls, before, "Hover performs no history requests");
    assert.equal(await card.count(), 1);
    const expected = monitoringSites.features.find((feature) => feature.id === id).geometry.coordinates;
    assert.ok((await card.innerText()).includes(`${expected[1].toFixed(5)} N / ${expected[0].toFixed(5)} E`), "Original source coordinates are displayed");
    assert.ok(!(await card.innerText()).match(/undefined|null|NaN/));
    await assertPosition();
    if (id === "KABUL_INDUS") { assert.ok((await card.innerText()).includes("Planning reference, not an active monitoring station")); assert.equal(await card.locator("table").count(), 0); }
    if (id === "TARBELA") { assert.ok((await card.innerText()).includes("No recent data")); assert.equal(await card.locator(".station-stale-badge").count(), 1); }
    if (id === "TAUNSA") {
      const box = await card.boundingBox(); await page.mouse.move(box.x + box.width / 2, box.y + 30);
      await page.waitForTimeout(300); assert.equal(await card.isVisible(), true, "Moving into card does not flicker");
      await card.getByRole("button", { name: "Pin station card", exact: true }).click();
      await card.locator(".station-sparkline").waitFor(); assert.equal(historyCalls, before + 1);
      assert.ok((await card.innerText()).includes("5 cumecs"));
      await page.mouse.move(1300, 600); await page.waitForTimeout(300); assert.equal(await card.isVisible(), true, "Pinned persists after leave");
      await page.keyboard.press("Escape"); await card.waitFor({ state: "hidden" });
      await page.mouse.click(point.x, point.y); await card.waitFor({ state: "visible" }); assert.equal(historyCalls, before + 1, "Pinned history is cached");
      await page.waitForTimeout(200);
      await page.screenshot({ path: "screenshots/station-popup-desktop.png" });
      await card.getByRole("button", { name: "Open station details", exact: true }).click();
      await page.getByRole("complementary", { name: "River station details", exact: true }).waitFor();
      await page.getByRole("button", { name: "Close station details", exact: true }).click();
    } else { await page.mouse.move(1300, 600); await card.waitFor({ state: "hidden" }); }
  }
  await locate("TAUNSA"); await page.getByRole("checkbox", { name: "River monitoring", exact: true }).check();
  await page.waitForFunction(() => JSON.parse(document.querySelector(".national-map").dataset.monitoringStations ?? "[]").length > 400);
  const beforeSweep = await page.locator(".national-map").evaluate((el) => ({ q: Number(el.dataset.stationHoverQueries ?? 0), r: Number(el.dataset.stationCardRenders ?? 0), updates: el.dataset.sourceUpdates }));
  const beforeRequests = historyCalls;
  await page.locator(".maplibregl-canvas").evaluate((canvas) => {
    const rect = canvas.getBoundingClientRect();
    for (let i = 0; i < 1000; i++) canvas.dispatchEvent(new MouseEvent("mousemove", { clientX: rect.left + 600 + i % 200, clientY: rect.top + 400 + i % 100, bubbles: true }));
  });
  await page.waitForTimeout(50);
  const afterSweep = await page.locator(".national-map").evaluate((el) => ({ q: Number(el.dataset.stationHoverQueries ?? 0), r: Number(el.dataset.stationCardRenders ?? 0), updates: el.dataset.sourceUpdates }));
  assert.ok(afterSweep.q - beforeSweep.q <= 2, "Burst is RAF-throttled"); assert.equal(afterSweep.r, beforeSweep.r, "No card render before intent");
  assert.equal(historyCalls, beforeRequests); assert.equal(afterSweep.updates, beforeSweep.updates, "Hover does not rerender map sources");
  const target = await locate("KALABAGH"); await page.mouse.move(target.x, target.y); await card.waitFor({ state: "visible" });
  await page.getByRole("checkbox", { name: "Upstream river stations", exact: true }).uncheck(); await card.waitFor({ state: "hidden" });
  await page.waitForFunction(() => !JSON.parse(document.querySelector(".national-map").dataset.priorityMonitoringTargets ?? "[]").some((point) => point.id === "KALABAGH"));
  await page.getByRole("checkbox", { name: "Upstream river stations", exact: true }).check();
  await page.waitForFunction(() => JSON.parse(document.querySelector(".national-map").dataset.priorityMonitoringTargets ?? "[]").some((point) => point.id === "KALABAGH"));
  await page.mouse.move(target.x, target.y); await card.waitFor({ state: "visible" });
  await page.waitForFunction(() => document.querySelector(".station-info-card")?.dataset.stationId === "KALABAGH");
  delayStation = "KALABAGH";
  const requested = page.waitForRequest((request) => request.url().includes("/KALABAGH/history"));
  const abortedBefore = await page.locator(".national-map").evaluate((el) => Number(el.dataset.stationHistoryAborts ?? 0));
  await card.getByRole("button", { name: "Pin station card", exact: true }).click(); await requested;
  await page.keyboard.press("Escape");
  await page.waitForFunction((before) => Number(document.querySelector(".national-map").dataset.stationHistoryAborts ?? 0) > before, abortedBefore);
  releaseHistory?.(); await card.waitFor({ state: "hidden" });
  console.log("Pending pinned history aborted on Esc.");
  delayStation = "";
  await page.locator(".station-point-focus").focus(); await card.waitFor({ state: "visible" });
  await page.keyboard.press("ArrowRight"); await page.keyboard.press("Enter"); await page.waitForFunction(() => document.querySelector(".station-info-card")?.dataset.pinned === "true");
  await page.keyboard.press("Escape"); await card.waitFor({ state: "hidden" });
  await page.getByRole("combobox", { name: "Catchment area", exact: true }).selectOption("1729");
  await page.waitForFunction(() => {
    const data = JSON.parse(document.querySelector(".national-map").dataset.priorityMonitoringSites);
    return data.features.length < 28 && !data.features.some((feature) => feature.id === "KALABAGH");
  });
  assert.deepEqual(errors, []);
  console.log("Desktop: four templates, zero-request hover, shared popup, pin/cache, no flicker, layout, 450 native gauges, RAF sweep, visibility and keyboard passed.");

  const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  await prepare(mobile); const touch = await mobile.newPage();
  touch.on("pageerror", (error) => errors.push(error.message));
  await touch.goto(mapTestUrl("http://localhost:3000"), { waitUntil: "domcontentloaded" });
  await touch.waitForFunction(() => document.querySelector(".national-map")?.dataset.priorityMonitoringSites, null, { timeout: 90000 });
  await touch.getByRole("button", { name: "Toggle map layers", exact: true }).tap();
  await touch.getByRole("checkbox", { name: "Major barrages & headworks", exact: true }).check();
  await touch.getByRole("button", { name: "Toggle map layers", exact: true }).tap();
  await touch.waitForFunction(() => JSON.parse(document.querySelector(".national-map").dataset.priorityMonitoringTargets ?? "[]").some((point) => point.id === "TAUNSA"));
  const point = await touch.locator(".national-map").evaluate((el) => { const target = JSON.parse(el.dataset.priorityMonitoringTargets).find((point) => point.id === "TAUNSA"); const rect = el.getBoundingClientRect(); return { x: rect.x + target.x, y: rect.y + target.y }; });
  await touch.touchscreen.tap(point.x, point.y);
  const mobileCard = touch.locator(".station-info-card"); await mobileCard.waitFor({ state: "visible" });
  await touch.waitForFunction(() => { const popup = document.querySelector(".station-info-popup"); return popup && getComputedStyle(popup).opacity === "1"; });
  assert.equal(await mobileCard.getAttribute("data-pinned"), "true");
  const box = await mobileCard.boundingBox(); assert.ok(box.x >= 0 && box.x + box.width <= 390 && box.y >= 0 && box.y + box.height <= 844);
  const mobileObstacles = await touch.locator(".topbar,.map-command-overlay,.map-legend,.hourly-analytics-ticker,.map-layer-control").evaluateAll((elements) => elements.map((el) => { const r = el.getBoundingClientRect(); return { left: r.left, top: r.top, right: r.right, bottom: r.bottom }; }));
  for (const obstacle of mobileObstacles) assert.ok(box.x + box.width <= obstacle.left || box.x >= obstacle.right || box.y + box.height <= obstacle.top || box.y >= obstacle.bottom, "Touch popup avoids dashboard overlays");
  await touch.screenshot({ path: "screenshots/station-popup-mobile.png" });
  await mobileCard.getByRole("button", { name: "Close station card", exact: true }).tap(); await mobileCard.waitFor({ state: "hidden" });
  assert.deepEqual(errors, []);
  console.log("Touch: tap pins the shared card within mobile viewport; close works.");
} finally { await browser.close(); }
