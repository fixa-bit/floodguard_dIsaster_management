import assert from "node:assert/strict";
import { mkdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const data = JSON.parse(await readFile(new URL("../src/data/jhang-terrain-prototype/jhang-pilot.geojson", import.meta.url), "utf8"));
const browser = await chromium.launch({ executablePath: process.env.EDGE_PATH ?? "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
const errors = [], writes = [], requests = [];
try {
  await mkdir(new URL("../screenshots/", import.meta.url), { recursive: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } });
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => { requests.push(request.url()); if (!["GET", "OPTIONS"].includes(request.method())) writes.push(request.url()); });
  await page.route("**/api/v1/**", route => new URL(route.request().url()).pathname.endsWith("/simulation/monitoring/stations")
    ? route.fulfill({ json: [{ code: "TAUNSA", name: "Taunsa", river: "Indus", thresholds: [] }] })
    : route.fulfill({ status: 503, json: { error: { code: "PILOT_CHECK", message: "Operational feeds excluded from prototype checks" } } }));
  await page.route("**/World_Imagery/MapServer/tile/**", route => route.abort());
  let failData = true;
  await page.route("**/*jhang-pilot-*.geojson.gz*", route => failData ? route.fulfill({ status: 503, body: "data unavailable" }) : route.continue());
  await page.goto(process.env.FRONTEND_URL ?? "http://127.0.0.1:3000/", { waitUntil: "domcontentloaded" });
  await page.locator(".sidebar nav").getByRole("button", { name: "Simulation", exact: true }).click();
  const monitoring = page.getByRole("tab", { name: "Monitoring scenario", exact: true });
  await page.getByRole("slider", { name: "Reading 1 value", exact: true }).fill("321000");
  await page.getByRole("tab", { name: "Storm replay", exact: true }).click();
  assert.equal(requests.filter(url => url.includes("jhang-pilot-")).length, 0, "Terrain data is lazy, not loaded by original replay");
  await page.getByRole("button", { name: "Jhang terrain prototype", exact: false }).click();
  const root = page.locator(".terrain-pilot");
  await root.getByRole("button", { name: "Retry terrain data", exact: true }).waitFor();
  assert.equal(await root.getByRole("slider").isDisabled(), true, "Missing data disables controls");
  failData = false;
  await root.getByRole("button", { name: "Retry terrain data", exact: true }).click();
  await page.waitForFunction(() => document.querySelector(".terrain-pilot-map")?.dataset.ready === "true" && Number(document.querySelector(".terrain-pilot-map")?.dataset.renderedWater) > 0);
  assert.equal(await root.locator("canvas").count(), 2, "Only one map engine plus water overlay");
  assert.equal(await page.locator(".storm-replay:not(.terrain-pilot)").count(), 0);
  const slider = root.getByRole("slider", { name: "Terrain prototype rise example", exact: true });
  const overlay = root.locator(".storm-replay-currents");
  await page.waitForFunction(() => Number(document.querySelector(".terrain-pilot .storm-replay-currents")?.dataset.streaks) > 0);
  for (const level of [0, 1, 3, 5, 2]) {
    await slider.fill(String(level));
    await page.waitForFunction(value => document.querySelector(".terrain-pilot-map").dataset.level === String(value), level);
    for (const [kind, field] of [["population", "exposed_population"], ["area", "flood_area_km2"]]) {
      const meter = root.locator(`.storm-replay-impact[data-kind="${kind}"] [role="meter"]`);
      assert.equal(Number(await meter.getAttribute("aria-valuenow")), data.levels[level][field]);
      assert.equal(Number(await meter.getAttribute("aria-valuemax")), data.levels[5][field]);
    }
  }
  await root.getByText(/Satellite imagery is unavailable/).waitFor();
  await root.getByRole("button", { name: "Population", exact: true }).click();
  await root.getByRole("button", { name: "Connection paths", exact: true }).click();
  await page.waitForFunction(() => document.querySelector(".terrain-pilot-map").dataset.population === "true" && document.querySelector(".terrain-pilot-map").dataset.paths === "true");
  await root.getByRole("button", { name: "Explore river bend", exact: true }).click();
  await page.waitForTimeout(1800);
  const closeZoom = Number(await root.locator(".terrain-pilot-map").getAttribute("data-zoom"));
  await root.getByRole("button", { name: "Study area", exact: true }).click();
  await page.waitForTimeout(1200);
  assert(closeZoom > Number(await root.locator(".terrain-pilot-map").getAttribute("data-zoom")) + .4);
  await root.locator(".storm-replay-layout").screenshot({ path: fileURLToPath(new URL("../screenshots/jhang-terrain-prototype.png", import.meta.url)) });
  await slider.fill("0");
  await root.getByRole("button", { name: "Play rise examples", exact: true }).click();
  await page.waitForFunction(() => Number(document.querySelector(".terrain-pilot").dataset.level) >= 1);
  await root.getByRole("button", { name: "Pause examples", exact: true }).click();
  const frozenLevel = await slider.inputValue(), phase = await overlay.getAttribute("data-phase");
  await page.waitForTimeout(2400);
  assert.equal(await slider.inputValue(), frozenLevel);
  assert.equal(await overlay.getAttribute("data-phase"), phase, "Paused surface is frozen");
  await slider.fill("4");
  await root.getByRole("button", { name: "Play rise examples", exact: true }).click();
  await page.waitForFunction(() => document.querySelector(".terrain-pilot").dataset.level === "5" && document.querySelector(".terrain-pilot").dataset.playing === "false");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await root.getByText(/Your browser prefers reduced motion/).waitFor();
  assert.equal(await root.getByRole("button", { name: "Play rise examples", exact: true }).isDisabled(), true);
  await slider.fill("1");
  assert.equal(await root.getAttribute("data-level"), "1", "Static controls work with reduced motion");
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.waitForFunction(() => ![...document.querySelectorAll('.terrain-pilot button')].find(button => button.textContent === 'Play rise examples')?.disabled);
  await root.getByRole("button", { name: "Play rise examples", exact: true }).click();
  await page.evaluate(() => { Object.defineProperty(document, "hidden", { configurable: true, value: true }); document.dispatchEvent(new Event("visibilitychange")); });
  await page.waitForFunction(() => document.querySelector(".terrain-pilot").dataset.playing === "false");
  await page.evaluate(() => { delete document.hidden; document.dispatchEvent(new Event("visibilitychange")); });
  await root.locator(".storm-replay-stage").scrollIntoViewIfNeeded();
  await page.waitForTimeout(150);
  await root.getByRole("button", { name: "Play rise examples", exact: true }).click();
  await root.locator(".storm-replay-method summary").click();
  await root.locator(".storm-replay-method").evaluate(element => element.scrollIntoView({ block: "start" }));
  await page.waitForFunction(() => document.querySelector(".terrain-pilot").dataset.playing === "false");
  await root.getByRole("heading", { name: "Future scope", exact: true }).waitFor();
  await root.getByRole("link", { name: "Source manifest and processing assumptions", exact: true }).waitFor();
  await page.getByRole("button", { name: "District storm replay", exact: false }).click();
  await page.waitForFunction(() => document.querySelector(".storm-replay:not(.terrain-pilot) .storm-replay-map")?.dataset.ready === "true");
  assert.equal(await page.locator(".terrain-pilot").count(), 0);
  assert.equal(await page.locator(".storm-replay canvas").count(), 2);
  await monitoring.click();
  assert.equal(await page.getByRole("slider", { name: "Reading 1 value", exact: true }).inputValue(), "321000", "Monitoring draft preserved");
  assert.deepEqual(writes, [], "Prototype cannot create operational alerts, readings or incidents");
  assert.deepEqual(errors, []);
  console.log("Jhang terrain prototype: lazy load/retry, terrain footprints, counters, layers, camera, animation, reduced motion, original replay and monitoring preservation passed.");
} finally { await browser.close(); }
