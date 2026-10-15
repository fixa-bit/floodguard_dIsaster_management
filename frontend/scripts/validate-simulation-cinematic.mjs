import assert from "node:assert/strict";
import { mkdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const browser = await chromium.launch({ executablePath: process.env.EDGE_PATH ?? "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
const errors = [], writes = [];
let page;
try {
  await mkdir(new URL('../screenshots/', import.meta.url), { recursive: true });
  page = await browser.newPage({ viewport: { width: 1600, height: 1050 } });
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('request', (request) => { if (!["GET", "OPTIONS"].includes(request.method())) writes.push(request.url()); });
  await page.route('**/api/v1/**', (route) => new URL(route.request().url()).pathname.endsWith('/simulation/monitoring/stations')
    ? route.fulfill({ json: [{ code: "TAUNSA", name: "Taunsa", river: "Indus", thresholds: [] }] })
    : route.fulfill({ status: 503, json: { error: { code: "SCENE_CHECK", message: "Operational feeds excluded from scene check" } } }));
  await page.goto(process.env.FRONTEND_URL ?? 'http://127.0.0.1:3000/', { waitUntil: 'domcontentloaded' });
  await page.locator('.sidebar nav').getByRole('button', { name: 'Simulation', exact: true }).click();
  await page.getByRole('tab', { name: 'Flood spread & population', exact: true }).click();
  const root = page.locator('.simulation-flood-visualization');
  const maps = root.locator('.outlook-map-canvas');
  const scene = maps.nth(1);
  const slider = page.getByRole('slider', { name: 'Example flood level', exact: true });
  await root.locator('.outlook-map-canvas[data-ready="true"]').nth(1).waitFor({ timeout: 50000 });
  await page.getByRole('button', { name: /^Highest flood scenario/ }).click();
  await page.waitForFunction(() => document.querySelector('.outlook-exposure').dataset.exposureArea === 'jhang');
  const initialExposure = await root.locator('.outlook-exposure-impact').getAttribute('data-estimated-people');
  await page.getByRole('button', { name: 'Cinematic 3D', exact: true }).click();
  await page.waitForFunction(() => {
    const root = document.querySelector('.simulation-flood-visualization');
    const map = root?.querySelectorAll('.outlook-map-canvas')[1];
    return root?.dataset.scene === 'cinematic' && Number(map?.dataset.pitch) >= 50 && Number(map?.dataset.sceneRenderedColumns) > 0;
  }, undefined, { timeout: 30000 });
  assert.equal(await maps.count(), 2, 'Cinematic mode reuses the existing canvases');
  assert.equal(await root.locator('.outlook-map-pane').first().isVisible(), false);
  assert.equal(await root.locator('.outlook-exposure-impact').getAttribute('data-estimated-people'), initialExposure, 'Changing presentation cannot change exposure');
  assert.equal(await scene.getAttribute('data-scene-columns'), 'visible');
  assert.equal(await scene.getAttribute('data-scene-water'), 'visible');
  assert(Number(await scene.getAttribute('data-scene-exposed-cells')) > 0);
  assert.match(await root.locator('.simulation-cinematic-key').innerText(), /not terrain, buildings, or measured flood depth/);
  await page.waitForFunction(() => document.querySelectorAll('.simulation-flood-visualization .outlook-map-canvas')[1].dataset.moving !== 'true');
  await root.locator('.outlook-map-pane').nth(1).screenshot({ path: fileURLToPath(new URL('../screenshots/simulation-cinematic-overview.png', import.meta.url)) });
  await page.getByRole('button', { name: 'Orbit region', exact: true }).click();
  const startBearing = Number(await scene.getAttribute('data-bearing'));
  await page.waitForFunction((start) => Math.abs(Number(document.querySelectorAll('.simulation-flood-visualization .outlook-map-canvas')[1].dataset.bearing) - start) > 3, startBearing);
  await page.getByRole('button', { name: 'Pause camera', exact: true }).click();
  const pausedBearing = await scene.getAttribute('data-bearing');
  await page.waitForTimeout(650);
  assert.equal(await scene.getAttribute('data-bearing'), pausedBearing);
  await page.getByRole('button', { name: 'Fly to river', exact: true }).click();
  await page.waitForFunction(() => { const map = document.querySelectorAll('.simulation-flood-visualization .outlook-map-canvas')[1]; return Number(map.dataset.zoom) > 8 && Number(map.dataset.pitch) >= 60 && map.dataset.moving !== 'true'; });
  await root.locator('.outlook-map-pane').nth(1).screenshot({ path: fileURLToPath(new URL('../screenshots/simulation-cinematic-river.png', import.meta.url)) });
  await page.getByRole('button', { name: 'Population focus', exact: true }).click();
  await page.waitForFunction(() => { const map = document.querySelectorAll('.simulation-flood-visualization .outlook-map-canvas')[1]; return Number(map.dataset.zoom) >= 8.5 && map.dataset.moving !== 'true'; });
  const size = await scene.boundingBox();
  for (const offset of [-50, -100, -150, -200, 0, 40]) {
    await scene.locator('canvas').click({ position: { x: size.width / 2, y: size.height / 2 + offset } });
    try { await page.locator('.simulation-scene-popup-body').waitFor({ timeout: 500 }); break; } catch { /* Try another part of the raised glyph. */ }
  }
  assert.equal(await page.locator('.simulation-scene-popup-body').count(), 1, 'Raised population columns can be inspected');
  assert.match(await page.locator('.simulation-scene-popup-body').innerText(), /WorldPop 2025/);
  await page.getByRole('button', { name: 'Close popup', exact: true }).click();
  await slider.focus(); await slider.press('Home');
  await page.waitForFunction(() => { const map = document.querySelectorAll('.simulation-flood-visualization .outlook-map-canvas')[1]; return map.dataset.sceneExposedCells === '0' && map.dataset.sceneRenderedWater === '0'; });
  assert.equal(await page.getByTestId('outlook-exposed-population').innerText(), '0');
  await page.getByRole('button', { name: /^Highest flood scenario/ }).click();
  await page.getByRole('button', { name: 'Population map', exact: true }).click();
  assert.equal(await scene.getAttribute('data-scene-columns'), 'none');
  await page.getByRole('button', { name: 'Population map', exact: true }).click();
  await page.getByRole('button', { name: 'Flood spread', exact: true }).click();
  assert.equal(await scene.getAttribute('data-scene-water'), 'none');
  assert.equal(await scene.getAttribute('data-scene-exposed-cells'), '0');
  await page.getByRole('button', { name: 'Flood spread', exact: true }).click();
  await page.getByLabel('Simulation preview district').selectOption('lahore');
  const lahore = JSON.parse(await readFile(new URL('../src/data/outlook-exposure/lahore.geojson', import.meta.url), 'utf8'));
  await page.waitForFunction(({ expected }) => { const root = document.querySelector('.simulation-flood-visualization'); return root.querySelectorAll('.outlook-map-canvas')[1].dataset.sceneArea === 'lahore' && Number(root.querySelector('.outlook-exposure-impact')?.dataset.estimatedPeople) === expected; }, { expected: lahore.levels[5].exposed_population });
  await page.getByLabel('Simulation preview district').selectOption('badin');
  await page.getByText('Badin: population available; water spread unavailable.', { exact: true }).waitFor();
  assert.equal(await scene.getAttribute('data-scene-water'), 'none');
  assert.equal(await page.getByRole('button', { name: 'Fly to river', exact: true }).isDisabled(), true);
  assert.equal(await scene.getAttribute('data-scene-columns'), 'visible');
  await page.getByLabel('Simulation preview district').selectOption('jhang');
  await page.waitForFunction(() => document.querySelectorAll('.simulation-flood-visualization .outlook-map-canvas')[1].dataset.sceneArea === 'jhang');
  await page.getByRole('button', { name: 'Orbit region', exact: true }).click();
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.waitForFunction(() => document.querySelector('.simulation-flood-visualization').dataset.orbiting === 'false');
  assert.equal(await page.getByRole('button', { name: 'Orbit region', exact: true }).isDisabled(), true);
  await page.getByRole('button', { name: 'Population focus', exact: true }).click();
  assert(Number(await scene.getAttribute('data-zoom')) >= 8.5, 'Static camera presets remain usable under reduced motion');
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.getByRole('button', { name: 'Orbit region', exact: true }).click();
  await page.evaluate(() => { Object.defineProperty(document, 'hidden', { configurable: true, value: true }); document.dispatchEvent(new Event('visibilitychange')); });
  await page.waitForFunction(() => document.querySelector('.simulation-flood-visualization').dataset.orbiting === 'false');
  await page.evaluate(() => { delete document.hidden; document.dispatchEvent(new Event('visibilitychange')); });
  await page.getByRole('button', { name: 'Orbit region', exact: true }).click();
  await page.locator('.simulation-workspace-header').evaluate((element) => element.scrollIntoView({ block: 'start' }));
  await page.waitForFunction(() => document.querySelector('.simulation-flood-visualization').dataset.orbiting === 'false');
  await page.getByRole('button', { name: '2D comparison', exact: true }).click();
  await page.waitForFunction(() => [...document.querySelectorAll('.simulation-flood-visualization .outlook-map-canvas')].every((map) => Number(map.dataset.pitch) === 0 && Number(map.dataset.bearing) === 0 && map.dataset.moving !== 'true'));
  assert.equal(await root.locator('.outlook-map-pane').first().isVisible(), true);
  assert.equal(await maps.nth(0).getAttribute('data-center'), await maps.nth(1).getAttribute('data-center'));
  assert.equal(await maps.nth(0).getAttribute('data-zoom'), await maps.nth(1).getAttribute('data-zoom'));
  assert.equal(await root.locator('.outlook-exposure-impact').getAttribute('data-estimated-people'), initialExposure);
  await page.getByRole('button', { name: 'Cinematic 3D', exact: true }).click();
  await page.setViewportSize({ width: 1024, height: 768 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await root.locator('.outlook-map-pane').nth(1).screenshot({ path: fileURLToPath(new URL('../screenshots/simulation-cinematic-compact.png', import.meta.url)) });
  await page.getByRole('tab', { name: 'Monitoring scenario', exact: true }).click();
  assert.equal(await page.locator('.simulation-flood-visualization canvas').count(), 0);
  assert.deepEqual(errors, []);
  assert.deepEqual(writes, []);
  console.log('PASS: preserved 2D comparison; actual 3D extrusion rendering; shared estimates; camera orbit/pause/close-ups; column inspection; level and layer consistency; district/missing-data handling; reduced-motion, visibility, and offscreen cleanup; compact layout; reused canvases; zero runtime errors or backend writes.');
} catch (error) {
  if (page && !page.isClosed()) {
    await page.screenshot({ path: fileURLToPath(new URL('../screenshots/simulation-cinematic-failure.png', import.meta.url)), fullPage: true }).catch(() => {});
    console.error(await page.locator('.simulation-scene-message').allTextContents());
  }
  throw error;
} finally { await browser.close(); }
