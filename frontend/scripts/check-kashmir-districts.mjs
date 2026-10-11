import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { chromium } from "playwright";
import { mapTestUrl } from "./map-test-url.mjs";

const browser = await chromium.launch({ executablePath: process.env.EDGE_PATH ?? "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
const zoomToKathua = async () => {
  const map = page.locator(".national-map");
  const bounds = await map.boundingBox();
  const target = JSON.parse(await map.getAttribute("data-kashmir-district-targets")).find((point) => point.name === "Kathua");
  const x = bounds.x + bounds.width / 2;
  const y = bounds.y + bounds.height / 2;
  await page.mouse.move(bounds.x + target.x, bounds.y + target.y);
  await page.mouse.down();
  await page.mouse.move(x, y, { steps: 12 });
  await page.mouse.up();
  await page.waitForTimeout(500);
  for (let step = 0; step < 4; step++) {
    const zoom = Number(await map.getAttribute("data-map-zoom"));
    await page.mouse.move(x, y);
    await page.mouse.wheel(0, -500);
    await page.waitForFunction((previous) => Number(document.querySelector(".national-map")?.dataset.mapZoom) > previous + 0.2, zoom);
  }
  await page.waitForFunction(() => JSON.parse(document.querySelector(".national-map")?.dataset.renderedDistrictNames ?? "[]").includes("Kathua"));
};
try {
  await page.route("**/api/v1/**", (route) => route.fulfill({ status: 503, json: { detail: "Feeds intentionally unavailable for static-layer test" } }));
  await page.goto(mapTestUrl(process.env.DASHBOARD_URL ?? "http://localhost:3000"), { waitUntil: "domcontentloaded" });
  const toggle = page.getByRole("checkbox", { name: "District names & boundaries", exact: true });
  await toggle.waitFor({ timeout: 90000 });
  assert.equal(await toggle.isChecked(), false);
  await toggle.check();
  await page.waitForFunction(() => {
    const data = document.querySelector(".national-map")?.dataset;
    return data?.districtSourceFeatures === "167" && Number(data.renderedKashmirDistricts) > 0;
  }, null, { timeout: 90000 });
  const names = JSON.parse(await page.locator(".national-map").getAttribute("data-district-names"));
  for (const name of ["Muzaffarabad", "Bagh", "Neelum", "Srinagar", "Jammu", "Kargil"]) assert.ok(names.includes(name), name);
  assert.equal(await page.getByRole("checkbox", { name: "District screening", exact: true }).isChecked(), false);
  const target = JSON.parse(await page.locator(".national-map").getAttribute("data-kashmir-district-targets")).find((point) => point.name === "Srinagar");
  const bounds = await page.locator(".national-map").boundingBox();
  await page.mouse.move(bounds.x + target.x, bounds.y + target.y);
  await page.mouse.wheel(0, -800);
  await page.waitForFunction(() => JSON.parse(document.querySelector(".national-map")?.dataset.renderedDistrictNames ?? "[]").includes("Srinagar"), null, { timeout: 60000 });
  await mkdir("screenshots", { recursive: true });
  await page.screenshot({ path: "screenshots/kashmir-districts-desktop.png" });
  await page.getByRole("button", { name: "Show regional Pakistan overview", exact: true }).click();
  await page.waitForTimeout(700);
  await zoomToKathua();
  await page.waitForTimeout(700);
  await page.screenshot({ path: "screenshots/kathua-alignment-desktop.png" });
  await toggle.uncheck();
  await page.waitForFunction(() => document.querySelector(".national-map")?.dataset.districtBoundariesVisibility === "none");
  await toggle.check();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForFunction(() => Number(document.querySelector(".national-map")?.dataset.renderedKashmirDistricts) > 0);
  const controls = page.getByRole("button", { name: "Toggle map layers", exact: true });
  if (await controls.getAttribute("aria-expanded") === "true") await controls.click();
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({ path: "screenshots/kashmir-districts-mobile.png" });
  await page.waitForFunction(() => {
    const map = document.querySelector(".national-map");
    const target = JSON.parse(map?.dataset.kashmirDistrictTargets ?? "[]").find((point) => point.name === "Kathua");
    return target && target.x > 0 && target.x < map.clientWidth && target.y > 0 && target.y < map.clientHeight;
  });
  await zoomToKathua();
  await page.waitForTimeout(700);
  await page.screenshot({ path: "screenshots/kathua-alignment-mobile.png" });
  assert.deepEqual(errors, []);
  console.log("PASS: Kashmir district borders and zoomed labels render with risk feed unavailable; toggle and mobile layout work.");
} finally { await browser.close(); }
