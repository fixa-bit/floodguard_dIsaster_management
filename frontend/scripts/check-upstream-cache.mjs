import assert from "node:assert/strict";
import { chromium } from "playwright";

const browser = await chromium.launch({ executablePath: "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  await page.goto("http://127.0.0.1:3000/", { waitUntil: "domcontentloaded" });
  await page.locator(".overview-command-canvas").waitFor({ timeout: 60000 });
  await page.locator(".sidebar nav").getByRole("button", { name: "Upstream Source Flood Watch" }).click();
  const toolbar = page.locator(".source-cache-toolbar");
  await toolbar.getByText(/^Stored /).waitFor({ timeout: 60000 });
  const refresh = toolbar.getByRole("button", { name: "Refresh", exact: true });
  await page.waitForFunction(() => !document.querySelector(".source-refresh-button")?.disabled, { timeout: 60000 });
  assert.equal(await page.locator(".source-station-selector button").count(), 4);
  const before = await (await page.request.get("http://127.0.0.1:8000/api/v1/river/upstream-forecasts")).json();
  const paths = await page.locator(".source-forecast-chart path").count();
  const responsePromise = page.waitForResponse((response) => response.url().endsWith("/upstream-forecasts/refresh") && response.request().method() === "POST");
  await refresh.click();
  const response = await responsePromise;
  assert.ok(response.ok());
  assert.ok((await response.json()).refreshing);
  assert.equal(await page.locator(".source-forecast-chart path").count(), paths);
  assert.ok(await page.locator(".source-refresh-button").isDisabled());
  await page.waitForFunction(() => !document.querySelector(".source-refresh-button")?.disabled, { timeout: 60000 });
  const after = await (await page.request.get("http://127.0.0.1:8000/api/v1/river/upstream-forecasts")).json();
  assert.ok(Date.parse(after.cached_at) > Date.parse(before.cached_at));
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    await toolbar.screenshot({ path: `upstream-cache-${width}.png` });
  }
  console.log("Stored forecasts, four stations, nonblocking manual refresh, polling completion, timestamps, and responsive toolbar passed");
} finally {
  await browser.close();
}
