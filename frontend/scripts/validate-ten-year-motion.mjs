import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { previewPoint } from "../src/components/tenYearPreviewData.ts";

const browser = await chromium.launch({ executablePath: process.env.EDGE_PATH ?? "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
const errors = [];
const writes = [];
try {
  await mkdir(new URL("../screenshots/", import.meta.url), { recursive: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1050 } });
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => { if (!["GET", "OPTIONS"].includes(request.method())) writes.push(request.url()); });
  await page.goto(process.env.DASHBOARD_URL ?? "http://localhost:3000", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "Predictive Risk Views", exact: true }).click();
  const tab = page.getByRole("tab", { name: "10-Year Outlook", exact: true });
  await tab.click({ timeout: 50000 });
  await page.locator('.outlook-map-canvas[data-ready="true"]').nth(1).waitFor({ timeout: 50000 });
  await page.getByRole("button", { name: "Play decade", exact: true }).click();
  await page.waitForFunction(() => Number(document.querySelector('[aria-label="Planning year"]').value) >= 2027);
  await page.getByRole("button", { name: "Pause timeline", exact: true }).click();
  const pausedYear = Number(await page.getByLabel("Planning year", { exact: true }).inputValue());
  await page.waitForTimeout(1750);
  assert.equal(Number(await page.getByLabel("Planning year", { exact: true }).inputValue()), pausedYear, "Pause prevents subsequent year advances");
  assert.equal(Number(await page.locator(".outlook-chart-panel").getAttribute("data-selected-year")), pausedYear);
  assert.equal(parseFloat(await page.getByTestId("outlook-future").innerText()), previewPoint("all", "riverine", "moderate", pausedYear).value);

  const slider = page.getByRole("slider", { name: "Timeline year", exact: true });
  await slider.focus();
  await slider.press("Home");
  for (let index = 0; index < 5; index++) await slider.press("ArrowRight");
  assert.equal(await page.getByLabel("Planning year", { exact: true }).inputValue(), "2031");

  await page.getByRole("button", { name: "Start map tour", exact: true }).click();
  await page.waitForFunction(() => document.querySelector('[aria-label="Example area"]').value === "jhang");
  await page.waitForFunction(() => [...document.querySelectorAll('.outlook-map-canvas')].every((map) => Number(map.dataset.pitch) > 20 && map.dataset.moving !== "true"));
  const cameras = await page.locator(".outlook-map-canvas").evaluateAll((maps) => maps.map((map) => ({ zoom: map.dataset.zoom, center: map.dataset.center, pitch: map.dataset.pitch, bearing: map.dataset.bearing })));
  assert.deepEqual(cameras[0], cameras[1], "Both cinematic cameras remain synchronized");
  await page.getByRole("button", { name: "Play decade", exact: true }).click();
  await page.screenshot({ path: fileURLToPath(new URL("../screenshots/ten-year-motion-tour.png", import.meta.url)), fullPage: true });
  await page.waitForFunction(() => document.querySelector('[aria-label="Example area"]').value === "multan", undefined, { timeout: 9000 });
  await page.getByLabel("Example area", { exact: true }).selectOption("lahore");
  assert.equal(await page.getByRole("button", { name: "Start map tour", exact: true }).getAttribute("aria-pressed"), "false");
  assert.equal(await page.getByRole("button", { name: "Play decade", exact: true }).getAttribute("aria-pressed"), "false");

  await page.getByRole("button", { name: "Motion on", exact: true }).click();
  assert.equal(await page.getByRole("button", { name: "Play decade", exact: true }).isDisabled(), true);
  assert.equal(await page.getByRole("button", { name: "Start map tour", exact: true }).isDisabled(), true);
  assert.equal(await page.locator(".outlook-map-pulse i").first().evaluate((node) => getComputedStyle(node).animationName), "none");
  await page.getByRole("button", { name: "Motion off", exact: true }).click();
  await page.getByRole("button", { name: "Play decade", exact: true }).click();
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.waitForFunction(() => document.querySelector('.ten-year-outlook').dataset.motion === "off");
  assert.equal(await page.getByRole("button", { name: "Motion off", exact: true }).isDisabled(), true);
  assert.equal(await page.getByRole("button", { name: "Play decade", exact: true }).isDisabled(), true);
  await slider.press("Home");
  assert.equal(await page.getByLabel("Planning year", { exact: true }).inputValue(), "2026", "Static exploration works under reduced motion");

  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.waitForFunction(() => document.querySelector('.ten-year-outlook').dataset.motion === "on");
  await page.getByRole("button", { name: "Play decade", exact: true }).click();
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, value: true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.waitForFunction(() => document.querySelector('.ten-year-outlook').dataset.motion === "off");
  const hiddenYear = await page.getByLabel("Planning year", { exact: true }).inputValue();
  await page.waitForTimeout(1750);
  assert.equal(await page.getByLabel("Planning year", { exact: true }).inputValue(), hiddenYear, "Document visibility handler stops playback");
  await page.evaluate(() => { delete document.hidden; document.dispatchEvent(new Event("visibilitychange")); });
  await page.waitForFunction(() => document.querySelector('.ten-year-outlook').dataset.motion === "on");
  await page.getByRole("button", { name: "Play decade", exact: true }).click();
  await page.getByRole("tab", { name: "Near-Term Screening", exact: true }).click();
  const inactiveYear = await page.locator('[aria-label="Planning year"]').inputValue();
  await page.waitForTimeout(1750);
  assert.equal(await page.locator('[aria-label="Planning year"]').inputValue(), inactiveYear, "Hidden sub-tab cannot keep advancing years");
  assert.equal(await page.locator(".outlook-map-canvas canvas").count(), 0);
  await tab.click();
  await page.locator('.outlook-map-canvas[data-ready="true"]').nth(1).waitFor({ timeout: 50000 });
  assert.equal(await page.getByRole("button", { name: "Play decade", exact: true }).getAttribute("aria-pressed"), "false");
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  assert.deepEqual(errors, []);
  assert.deepEqual(writes, []);
  console.log("PASS: timeline playback/pause, keyboard scrubber, synchronized cinematic map tour, tour progression, manual takeover, motion-off control, reduced-motion preference, inactive-tab timer cleanup, and no backend writes or runtime errors.");
} finally {
  await browser.close();
}
