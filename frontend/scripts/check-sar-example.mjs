import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";

const browser = await chromium.launch({
  executablePath: process.env.EDGE_PATH ?? "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  headless: true,
});
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  let liveRequests = 0;
  page.on("request", request => { if (request.url().includes("/water-extent/location")) liveRequests++; });
  const appUrl = new URL(process.env.DASHBOARD_URL ?? "http://localhost:3000");
  appUrl.searchParams.set("mapDiagnostics", "1");
  await page.goto(appUrl.href, { waitUntil: "domcontentloaded" });
  const control = page.locator(".sar-water-control").first();
  await control.locator("summary").first().click({ timeout: 60000 });
  if (await page.getByLabel("Satellite analysis location").inputValue() !== "historical") {
    throw new Error("The historical example must be the default selection");
  }
  await page.getByRole("button", { name: "View flood example", exact: true }).click();
  await page.getByText("HISTORICAL EXAMPLE · NOT LIVE", { exact: true }).waitFor();
  await page.getByText("Potential flooding detected", { exact: true }).waitFor();
  const value = await page.locator(".sar-area-highlight b").innerText();
  if (!Number.isFinite(parseFloat(value)) || parseFloat(value) <= 0) throw new Error(`Unexpected historical example area: ${value}`);
  if (liveRequests) throw new Error("Historical example unexpectedly requested live imagery");
  await page.locator(".sar-area-highlight").scrollIntoViewIfNeeded();
  await page.locator('.national-map[data-sar-overlay-ready="true"]').first().waitFor({ timeout: 60000 });
  await mkdir(new URL("../screenshots/", import.meta.url), { recursive: true });
  await page.screenshot({ path: new URL("../screenshots/sar-historical-example.png", import.meta.url).pathname.replace(/^\/(\w:)/, "$1"), fullPage: true });
  await page.getByRole("button", { name: "Compare imagery, labels & accuracy" }).click();
  const dialog = page.getByRole("dialog", { name: "Compare prediction with event evidence" });
  await dialog.waitFor();
  for (const title of ["Event radar imagery", "Predicted water", "Reference water labels", "Correct detections & errors", "Permanent-water reference"]) {
    await dialog.getByText(title, { exact: true }).waitFor();
  }
  await page.waitForFunction(() => [...document.querySelectorAll(".sar-validation-image img")].every(image => image.complete && image.naturalWidth === 512));
  await page.screenshot({ path: new URL("../screenshots/sar-validation-desktop.png", import.meta.url).pathname.replace(/^\/(\w:)/, "$1"), fullPage: true });
  await page.getByRole("button", { name: "Close satellite validation" }).click();
  await page.getByLabel("Satellite result layer").selectOption("errors");
  await page.getByText(/Pink: missed water/).first().waitFor();
  await page.getByLabel("Satellite analysis location").selectOption("permanent");
  const sampleResponse = page.waitForResponse(response => response.url().includes("sar-pakistan-permanent.json"));
  await page.getByRole("button", { name: "View flood example", exact: true }).click();
  const permanentSample = await (await sampleResponse).json();
  if (permanentSample.permanent_water_reference_pixels <= 0) throw new Error("Second example must show permanent water");
  await page.getByRole("button", { name: "Compare imagery, labels & accuracy" }).click();
  await dialog.waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  const overflow = await dialog.evaluate(element => element.scrollWidth > element.clientWidth + 1);
  if (overflow) throw new Error("Validation dialog has horizontal overflow on mobile");
  await page.getByRole("button", { name: "Close satellite validation" }).click();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByLabel("Satellite analysis location").selectOption("map");
  await page.getByRole("button", { name: "Select place on map", exact: true }).waitFor();
  console.log("Passed: rendered overlay, event-matched comparison panels, reference and error layers, permanent-water example, mobile layout, no live imagery request, manual selection available.");
} finally {
  await browser.close();
}
