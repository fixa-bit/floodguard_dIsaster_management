import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const browser = await chromium.launch({ executablePath: process.env.EDGE_PATH ?? "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
const screenshots = new URL("../../.pytest_cache/", import.meta.url);
const screenshot = (name) => fileURLToPath(new URL(name, screenshots));
const errors = [];
async function setSlider(page, label, value) {
  const slider = page.getByRole("slider", { name: label, exact: true });
  if (await slider.isDisabled()) await page.getByRole("checkbox", { name: `Enable ${label}`, exact: true }).check();
  await slider.evaluate((element, next) => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(element, next);
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
  }, value);
  assert.equal(await slider.inputValue(), value);
}
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, timezoneId: "Asia/Karachi" });
  const apiBase = process.env.BACKEND_URL ?? "http://127.0.0.1:8001/api/v1";
  const initialAlerts = await (await page.request.get(`${apiBase}/alerts`)).json();
  const initialIncidents = await (await page.request.get(`${apiBase}/incidents`)).json();
  page.on("pageerror", (error) => errors.push(error.message));
  // Keep unrelated provider requests out of this database-backed workflow check.
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (/\/(simulation|alerts|incidents|events|dashboard|system)\b/.test(path)) return route.continue();
    return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: { code: "QA_PROVIDER", message: "Provider requests excluded from simulation check" } }) });
  });
  await page.goto(process.env.FRONTEND_URL ?? "http://127.0.0.1:3000/", { waitUntil: "domcontentloaded" });
  const nav = page.locator(".sidebar nav");
  await nav.getByRole("button", { name: "Simulation", exact: true }).click();
  await page.getByLabel("Station", { exact: true }).selectOption("TAUNSA");
  assert.equal(await page.getByRole("button", { name: "Play", exact: true }).isDisabled(), true);
  await page.getByLabel("Measurement", { exact: true }).selectOption("water_level");
  await page.getByLabel("Gauge datum / reference", { exact: true }).selectOption("custom");
  await page.getByLabel("Custom gauge datum / reference", { exact: true }).fill("QA gauge datum");
  assert.deepEqual(await page.getByLabel("Unit", { exact: true }).locator("option").allTextContents(), ["m", "ft"]);
  await page.getByLabel("Measurement", { exact: true }).selectOption("discharge_inflow");
  await page.getByRole("button", { name: "Custom test thresholds", exact: true }).click();
  await setSlider(page, "Warning (cusecs)", "600000");
  await setSlider(page, "Danger (cusecs)", "300000");
  await setSlider(page, "Reading 1 value", "650000");
  await page.getByRole("button", { name: "Play", exact: true }).click();
  await page.getByText("Danger threshold must exceed warning threshold.", { exact: true }).waitFor();
  await setSlider(page, "Warning (cusecs)", "300000");
  await setSlider(page, "Danger (cusecs)", "600000");
  await page.getByLabel("Testing profile").selectOption("danger");
  assert.equal(await page.locator(".simulation-readings tbody tr").count(), 3);
  await setSlider(page, "Reading 2 p25", "280000");
  await setSlider(page, "Reading 2 p75", "320000");
  await page.screenshot({ path: screenshot("simulation-entry-desktop.png"), fullPage: true });
  const responsePromise = page.waitForResponse((response) => response.url().endsWith("/simulation/monitoring/play") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Play", exact: true }).click();
  const response = await responsePromise;
  assert.equal(response.status(), 200);
  const played = await response.json();
  assert.equal(played.inserted, 3);
  assert.equal(played.alerts.length, 2);
  assert.equal(played.incidents.length, 0, "Incidents require alert approval");
  await page.getByRole("heading", { name: "Threshold reached", exact: true }).waitFor();
  assert.equal(await page.locator(".simulation-alert-banner").count(), 1);
  await page.screenshot({ path: screenshot("simulation-result-desktop.png"), fullPage: true });
  await page.getByRole("button", { name: "Review alerts (2)", exact: true }).click();
  await page.locator(".alerts-table tbody tr").first().waitFor();
  await page.getByRole("button", { name: "Operational", exact: true }).click();
  assert.equal(await page.locator(".alerts-table").count(), 0);
  await page.getByRole("button", { name: "Simulated flow", exact: true }).click();
  assert.equal(await page.locator(".alerts-table tbody tr").count(), initialAlerts.length + 2);
  await page.screenshot({ path: screenshot("simulation-alerts-desktop.png"), fullPage: true });
  await page.getByRole("button", { name: `Approve simulated alert ${played.alerts[0].id}`, exact: true }).click();
  await page.locator(".alert-incident-link").first().waitFor();
  await page.locator(".alert-incident-link").first().click();
  await page.getByRole("dialog").waitFor();
  assert.ok((await page.getByRole("dialog").innerText()).includes("SIMULATED FLOW"));
  assert.equal(await page.locator(".data-table tbody tr").count(), initialIncidents.length + 1);
  await page.screenshot({ path: screenshot("simulation-incidents-desktop.png"), fullPage: true });
  await page.reload({ waitUntil: "domcontentloaded" });
  await nav.getByRole("button", { name: "Alerts", exact: true }).click();
  await page.locator(".alerts-table tbody tr").first().waitFor();
  assert.equal(await page.locator(".alerts-table tbody tr").count(), initialAlerts.length + 2);
  assert.equal(await page.getByText("Approved", { exact: true }).count(), 1);
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Menu", exact: true }).click();
  await nav.getByRole("button", { name: "Simulation", exact: true }).click();
  await page.getByLabel("Station", { exact: true }).selectOption("TAUNSA");
  await page.getByRole("button", { name: "Custom test thresholds", exact: true }).click();
  await setSlider(page, "Warning (cusecs)", "300000");
  await setSlider(page, "Danger (cusecs)", "600000");
  await setSlider(page, "Reading 1 value", "100000");
  await page.screenshot({ path: screenshot("simulation-entry-mobile.png"), fullPage: true });
  const mobileLayout = await page.evaluate(() => ({
    width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
    overflow: [...document.querySelectorAll("body *")].filter((element) => element.getBoundingClientRect().right > innerWidth)
      .slice(0, 20).map((element) => ({ tag: element.tagName, class: element.className, right: element.getBoundingClientRect().right })),
  }));
  assert.ok(mobileLayout.scrollWidth <= mobileLayout.width, JSON.stringify(mobileLayout));
  await page.getByRole("button", { name: "Play", exact: true }).click();
  await page.getByRole("heading", { name: "Readings saved", exact: true }).waitFor();
  assert.equal(await page.locator(".simulation-alert-banner").count(), 0);
  await page.screenshot({ path: screenshot("simulation-result-mobile.png"), fullPage: true });

  await page.getByRole("button", { name: "New run", exact: true }).click();
  await setSlider(page, "Reading 1 value", "600000");
  let committed;
  await page.route("**/simulation/monitoring/play", async (route) => {
    committed = await (await route.fetch()).json();
    await route.abort("failed");
    await page.unroute("**/simulation/monitoring/play");
  }, { times: 1 });
  await page.getByRole("button", { name: "Play", exact: true }).click();
  await page.getByText("Cannot reach the FloodGuard backend", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Play", exact: true }).click();
  await page.getByRole("heading", { name: "Threshold reached", exact: true }).waitFor();
  const alerts = await (await page.request.get(`${apiBase}/alerts`)).json();
  assert.equal(alerts.filter((alert) => alert.event_metadata.run_id === committed.run_id).length, 1);
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.getByRole("button", { name: "Review alerts (1)", exact: true }).click();
  await page.locator(".alerts-table tbody tr").first().waitFor();
  await page.screenshot({ path: screenshot("simulation-alerts-mobile.png"), fullPage: true });
  const retryAlert = alerts.find((alert) => alert.event_metadata.run_id === committed.run_id);
  await page.getByRole("button", { name: `Approve simulated alert ${retryAlert.id}`, exact: true }).click();
  await page.locator(".alert-incident-link").first().waitFor();
  await page.locator(".alert-incident-link").first().click();
  await page.getByRole("dialog").waitFor();
  await page.screenshot({ path: screenshot("simulation-incidents-mobile.png"), fullPage: true });
  assert.deepEqual(errors, []);
  console.log("Simulation browser checks passed: saved thresholds, units and datum, custom input, profiles, boundary alerts, linked incidents, reload persistence, below-threshold run, interrupted-response retry, desktop/mobile layout.");
} finally {
  await browser.close();
}
