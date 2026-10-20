import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { chromium } from "playwright";

const origin = process.env.DASHBOARD_URL ?? "http://127.0.0.1:3000";
const backend = process.env.API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";
const packaged = JSON.parse(await readFile(new URL("../public/data/marala-monthly.json", import.meta.url), "utf8"));
const measured = packaged.recent_history.daily;
const monthlyMeasured = packaged.recent_history.monthly.filter(row => row.flow_mean_cumecs !== null);
const issueDate = Date.parse(packaged.current_provider_outlook.forecast_issue_start);
const dailyForecastCount = packaged.current_provider_outlook.daily_forecast.filter(row => Date.parse(row.date) >= issueDate && row.date <= packaged.current_provider_outlook.forecast_available_through).length;
const segmentCount = measured.filter((row, index) => index === 0 || Date.parse(row.date) - Date.parse(measured[index - 1].date) !== 86_400_000).length;
const browser = await chromium.launch({
  executablePath: process.env.EDGE_PATH ?? "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  headless: true,
});
try {
  // Preview's port may be outside the backend's configured CORS origins.
  const modes = process.env.MARALA_FALLBACK_ONLY === "1" ? [true] : [false, true];
  for (const fallback of modes) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const requests = [];
    page.on("response", response => {
      if (response.url().includes("/data/marala-monthly.json") || response.url() === `${backend}/predictive/marala-monthly`) {
        requests.push({ url: response.url(), status: response.status() });
      }
    });
    if (fallback) await page.route(`${backend}/predictive/marala-monthly`, route => route.fulfill({ status: 404, json: { detail: "Not Found" } }));
    await page.goto(origin);
    await page.getByRole("button", { name: "Predictive Risk Views", exact: true }).click();
    const card = page.locator(".multiview-card").filter({ has: page.getByRole("tab", { name: "Monthly Marala", exact: true }) });
    const before = await card.boundingBox();
    await card.getByRole("tab", { name: "Monthly Marala", exact: true }).click();
    await card.getByRole("heading", { name: "Marala discharge prediction", exact: true }).waitFor();
    assert.equal(await card.locator(".marala-monthly-details").count(), 0, "Details must be hidden initially");
    assert.equal(await card.getByRole("tab", { name: "Daily", exact: true }).getAttribute("aria-selected"), "true");
    assert.equal(await card.locator(".marala-resolution-tabs").getByRole("tab").count(), 2);
    assert.equal(await card.locator(".marala-hydrograph").getByRole("button").count(), 0, "Only the two resolution tabs should be offered");
    assert.equal(await card.locator(".marala-hydrograph").getAttribute("data-history-start"), packaged.recent_history.period_start);
    assert.equal(await card.locator(".marala-hydrograph").getAttribute("data-history-end"), packaged.recent_history.period_end);
    assert.equal(await card.locator(".marala-hydrograph").getAttribute("data-max-months"), "7");
    assert.equal(await card.locator(".marala-history-point").count(), measured.length);
    assert.equal(await card.locator(".marala-highest-line").count(), 1);
    if (!fallback && process.env.MARALA_SCREENSHOT) await card.screenshot({ path: process.env.MARALA_SCREENSHOT });
    assert.equal(await card.locator(".marala-forecast-point").count(), dailyForecastCount);
    await card.locator(".marala-forecast-point").first().focus();
    assert.match(await card.locator(".marala-hydrograph-tooltip").textContent(), /Forecast mean/);
    assert.equal(await card.locator(".marala-prediction-chart .marala-forecast-point").count(), dailyForecastCount);
    assert.equal(await card.locator(".marala-prediction-chart .marala-history-point").count(), measured.length);
    const positions = await card.locator(".marala-history-point").evaluateAll(nodes => nodes.map(node => Number(node.getAttribute("cx"))));
    const firstTime = Date.parse(measured[0].observed_at);
    const lastTime = Date.parse(measured.at(-1).observed_at);
    for (let index = 0; index < measured.length; index++) {
      const fraction = (Date.parse(measured[index].observed_at) - firstTime) / (lastTime - firstTime);
      const expected = positions[0] + fraction * (positions.at(-1) - positions[0]);
      assert.ok(Math.abs(positions[index] - expected) < 0.001, "Measured x positions must follow actual dates, not point index");
    }
    assert.match(await card.locator(".marala-chart-legend").innerText(), /Observed.*06:00 PKT/);
    assert.match(await card.locator(".marala-chart-legend").innerText(), /Forecast.*daily mean/);
    assert.match(await card.locator(".marala-prediction-chart").innerText(), /Discharge/);
    const historyPoint = card.locator(".marala-history-point").first();
    await historyPoint.focus();
    assert.equal(await card.locator(".marala-chart-point-value").textContent(), await historyPoint.getAttribute("aria-label"));
    assert.equal(await card.locator(".marala-history-line").count(), segmentCount, "Missing days must break the measured line");
    assert.equal(await card.locator(".marala-forecast-line").count(), 1);
    const after = await card.boundingBox();
    assert.ok(Math.abs(before.width - after.width) < 1, "Monthly selection must retain Riverine card width");
    assert.equal(await card.evaluate(el => getComputedStyle(el).gridColumn), "auto");
    await card.getByRole("tab", { name: "Monthly averages", exact: true }).click();
    assert.equal(await card.locator(".marala-hydrograph").getAttribute("data-mode"), "monthly");
    assert.equal(await card.locator(".marala-hydrograph").getAttribute("data-max-months"), String(packaged.current_provider_outlook.forecast.length));
    assert.equal(await card.locator(".marala-history-point").count(), monthlyMeasured.length);
    assert.equal(await card.locator(".marala-forecast-point").count(), packaged.current_provider_outlook.forecast.length);
    assert.match(await card.locator(".marala-chart-legend").innerText(), /Observed.*monthly average/);
    assert.match(await card.locator(".marala-chart-legend").innerText(), /Forecast.*monthly average/);
    await card.locator(".marala-history-point").first().focus();
    assert.match(await card.locator(".marala-chart-point-value").textContent(), /days; partial/);
    await card.getByRole("tab", { name: "Daily", exact: true }).click();
    assert.equal(await card.locator(".marala-hydrograph").getAttribute("data-mode"), "daily");
    await card.getByRole("button", { name: "View details", exact: true }).click();
    await card.getByText("264 rows", { exact: true }).waitFor();
    await card.getByText("Browse monthly input dataset", { exact: true }).click();
    assert.equal(await card.locator(".marala-dataset-details tbody tr").count(), 264);
    const [download] = await Promise.all([page.waitForEvent("download"), card.getByRole("link", { name: "Download CSV" }).click()]);
    assert.equal(download.suggestedFilename(), "marala-monthly-dataset.csv");
    const stream = await download.createReadStream();
    let csv = "";
    for await (const chunk of stream) csv += chunk.toString();
    assert.equal(csv.trim().split(/\r?\n/).length, 265);
    assert.equal(await card.getByText(/Showing packaged dataset/).count(), fallback ? 1 : 0);
    assert.equal(requests.some(r => r.url.includes("/data/marala-monthly.json") && r.status === 200), fallback);
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, "Mobile dashboard must not overflow");
    await card.getByRole("button", { name: "Hide details", exact: true }).click();
    assert.equal(await card.locator(".marala-monthly-details").count(), 0);
    console.log(JSON.stringify({ mode: fallback ? "packaged fallback" : "live API", rows: 264, csvRows: 264, cardWidth: after.width, requests }));
    await page.close();
  }
} finally {
  await browser.close();
}
