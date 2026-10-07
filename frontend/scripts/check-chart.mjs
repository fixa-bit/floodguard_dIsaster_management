import assert from "node:assert/strict";
import { chromium } from "playwright";

const browser = await chromium.launch({ executablePath: "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const response = await page.request.get("http://127.0.0.1:8000/api/v1/river/upstream-forecasts", { timeout: 60000 });
  assert.ok(response.ok());
  const payload = await response.json();
  const station = payload.stations[0];
  station.providers[0].series = [
    { time: "2026-10-01", value: 10, phase: "past" },
    { time: "2026-10-06", value: 20, phase: "forecast" },
    { time: "2026-10-11", value: 30, phase: "forecast" },
  ];
  station.providers[1].series = [
    { time: "2026-10-06T00:00:00", value: 15, phase: "forecast" },
    { time: "2026-10-11T00:00:00Z", value: 25, phase: "forecast" },
  ];
  await page.route("**/river/upstream-forecasts", (route) => route.fulfill({ json: payload }));
  await page.goto("http://127.0.0.1:3000/", { waitUntil: "domcontentloaded" });
  const navigation = page.locator(".sidebar nav");
  await page.locator(".overview-command-canvas").waitFor({ timeout: 60000 });
  assert.equal(await page.locator(".overview-command-canvas .source-forecast-tab, .overview-command-canvas .flood-multiview").count(), 0);
  await navigation.getByRole("button", { name: "Predictive Risk Views" }).click();
  await page.locator(".flood-risk-page").waitFor();
  assert.equal(await page.locator(".flood-risk-page .multiview-card").count(), 5);
  assert.equal(await page.locator(".flood-risk-page").evaluate((el) => getComputedStyle(el).position), "static");
  await page.screenshot({ path: "predictive-sidebar-desktop.png", fullPage: true });
  await navigation.getByRole("button", { name: "Upstream Source Flood Watch" }).click();
  const chart = page.locator(".source-chart-wrap");
  await chart.waitFor();
  assert.match(await chart.innerText(), /River discharge \(m3\/s\)/);
  assert.match(await chart.innerText(), /Date \(UTC\)/);
  assert.equal(await chart.locator(".source-chart-legend span").count(), 2);
  assert.equal(await chart.locator(".source-chart-dates span").count(), 5);
  const paths = await chart.locator("path").evaluateAll((els) => els.map((el) => el.getAttribute("d")));
  assert.match(paths[0], /^M 0\.0 .*L 380\.0 .*L 760\.0 /);
  assert.match(paths[1], /^M 380\.0 .*L 760\.0 /);
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await chart.scrollIntoViewIfNeeded();
    assert.ok(await chart.evaluate((el) => el.scrollWidth <= el.clientWidth));
    const ticks = await chart.locator(".source-chart-dates span").evaluateAll((els) => els.map((el) => { const r = el.getBoundingClientRect(); return { left: r.left, right: r.right }; }));
    for (let i = 1; i < ticks.length; i++) assert.ok(ticks[i].left >= ticks[i - 1].right, `Date labels overlap at ${width}px`);
    await chart.screenshot({ path: `chart-${width}.png` });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `Page overflow at ${width}px`);
    if (width === 390) {
      await page.locator(".mobile-menu").click();
      await navigation.getByRole("button", { name: "Predictive Risk Views" }).click();
      await page.locator(".flood-risk-page").waitFor();
      assert.equal(await page.locator(".sidebar").evaluate((el) => el.classList.contains("sidebar-open")), false);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "Mobile predictive page overflow");
      await page.screenshot({ path: "predictive-sidebar-mobile.png", fullPage: true });
      await page.locator(".mobile-menu").click();
      await navigation.getByRole("button", { name: "Overview", exact: true }).click();
      await page.locator(".overview-command-canvas").waitFor();
      assert.equal(await page.locator(".overview-command-canvas .source-forecast-tab, .overview-command-canvas .flood-multiview").count(), 0);
    }
  }
  console.log("Sidebar navigation, unobstructed Overview, both forecast views, chart alignment, and desktop/mobile layout passed");
} finally {
  await browser.close();
}
