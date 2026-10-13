import assert from "node:assert/strict";
import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";

const browser = await chromium.launch({ executablePath: process.env.EDGE_PATH ?? "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, timezoneId: "Asia/Karachi" });
  const errors = [];
  const submissions = [];
  let rejectNext = false;
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/simulation/monitoring/stations")) return route.fulfill({ json: [{ code: "TAUNSA", name: "Taunsa", river: "Indus", thresholds: [
      { measurement: "water_level", unit: "m", level: "warning", value: 4.5, level_reference: "Station gauge datum", source_reference: null },
      { measurement: "water_level", unit: "m", level: "danger", value: 6.75, level_reference: "Station gauge datum", source_reference: null },
    ] }] });
    if (path.endsWith("/simulation/monitoring/play")) {
      const payload = route.request().postDataJSON();
      submissions.push(payload);
      if (rejectNext) { rejectNext = false; return route.fulfill({ status: 503, json: { error: { code: "TEST_RETRY", message: "Retry this test run" } } }); }
      return route.fulfill({ json: { run_id: payload.run_id, name: payload.name, station: payload.station, station_name: "Taunsa", provider: "SIMULATED_FLOW_TEST", value_type: "simulated", inserted: payload.readings.length, readings: [], alerts: [], incidents: [] } });
    }
    return route.fulfill({ status: 503, json: { error: { code: "TEST_FEEDS", message: "Feeds excluded from isolated form check" } } });
  });
  const slider = (label) => page.getByRole("slider", { name: label, exact: true });
  const setSlider = async (label, value) => {
    if (await slider(label).isDisabled()) await page.getByRole("checkbox", { name: `Enable ${label}`, exact: true }).check();
    await slider(label).evaluate((element, next) => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(element, String(next));
      element.dispatchEvent(new Event("input", { bubbles: true }));
      element.dispatchEvent(new Event("change", { bubbles: true }));
    }, value);
    assert.equal(Number(await slider(label).inputValue()), value);
  };
  const select = (label, value) => page.getByRole("combobox", { name: label, exact: true }).selectOption(value);
  const play = () => page.getByRole("button", { name: "Play", exact: true }).click();
  await page.goto(process.env.FRONTEND_URL ?? "http://127.0.0.1:3000/", { waitUntil: "domcontentloaded" });
  await page.locator(".sidebar nav").getByRole("button", { name: "Simulation", exact: true }).click();
  await page.getByRole("combobox", { name: "Station", exact: true }).waitFor();
  assert.equal(await page.locator('.simulation-workspace input[type="number"]').count(), 0);
  assert.equal(await page.getByRole("button", { name: "Play", exact: true }).isDisabled(), true);
  await select("Scenario name", "Danger crossing test");
  await select("Reading start (local time)", "custom");
  await page.getByLabel("Custom reading start", { exact: true }).fill("2026-10-13T10:30");
  await select("Measurement", "water_level");
  assert.equal(await page.getByLabel("Gauge datum / reference", { exact: true }).inputValue(), "Station gauge datum");
  await page.getByRole("button", { name: "Custom test thresholds", exact: true }).click();
  assert.equal(await slider("Danger (m)").inputValue(), "6.75");
  await page.getByRole("button", { name: "Increase Reading 1 value", exact: true }).click();
  assert.equal(await slider("Reading 1 value").inputValue(), "0.1");
  await setSlider("Reading 1 value", -2.125);
  await play();
  await page.getByRole("heading", { name: "Readings saved", exact: true }).waitFor();
  assert.equal(submissions[0].readings[0].value, -2.125);
  assert.equal(submissions[0].level_reference, "Station gauge datum");
  assert.equal(submissions[0].start_at, "2026-10-13T05:30:00.000Z");
  await page.getByRole("button", { name: "New run", exact: true }).click();
  await select("Measurement", "discharge_inflow");
  assert.equal(await slider("Reading 1 value").inputValue(), "0");
  await setSlider("Warning (cusecs)", 600000);
  await setSlider("Danger (cusecs)", 300000);
  await play();
  await page.getByText("Danger threshold must exceed warning threshold.", { exact: true }).waitFor();
  await setSlider("Warning (cusecs)", 300000);
  await setSlider("Danger (cusecs)", 600000);
  await select("Testing profile", "danger");
  assert.equal(await page.getByLabel("Testing profile").inputValue(), "danger");
  assert.equal(await page.locator(".simulation-readings tbody tr").count(), 3);
  await setSlider("Reading 2 p25", 400000);
  await setSlider("Reading 2 p75", 320000);
  await play();
  await page.getByText("The lower band (p25) must not exceed the upper band (p75).", { exact: true }).waitFor();
  await setSlider("Reading 2 p25", 280000);
  await setSlider("Reading 2 offset minutes", 0);
  await play();
  await page.getByText("Reading offsets must be unique and increase with each row.", { exact: true }).waitFor();
  await setSlider("Reading 2 offset minutes", 60);
  await select("Slider range", "5");
  assert.equal(await slider("Reading 1 value").getAttribute("max"), "5000000");
  await select("Reading window", "525600");
  assert.equal(await slider("Reading 1 offset minutes").getAttribute("max"), "525600");
  await mkdir("screenshots", { recursive: true });
  await page.screenshot({ path: "screenshots/simulation-sliders-desktop.png", fullPage: true });
  rejectNext = true;
  await play();
  await page.getByText("Retry this test run", { exact: true }).waitFor();
  await play();
  await page.getByRole("heading", { name: "Readings saved", exact: true }).waitFor();
  assert.deepEqual(submissions[1], submissions[2], "Retry must retain the exact payload and run ID");
  assert.deepEqual(submissions[2].readings, [
    { offset_minutes: 0, value: 240000, p25: null, p75: null },
    { offset_minutes: 60, value: 300000, p25: 280000, p75: 320000 },
    { offset_minutes: 120, value: 600000, p25: null, p75: null },
  ]);
  await page.getByRole("button", { name: "New run", exact: true }).click();
  await page.getByRole("checkbox", { name: "Enable Danger (cusecs)", exact: true }).uncheck();
  assert.equal(await slider("Danger (cusecs)").isDisabled(), true);
  await play();
  await page.getByRole("heading", { name: "Readings saved", exact: true }).waitFor();
  assert.equal(submissions[3].danger_threshold, null);
  assert.equal(submissions[3].warning_threshold, 300000);
  assert.deepEqual(errors, []);
  console.log("PASS: Desktop selectors, sliders, fine adjustments, negative/decimal levels, unit reset, optional limits/bands, profiles, range controls, validation, submitted values and retry IDs. Backend requests isolated; no database writes.");
} finally {
  await browser.close();
}
