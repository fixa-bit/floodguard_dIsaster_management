import assert from "node:assert/strict";
import { chromium } from "playwright";

const browser = await chromium.launch({ executablePath: process.env.EDGE_PATH ?? "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const requests = [];
  const errors = [];
  let failAlerts = false;
  page.on("pageerror", (error) => errors.push(error.message));
  await page.clock.install();
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    requests.push(url.pathname + url.search);
    // Leave weather pending to reproduce the real frontend timeout.
    if (url.pathname.endsWith("/weather/current")) return;
    if (/\/(gis|flood|river)\//.test(url.pathname)) return route.fulfill({ status: 503, json: { error: { code: "PROVIDER_UNAVAILABLE", message: "Live provider unavailable" } } });
    if (url.pathname.endsWith("/simulation/monitoring/stations")) return route.fulfill({ json: [{ code: "TAUNSA", name: "Taunsa", river: "Indus", thresholds: [] }] });
    if (url.pathname.endsWith("/alerts") && failAlerts) return route.fulfill({ status: 503, json: { error: { code: "ALERTS_UNAVAILABLE", message: "Cannot load alerts" } } });
    return route.fulfill({ json: /\/(summary|status)$/.test(url.pathname) ? null : [] });
  });
  const weatherStarted = page.waitForRequest((request) => request.url().includes("/weather/current?location_id=ISB_001"));
  await page.goto(process.env.FRONTEND_URL ?? "http://127.0.0.1:3000/", { waitUntil: "domcontentloaded" });
  await weatherStarted;
  await page.clock.fastForward(31000);
  await page.locator(".error-banner").waitFor();
  assert.match(await page.locator(".error-banner").innerText(), /Weather \(JHG_001\): FloodGuard backend request timed out/);
  assert.equal(requests.filter((path) => path === "/api/v1/weather/current?location_id=JHG_001").length, 1);
  assert.equal(requests.filter((path) => path === "/api/v1/river/current?location_id=JHG_001").length, 1);

  const dashboardLivePaths = new Set(["/api/v1/weather/current", "/api/v1/river/current", "/api/v1/flood/risk", "/api/v1/flood/model-forecasts", "/api/v1/gis/national-risk", "/api/v1/gis/water-intelligence"]);
  const liveCount = () => requests.filter((path) => dashboardLivePaths.has(path.split("?")[0])).length;
  const beforeSimulation = liveCount();
  failAlerts = true;
  await page.locator(".sidebar nav").getByRole("button", { name: "Simulation", exact: true }).click();
  await page.getByRole("combobox", { name: "Station", exact: true }).waitFor();
  await page.getByText("Alerts: ALERTS_UNAVAILABLE: Cannot load alerts", { exact: true }).waitFor();
  assert.equal(liveCount(), beforeSimulation, "Simulation must not request unrelated live feeds");
  assert.doesNotMatch(await page.locator(".error-banner").innerText(), /Weather|Live provider/);
  failAlerts = false;
  await page.locator(".error-banner").getByRole("button", { name: "Retry", exact: true }).click();
  await page.waitForResponse((response) => response.url().endsWith("/alerts") && response.status() === 200);
  await page.waitForFunction(() => !document.querySelector(".error-banner"));
  assert.equal(liveCount(), beforeSimulation);

  // An old live refresh may still be pending when the operator changes views.
  // Its later timeout must not overwrite the successful Simulation refresh.
  const nextWeatherStarted = page.waitForRequest((request) => request.url().includes("/weather/current?location_id=ISB_001"));
  await page.reload({ waitUntil: "domcontentloaded" });
  await nextWeatherStarted;
  await page.locator(".sidebar nav").getByRole("button", { name: "Simulation", exact: true }).click();
  await page.getByRole("combobox", { name: "Station", exact: true }).waitFor();
  await page.clock.fastForward(31000);
  assert.equal(await page.locator(".error-banner").count(), 0, "An obsolete live timeout must not leak into Simulation");
  assert.deepEqual(errors, []);
  console.log("Dashboard error checks passed: named timeouts, shared requests, Simulation isolation, operational failures, retry recovery, and obsolete timeout isolation.");
} finally {
  await browser.close();
}
