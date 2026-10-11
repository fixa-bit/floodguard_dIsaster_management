import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { chromium } from "playwright";
import { mapTestUrl } from "./map-test-url.mjs";

const browser = await chromium.launch({ executablePath: process.env.EDGE_PATH ?? "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
const diagnostics = () => page.locator(".national-map").evaluate((element) => ({ ...element.dataset }));
const waitRendered = () => page.waitForFunction(() => {
  const data = document.querySelector(".national-map")?.dataset;
  return Number(data?.renderedGlaciers) > 0 && Number(data?.renderedExternalGlaciers) > 0;
}, null, { timeout: 90000 });
try {
  await mkdir("screenshots", { recursive: true });
  await page.goto(mapTestUrl(process.env.DASHBOARD_URL ?? "http://localhost:3000"), { waitUntil: "domcontentloaded" });
  const toggle = page.getByRole("checkbox", { name: "Glaciers & upstream drainage", exact: true });
  await toggle.waitFor({ timeout: 60000 });
  assert.equal(await toggle.isChecked(), false);
  await toggle.check();
  await waitRendered();
  assert.ok(Number((await diagnostics()).glacierFeatures) > 1000);
  await page.screenshot({ path: "screenshots/glaciers-desktop.png" });
  const filter = page.getByRole("combobox", { name: "Glacier coverage", exact: true });
  await filter.selectOption("external");
  await page.waitForFunction(() => {
    const data = document.querySelector(".national-map")?.dataset;
    return data?.glacierView === "external" && Number(data.renderedGlaciers) > 0 && data.renderedGlaciers === data.renderedExternalGlaciers;
  }, null, { timeout: 60000 });
  const bounds = await page.locator(".national-map").boundingBox();
  const point = JSON.parse((await diagnostics()).glacierClickTargets).find((target) => target.x > 240 && target.x < bounds.width - 20 && target.y > 220 && target.y < bounds.height - 160);
  assert.ok(point, "External contributor must have a visible click target");
  await page.mouse.click(bounds.x + point.x, bounds.y + point.y);
  const inspector = page.getByRole("complementary", { name: "Glacier details", exact: true });
  await inspector.waitFor();
  assert.ok((await inspector.innerText()).includes("Outside Pakistan operational footprint"));
  assert.ok((await inspector.innerText()).includes("Indus river system"));
  await page.screenshot({ path: "screenshots/glacier-external-details.png" });
  await page.getByRole("button", { name: "Close glacier details", exact: true }).click();
  await filter.selectOption("contributors");
  await waitRendered();
  await toggle.uncheck();
  assert.equal((await diagnostics()).glacierVisibility, "none");
  await toggle.check();
  await filter.selectOption("all");
  await waitRendered();
  await page.setViewportSize({ width: 390, height: 844 });
  await waitRendered();
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  const layers = page.getByRole("button", { name: "Toggle map layers", exact: true });
  if (await layers.getAttribute("aria-expanded") === "true") await layers.click();
  await page.screenshot({ path: "screenshots/glaciers-mobile.png" });
  assert.deepEqual(errors, []);
  console.log("PASS: real glacier polygons and external contributors render; filters, inspector, toggle and mobile layout work.");
} catch (error) {
  console.log("Glacier diagnostics:", await diagnostics(), errors);
  await page.screenshot({ path: "screenshots/glaciers-failure.png" });
  throw error;
} finally {
  await browser.close();
}
