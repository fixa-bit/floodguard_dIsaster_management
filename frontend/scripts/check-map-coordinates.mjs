import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { chromium } from "playwright";

const browser = await chromium.launch({
  executablePath: process.env.EDGE_PATH ?? "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true,
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
try {
  await mkdir("screenshots", { recursive: true });
  await page.goto(process.env.DASHBOARD_URL ?? "http://localhost:3000", { waitUntil: "domcontentloaded" });
  await page.locator(".national-map canvas").waitFor({ timeout: 60000 });
  const readout = page.getByLabel("Map cursor coordinates", { exact: true });
  for (const [name, width, height] of [["desktop", 1440, 1000], ["mobile", 390, 844]]) {
    await page.setViewportSize({ width, height });
    await page.waitForTimeout(1500);
    const bounds = await page.locator(".national-map").boundingBox();
    const readAt = async (x, y) => {
      await page.mouse.move(bounds.x + x, bounds.y + y);
      await readout.waitFor({ state: "visible" });
      const text = await readout.textContent();
      const match = /^Lat: (-?\d+\.\d{6})\s+Lon: (-?\d+\.\d{6})$/.exec(text);
      assert.ok(match, "Every map hover must show numeric latitude and longitude");
      const box = await readout.boundingBox();
      assert.ok(box.x >= bounds.x && box.x + box.width <= bounds.x + bounds.width + 1);
      assert.ok(box.y >= bounds.y && box.y + box.height <= bounds.y + bounds.height + 1);
      return { latitude: Number(match[1]), longitude: Number(match[2]) };
    };
    const initial = await readAt(bounds.width * 0.65, bounds.height * 0.4);
    const east = await readAt(bounds.width * 0.85, bounds.height * 0.4);
    assert.ok(east.longitude > initial.longitude, "Longitude must increase when the cursor moves east");
    const south = await readAt(bounds.width * 0.85, bounds.height * 0.6);
    assert.ok(south.latitude < east.latitude, "Latitude must decrease when the cursor moves south");
    await readAt(bounds.width - 4, bounds.height * 0.6);
    await page.screenshot({ path: `screenshots/map-coordinate-hover-${name}.png` });
    await page.getByRole("button", { name: "Toggle map layers", exact: true }).hover();
    await readout.waitFor({ state: "hidden" });
  }
  assert.deepEqual(errors, []);
  console.log("PASS: map-wide hover coordinates update geographically, remain within desktop/mobile bounds, and hide on exit.");
} finally {
  await browser.close();
}
