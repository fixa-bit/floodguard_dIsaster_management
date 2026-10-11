import assert from "node:assert/strict";
import { chromium } from "playwright";
import { mapTestUrl } from "./map-test-url.mjs";

const browser = await chromium.launch({ executablePath: process.env.EDGE_PATH ?? "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
let inventoryRequests = 0;
page.on("request", (request) => { if (request.resourceType() === "fetch" && /\/glaciers(?:-[\w-]+)?\.geojson(?:\.gz)?(?:\?|$)/.test(request.url())) inventoryRequests++; });
const data = () => page.locator(".national-map").evaluate((element) => ({ ...element.dataset }));
try {
  await page.goto(mapTestUrl(process.env.DASHBOARD_URL ?? "http://localhost:3000"), { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => Number(document.querySelector(".national-map")?.dataset.glacierFeatures) > 1000, null, { timeout: 90000 });
  console.log("Inventory loaded; checking isolated source updates.");
  const before = JSON.parse((await data()).sourceUpdates);
  const measure = page.getByRole("combobox", { name: "Water quantity", exact: true });
  await measure.selectOption("current");
  await page.waitForFunction((count) => JSON.parse(document.querySelector(".national-map").dataset.sourceUpdates)["observed-water-stations"] > count, before["observed-water-stations"]);
  const after = JSON.parse((await data()).sourceUpdates);
  for (const id of ["glaciers", "district-risk", "water-lines", "river-status-lines", "water-bodies", "model-water-points"]) {
    assert.equal(after[id], before[id], `${id} must not be resent when station measure changes`);
  }
  assert.equal((await data()).rainfallVisibility, "none", "Prepared rainfall must stay hidden until enabled");
  const glacierToggle = page.getByRole("checkbox", { name: "Glaciers & upstream drainage", exact: true });
  for (let i = 0; i < 3; i++) { await glacierToggle.uncheck(); await glacierToggle.check(); }
  assert.equal(JSON.parse((await data()).sourceUpdates).glaciers, before.glaciers);
  assert.equal(inventoryRequests, 1);
  for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    const bounds = await page.locator(".national-map").boundingBox();
    await page.mouse.move(bounds.x + bounds.width * 0.85, bounds.y + bounds.height * 0.5);
    const coordinates = page.getByLabel("Map cursor coordinates", { exact: true });
    await coordinates.waitFor({ state: "visible" });
    assert.match(await coordinates.textContent(), /^Lat: -?\d+\.\d{6}\s+Lon: -?\d+\.\d{6}$/);
    await page.getByRole("button", { name: "Toggle map layers", exact: true }).hover();
    await coordinates.waitFor({ state: "hidden" });
  }
  assert.deepEqual(errors, []);
  console.log("PASS: station controls update only their source; background rainfall stays hidden; glacier toggles do not resend or redownload geometry; desktop/mobile coordinate hover works.");
} finally { await browser.close(); }
