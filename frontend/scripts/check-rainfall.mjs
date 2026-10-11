import assert from "node:assert/strict";
import { mkdir, readFile } from "node:fs/promises";
import { chromium } from "playwright";
import { mapTestUrl } from "./map-test-url.mjs";

const browser = await chromium.launch({
  executablePath: process.env.EDGE_PATH ?? "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  headless: true,
});
const periods = ["Last 1 hour", "Last 3 hours", "Last 6 hours", "Last 24 hours", "Next 24 hours", "Next 72 hours"];
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const pageErrors = [];
const coverage = JSON.parse(await readFile(new URL("../../app/gis/data/rainfall_coverage.geojson", import.meta.url), "utf8"));
const upstreamPoints = [[74.8, 34.08], [77.58, 34.15], [69.17, 34.55], [77.19, 32.24], [78.72, 31.8], [79.7, 32.5]];
page.on("pageerror", (error) => pageErrors.push(error.message));

try {
  await mkdir("screenshots", { recursive: true });
  if (process.env.RAINFALL_LIVE !== "1") {
    await page.route("**/api/v1/gis/rainfall", (route) => route.fulfill({ json: {
      type: "FeatureCollection", coverage,
      features: [...upstreamPoints, [71.47, 30.15]].map((coordinates) => ({ type: "Feature", geometry: { type: "Point", coordinates },
        properties: { accumulations_mm: { last_1h: 10, last_3h: 25, last_6h: 40, last_24h: 60, next_24h: 80, next_72h: 100 } } })),
      metadata: { source: "Open-Meteo model precipitation", generated_at: new Date().toISOString(), cache_status: "fresh", missing_samples: 0, warning: null },
    } }));
    // Keep render checks independent of provider availability; operational feeds are unchanged.
    await page.route("**/api/v1/weather/current?*", (route) => route.fulfill({ json: {
      location_id: new URL(route.request().url()).searchParams.get("location_id"),
      location_name: "Rainfall test station", timestamp: new Date().toISOString(), source: "simulation", scenario: "NORMAL",
      rainfall_current_mm: 1, rainfall_last_1h_mm: 1, rainfall_last_6h_mm: 6, rainfall_last_24h_mm: 24,
      forecast_rainfall_next_6h_mm: 8, forecast_rainfall_next_24h_mm: 30,
      temperature_c: 25, humidity_percent: 80, soil_moisture_percent: 30,
    } }));
  }
  await page.goto(mapTestUrl(process.env.DASHBOARD_URL ?? "http://localhost:3000"), { waitUntil: "domcontentloaded" });
  const rasterChecks = await page.evaluate(async ({ coverage, upstreamPoints }) => {
    const [{ renderRainfallRaster, rainfallImageCoordinates }, { MercatorCoordinate }, { default: rawBoundaries }] = await Promise.all([
      import("/src/components/rainfallRaster.ts"),
      import("/node_modules/.vite/deps/maplibre-gl.js"),
      import("/src/data/pakistan/pakistan_admin1.geojson?raw"),
    ]);
    const boundaries = JSON.parse(rawBoundaries);
    const alphaAt = async (raster, longitude, latitude) => {
      const image = new Image();
      image.src = raster.imageUrl;
      await image.decode();
      const canvas = document.createElement("canvas");
      canvas.width = image.width;
      canvas.height = image.height;
      const context = canvas.getContext("2d");
      context.drawImage(image, 0, 0);
      const topLeft = MercatorCoordinate.fromLngLat(rainfallImageCoordinates[0]);
      const bottomRight = MercatorCoordinate.fromLngLat(rainfallImageCoordinates[2]);
      const point = MercatorCoordinate.fromLngLat([longitude, latitude]);
      const x = Math.floor((point.x - topLeft.x) / (bottomRight.x - topLeft.x) * image.width);
      const y = Math.floor((point.y - topLeft.y) / (bottomRight.y - topLeft.y) * image.height);
      return context.getImageData(x, y, 1, 1).data[3];
    };
    const anchor = (longitude, latitude, value) => ({ longitude, latitude, value, weight: 1 });
    const heavy = renderRainfallRaster([anchor(71.47, 30.15, 100), anchor(69.17, 34.55, 100), anchor(77.23, 28.61, 100)], boundaries);
    const light = renderRainfallRaster([anchor(71.47, 30.15, 0.1)], boundaries);
    const local = renderRainfallRaster([anchor(71.47, 30.15, 100)], boundaries);
    const regional = renderRainfallRaster([...upstreamPoints.map(([lon, lat]) => anchor(lon, lat, 100)), anchor(77.23, 28.61, 100)], coverage);
    const hole = renderRainfallRaster([anchor(71.47, 30.15, 100)], {
      type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [
        [[69, 28], [74, 28], [74, 33], [69, 33], [69, 28]],
        [[70, 29], [72, 29], [72, 31], [70, 31], [70, 29]],
      ] } }],
    });
    return {
      kabul: await alphaAt(heavy, 69.17, 34.55), delhi: await alphaAt(heavy, 77.23, 28.61),
      multan: await alphaAt(heavy, 71.47, 30.15), light: await alphaAt(light, 71.47, 30.15),
      unsupported: await alphaAt(local, 66.99, 30.18), hole: await alphaAt(hole, 71.47, 30.15),
      empty: renderRainfallRaster([], boundaries).cellCount,
      upstream: await Promise.all(upstreamPoints.map(([lon, lat]) => alphaAt(regional, lon, lat))),
      unrelated: await alphaAt(regional, 77.23, 28.61),
    };
  }, { coverage, upstreamPoints });
  assert.ok(rasterChecks.upstream.every((alpha) => alpha > 150), `Upstream rainfall missing: ${rasterChecks.upstream}`);
  assert.equal(rasterChecks.unrelated, 0, "Rainfall leaks into an unrelated basin");
  assert.equal(rasterChecks.kabul, 0, "Rainfall leaks outside Pakistan into Afghanistan");
  assert.equal(rasterChecks.delhi, 0, "Rainfall leaks outside Pakistan into India");
  assert.ok(rasterChecks.multan > 200, "Heavy rainfall should be visible within Pakistan");
  assert.ok(rasterChecks.light > 0 && rasterChecks.light < 25, "Light rain should not become an opaque green sheet");
  assert.equal(rasterChecks.unsupported, 0, "Rainfall extrapolates beyond nearby observations");
  assert.equal(rasterChecks.hole, 0, "Boundary polygon holes are filled");
  assert.equal(rasterChecks.empty, 0);
  console.log("PASS: country mask, polygon holes, light-rain transparency, local coverage, and empty-data handling.");
  const toggle = page.getByRole("checkbox", { name: "Rainfall heatmap", exact: true });
  await toggle.waitFor({ timeout: 60000 });
  await page.waitForFunction(() => document.querySelector(".national-map")?.dataset.rainfallVisibility === "none", null, { timeout: 60000 });
  await page.waitForFunction(() => Number(document.querySelector(".national-map")?.dataset.rainfallCells) > 0, null, { timeout: 60000 });
  assert.equal(await toggle.isChecked(), false, "Background raster preparation must not enable rainfall");
  console.log("PASS: rainfall raster is prepared in the background while its layer remains off.");
  const before = await page.locator(".maplibregl-canvas").screenshot();
  await page.getByRole("button", { name: "Last 6 hours", exact: true }).click();
  assert.equal(await toggle.isChecked(), true);
  console.log("Rainfall control enabled; checking map source.");
  await page.waitForFunction(() => {
    const data = document.querySelector(".national-map")?.dataset;
    return data?.rainfallVisibility === "visible" && data.rainfallReady === "true" && Number(data.rainfallCells) > 0;
  }, null, { timeout: 60000 });
  const after = await page.locator(".maplibregl-canvas").screenshot();
  const changedPixels = await page.evaluate(async ([beforePng, afterPng]) => {
    const readPixels = async (png) => {
      const image = new Image();
      image.src = `data:image/png;base64,${png}`;
      await image.decode();
      const canvas = document.createElement("canvas");
      canvas.width = image.width;
      canvas.height = image.height;
      const context = canvas.getContext("2d");
      context.drawImage(image, 0, 0);
      return context.getImageData(0, 0, image.width, image.height).data;
    };
    const previous = await readPixels(beforePng);
    const current = await readPixels(afterPng);
    let count = 0;
    for (let i = 0; i < current.length; i += 4) {
      if (Math.abs(current[i] - previous[i]) + Math.abs(current[i + 1] - previous[i + 1]) + Math.abs(current[i + 2] - previous[i + 2]) > 50) count++;
    }
    return count;
  }, [before.toString("base64"), after.toString("base64")]);
  assert.ok(changedPixels > 1000, `Rainfall did not visibly render: ${changedPixels} changed pixels`);
  await page.screenshot({ path: "screenshots/rainfall-fixed-desktop.png" });
  console.log(`Rainfall visibly rendered: ${changedPixels} changed pixels.`);

  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    const mapLayers = page.getByRole("button", { name: "Toggle map layers", exact: true });
    await page.waitForTimeout(250);
    if (await mapLayers.getAttribute("aria-expanded") === "false") await mapLayers.click();
    if (width === 390) {
      const header = await page.locator(".topbar").boundingBox();
      const stats = await page.locator(".overview-map-hud").boundingBox();
      assert.ok(header.y + header.height <= stats.y, "Mobile header overlaps statistics");
    }
    for (const period of periods) {
      if (await mapLayers.getAttribute("aria-expanded") === "false") await mapLayers.click();
      await toggle.uncheck();
      const button = page.getByRole("button", { name: period, exact: true });
      await button.click();
      assert.equal(await toggle.isChecked(), true, `${width}px: ${period} failed to enable rainfall`);
      assert.equal(await button.getAttribute("aria-pressed"), "true");
      await page.waitForFunction(() => document.querySelector(".national-map")?.dataset.rainfallVisibility === "visible", null, { timeout: 60000 });
      assert.ok(await page.locator(".map-legend").getByText(`Rainfall / ${period}`, { exact: true }).isVisible());
    }
    if (await mapLayers.getAttribute("aria-expanded") === "false") await mapLayers.click();
    await toggle.scrollIntoViewIfNeeded();
    assert.equal(await toggle.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      return document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2) === element;
    }), true, `${width}px: rainfall toggle is covered`);
    const controls = await page.locator(".map-layer-control").boundingBox();
    const legend = await page.locator(".map-legend").boundingBox();
    assert.ok(controls.y + controls.height <= legend.y, `${width}px: legend overlaps controls`);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  }
  await page.screenshot({ path: "screenshots/rainfall-fixed-mobile.png" });
  await page.getByRole("button", { name: "Menu", exact: true }).click();
  await page.getByRole("button", { name: "Rainfall heatmap", exact: true }).click();
  await page.getByRole("heading", { name: "Rainfall Heatmap", exact: true }).waitFor();
  const mapLayers = page.getByRole("button", { name: "Toggle map layers", exact: true });
  if (await mapLayers.getAttribute("aria-expanded") === "false") await mapLayers.click();
  await toggle.waitFor();
  assert.equal(await toggle.isChecked(), true);
  assert.deepEqual(pageErrors, []);
  console.log(`PASS (${process.env.RAINFALL_LIVE === "1" ? "live data" : "weather fixtures"}): ${changedPixels} changed map pixels; all six periods enable rainfall; controls are uncovered on desktop/mobile; sidebar view enables rainfall.`);
} catch (error) {
  console.log("Map diagnostics:", await page.locator(".national-map").evaluate((element) => ({ ...element.dataset })), "page errors:", pageErrors);
  await page.screenshot({ path: "screenshots/rainfall-failure.png" });
  throw error;
} finally {
  await browser.close();
}
