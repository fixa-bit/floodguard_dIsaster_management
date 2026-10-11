import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { chromium } from "playwright";
import { mapTestUrl } from "./map-test-url.mjs";

const browser = await chromium.launch({ executablePath: process.env.EDGE_PATH ?? "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
const waitVisible = () => page.waitForFunction(() => {
  const data = document.querySelector(".national-map")?.dataset;
  return data?.kashmirBoundaryVisibility === "visible" && Number(data.renderedKashmirContext) > 0;
}, null, { timeout: 60000 });
try {
  await mkdir("screenshots", { recursive: true });
  await page.goto(mapTestUrl(process.env.DASHBOARD_URL ?? "http://localhost:3000"), { waitUntil: "domcontentloaded" });
  await waitVisible();
  const paint = JSON.parse(await page.locator(".national-map").getAttribute("data-boundary-paint"));
  assert.equal(paint.length, 5);
  for (const layer of paint) {
    assert.equal(layer.dash, null, `${layer.id} must be solid`);
    assert.deepEqual(layer.width, ["interpolate", ["linear"], ["zoom"], 3, 3, 7, 4, 10, 5]);
    assert.equal(layer.opacity, 1);
  }
  const boundary = page.getByRole("checkbox", { name: "Pakistan boundary", exact: true });
  assert.equal(await boundary.isChecked(), true);
  assert.equal(await page.getByRole("checkbox", { name: "District screening", exact: true }).isChecked(), false);
  await page.getByText("Jammu & Kashmir (disputed)", { exact: true }).waitFor();
  await page.screenshot({ path: "screenshots/kashmir-boundary-desktop.png" });
  await boundary.uncheck();
  await page.waitForFunction(() => document.querySelector(".national-map")?.dataset.kashmirBoundaryVisibility === "none");
  await boundary.check();
  await waitVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await waitVisible();
  const controls = page.getByRole("button", { name: "Toggle map layers", exact: true });
  if (await controls.getAttribute("aria-expanded") === "true") await controls.click();
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({ path: "screenshots/kashmir-boundary-mobile.png" });
  assert.deepEqual(errors, []);
  console.log("PASS: Kashmir is included in the default boundary without screening; boundary toggle controls Kashmir; desktop/mobile render correctly.");
} finally {
  await browser.close();
}
