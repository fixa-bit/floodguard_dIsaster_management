import assert from "node:assert/strict";
import { chromium } from "playwright";

const browser = await chromium.launch({
  executablePath: process.env.EDGE_PATH ?? "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  headless: true,
});
try {
  for (const width of [1440, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route("**/api/v1/flood/water-extent/location?*", async (route) => {
      const request = new URL(route.request().url());
      assert.ok(request.searchParams.has("latitude"));
      assert.ok(request.searchParams.has("longitude"));
      await route.fulfill({ json: {
        model: "browser-test", label: "Water extent", threshold: 0.5,
        water_pixels: 1, valid_pixels: 1, water_percent: 100,
        coordinates: [[69, 31], [70, 31], [70, 30], [69, 30]],
        image_data_url: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==",
        during_date: "2026-10-03T00:00:00Z", pre_date: "2026-09-21T00:00:00Z",
      } });
    });
    await page.goto(process.env.DASHBOARD_URL ?? "http://127.0.0.1:3020/", { waitUntil: "domcontentloaded" });
    const control = page.locator(".sar-water-control").first();
    await control.waitFor({ state: "attached", timeout: 45000 });
    const toggle = page.locator(".map-layer-toggle").first();
    if (await toggle.getAttribute("aria-expanded") === "false") await toggle.click();
    await control.locator("summary").click();
    assert.equal(await control.locator("input[type=file]").count(), 0);
    await control.getByRole("button", { name: "Select place on map" }).click();
    await page.locator(".coordinate-pick-status").waitFor();
    if (await toggle.getAttribute("aria-expanded") === "true") await toggle.click();
    const canvas = page.locator(".national-map canvas");
    const bounds = await canvas.boundingBox();
    assert.ok(bounds);
    await canvas.click({ position: { x: bounds.width / 2, y: bounds.height / 2 }, force: true });
    if (await toggle.getAttribute("aria-expanded") === "false") await toggle.click();
    await control.getByText("100% of valid pixels", { exact: false }).waitFor({ timeout: 30000 });
    assert.equal(await control.evaluate((node) => node.scrollWidth <= node.clientWidth + 2), true);
    assert.deepEqual(errors, []);
    if (process.env.SAR_SCREENSHOT_DIR) {
      await page.screenshot({ path: `${process.env.SAR_SCREENSHOT_DIR}/sar-water-${width}.png` });
    }
    console.log(`Satellite water controls: ${width}px OK`);
    await page.close();
  }
} finally {
  await browser.close();
}
