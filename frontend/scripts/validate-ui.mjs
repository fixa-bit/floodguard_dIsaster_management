import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { mapTestUrl } from "./map-test-url.mjs";

const appUrl = process.env.DASHBOARD_URL ?? "http://localhost:3000";
const edgePath = process.env.EDGE_PATH ?? "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const outputDir = new URL("../screenshots/", import.meta.url);
const screenshotPath = (name) => fileURLToPath(new URL(name, outputDir));
const browser = await chromium.launch({ executablePath: edgePath, headless: true });
const errors = [];

try {
  await mkdir(outputDir, { recursive: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });

  await page.goto(mapTestUrl(appUrl), { waitUntil: "networkidle", timeout: 120_000 });
  await page.getByRole("heading", { name: "Operational Overview" }).waitFor();
  await page.getByLabel("Operational location").selectOption("MUL_001");
  await page.locator(".location-select strong").getByText("Multan", { exact: true }).waitFor();
  await page.locator(".dashboard-loading").waitFor({ state: "hidden", timeout: 120_000 });
  await page.locator(".maplibregl-canvas").first().waitFor({ timeout: 120_000 });
  await page.getByText(/126 districts/).first().waitFor({ timeout: 120_000 });
  const renderedMap = page.locator(".national-map[data-source-features]").first();
  await renderedMap.waitFor({ timeout: 120_000 });
  const sourceFeatureCount = Number(await renderedMap.getAttribute("data-source-features"));
  const renderedFeatureCount = Number(await renderedMap.getAttribute("data-rendered-features"));
  if (sourceFeatureCount < 1 || renderedFeatureCount < 1) throw new Error(`District layer failed to render: source=${sourceFeatureCount}, rendered=${renderedFeatureCount}`);
  await page.screenshot({ path: screenshotPath("overview-desktop.png"), fullPage: true });

  const desktopOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  if (desktopOverflow) throw new Error("Desktop layout has horizontal overflow");

  await page.getByRole("button", { name: "GIS Operations" }).click();
  await page.getByRole("heading", { name: "GIS Operations" }).waitFor();
  const gisMap = page.locator('.national-map[data-rendered-features]:not([data-rendered-features="0"])');
  await gisMap.waitFor({ timeout: 120_000 });
  const mapBounds = await gisMap.boundingBox();
  if (!mapBounds || mapBounds.width < 500 || mapBounds.height < 400) throw new Error(`National GIS map is not correctly framed: ${JSON.stringify(mapBounds)}; console: ${errors.join(" | ")}`);
  await gisMap.click({ position: { x: Math.round(mapBounds.width * 0.5), y: Math.round(mapBounds.height * 0.5) } });
  await page.locator(".district-inspector").waitFor({ timeout: 10_000 });
  await page.screenshot({ path: screenshotPath("gis-operations-desktop.png"), fullPage: true });

  await page.getByRole("button", { name: "Simulation" }).click();
  await page.getByLabel("Scenario").selectOption("HEAVY_RAIN");
  await page.getByRole("button", { name: /Start/ }).click();
  await page.locator(".simulation-current strong").getByText("HEAVY RAIN", { exact: true }).waitFor({ timeout: 120_000 });
  await page.getByRole("button", { name: /Advance/ }).click();
  await page.getByRole("button", { name: /Reset/ }).click();
  await page.locator(".simulation-current strong").getByText("NORMAL", { exact: true }).waitFor({ timeout: 120_000 });

  await page.getByRole("button", { name: "Overview" }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('.national-map[data-rendered-features]:not([data-rendered-features="0"])').waitFor({ timeout: 120_000 });
  await page.waitForTimeout(300);
  await page.screenshot({ path: screenshotPath("overview-mobile.png"), fullPage: true });
  const mobileOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  if (mobileOverflow) throw new Error("Mobile layout has horizontal overflow");

  if (errors.length) throw new Error(`Browser console errors: ${errors.join(" | ")}`);
  console.log("UI validation passed: national GIS, live load, location switch, simulation lifecycle, responsive layout");
} finally {
  await browser.close();
}

