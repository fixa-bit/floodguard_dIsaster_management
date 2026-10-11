import assert from "node:assert/strict";
import { mkdir, readFile } from "node:fs/promises";
import { chromium } from "playwright";
import { mapTestUrl } from "./map-test-url.mjs";

const loadGeometry = async (name) => JSON.parse(await readFile(new URL(`../src/data/pakistan/${name}.geojson`, import.meta.url), "utf8"));
const admin = await loadGeometry("pakistan_admin1");
const districts = await loadGeometry("pakistan_districts");
const vertices = (geometry) => geometry.type === "Polygon" ? geometry.coordinates.flat() : geometry.coordinates.flat(2);
const distanceToVertex = (coordinate, features) => Math.min(...features.flatMap((feature) => vertices(feature.geometry)
  .map((vertex) => Math.hypot(vertex[0] - coordinate[0], vertex[1] - coordinate[1]))));
const browser = await chromium.launch({
  executablePath: process.env.EDGE_PATH ?? "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true,
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
const diagnostics = () => page.locator(".national-map").evaluate((element) => ({ ...element.dataset }));

try {
  await mkdir("screenshots", { recursive: true });
  await page.goto(mapTestUrl(process.env.DASHBOARD_URL ?? "http://localhost:3000"), { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => Number(document.querySelector(".national-map")?.dataset.renderedBorderCheckpoints) === 3, null, { timeout: 90000 });
  const checkpoints = JSON.parse((await diagnostics()).borderCheckpoints);
  assert.equal(checkpoints.length, 3);
  for (const checkpoint of checkpoints) {
    assert.ok(distanceToVertex(checkpoint.coordinates, admin.features) < 1e-8, `${checkpoint.name}: point must lie on the built-in Pakistan/province boundary`);
    assert.ok(distanceToVertex(checkpoint.coordinates, districts.features.filter((feature) => feature.properties.district === checkpoint.district)) < 1e-8,
      `${checkpoint.name}: point must also lie on its district boundary`);
  }
  await page.screenshot({ path: "screenshots/border-alignment-desktop.png" });
  for (const checkpoint of checkpoints) {
    const revision = Number((await diagnostics()).borderRenderRevision);
    await page.getByRole("button", { name: `Inspect ${checkpoint.name} border checkpoint`, exact: true }).click();
    await page.waitForFunction((previous) => Number(document.querySelector(".national-map")?.dataset.borderRenderRevision) > previous,
      revision, { timeout: 60000 });
    const point = JSON.parse((await diagnostics()).borderCheckpoints).find((item) => item.number === checkpoint.number);
    const bounds = await page.locator(".national-map").boundingBox();
    await page.mouse.move(bounds.x + point.x, bounds.y + point.y);
    const coordinateText = `${checkpoint.number}. ${checkpoint.name} / ${checkpoint.district}: Latitude ${checkpoint.coordinates[1].toFixed(6)} N, Longitude ${checkpoint.coordinates[0].toFixed(6)} E`;
    await page.getByText(coordinateText, { exact: true }).waitFor();
    await page.mouse.move(bounds.x + 20, bounds.y + 20);
    await page.locator(".border-checkpoint-popup").waitFor({ state: "hidden" });
    await page.mouse.click(bounds.x + point.x, bounds.y + point.y);
    await page.getByText(`${checkpoint.number}. ${checkpoint.name} / ${checkpoint.district}:`, { exact: false }).waitFor();
    await page.screenshot({ path: `screenshots/border-alignment-${checkpoint.name.toLowerCase()}.png` });
    await page.locator(".maplibregl-popup-close-button").click();
  }
  const toggle = page.getByRole("checkbox", { name: "Boundary alignment test", exact: true });
  await toggle.uncheck();
  assert.equal((await diagnostics()).borderTestVisibility, "none");
  await toggle.check();
  assert.equal((await diagnostics()).borderTestVisibility, "visible");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForFunction(() => Number(document.querySelector(".national-map")?.dataset.renderedBorderCheckpoints) === 3, null, { timeout: 60000 });
  const mobilePoints = JSON.parse((await diagnostics()).borderCheckpoints);
  const horizontalSpan = Math.max(...mobilePoints.map((point) => point.x)) - Math.min(...mobilePoints.map((point) => point.x));
  assert.ok(horizontalSpan > 390 * 0.4, "Checkpoint navigation must not leave camera padding that shrinks the mobile overview");
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({ path: "screenshots/border-alignment-mobile.png" });
  assert.deepEqual(errors, []);
  console.log("PASS: 3 red checkpoints share Pakistan/province and district boundary vertices; coordinate hover, zoom, click popups, toggle and desktop/mobile rendering work.");
} catch (error) {
  console.log("Border alignment diagnostics:", await diagnostics(), errors);
  await page.screenshot({ path: "screenshots/border-alignment-failure.png" });
  throw error;
} finally {
  await browser.close();
}
