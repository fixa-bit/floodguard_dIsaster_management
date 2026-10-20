import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { chromium } from "playwright";

const browser=await chromium.launch({executablePath:process.env.EDGE_PATH ?? "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",headless:true});
let page;
try{
  page=await browser.newPage({viewport:{width:1680,height:1100},reducedMotion:"reduce"});
  page.setDefaultTimeout(120000);
  const errors=[],terrainRequests=[],failedTerrain=[];
  page.on("pageerror",e=>errors.push(e.message));
  page.on("request",r=>{if(r.url().includes("/station-terrain/"))terrainRequests.push(r.url());});
  page.on("requestfailed",r=>{if(r.url().includes("elevation-tiles-prod"))failedTerrain.push(r.url());});
  await page.route("**/api/v1/**",route=>route.fulfill({status:503,json:{error:{message:"Offline terrain visualization check"}}}));
  if(process.env.LIVE_IMAGERY!=="1")await page.route("**/World_Imagery/MapServer/tile/**",route=>route.abort());
  if(process.env.LIVE_IMAGERY!=="1")await page.route("**/elevation-tiles-prod.s3.amazonaws.com/**",route=>route.abort());
  await page.goto(process.env.FRONTEND_URL ?? "http://127.0.0.1:3000/",{waitUntil:"domcontentloaded"});
  console.log("Opened dashboard");
  await page.locator(".sidebar nav").getByRole("button",{name:"GIS Operations",exact:true}).click({noWaitAfter:true});
  console.log("Opened GIS");
  const studio=page.getByRole("region",{name:"Station terrain studio"});
  await studio.getByRole("button",{name:"Bird’s-eye",exact:true}).waitFor();
  await page.waitForFunction(()=>!document.querySelector(".station-terrain-modes button")?.disabled);
  await studio.getByRole("button",{name:"Bird’s-eye",exact:true}).click();
  console.log("Selected bird's-eye");
  await page.waitForFunction(()=>document.querySelector(".national-map")?.dataset.stationTerrain==="true" && Number(document.querySelector(".national-map")?.dataset.terrainPitch)>50);
  await page.waitForFunction(()=>document.querySelector(".national-map")?.dataset.terrainLoaded==="true" && /~4\d\d m elevation/.test(document.querySelector(".station-terrain-readouts")?.textContent ?? ""));
  console.log("DEM rendered");
  assert(terrainRequests.some(url=>url.endsWith(".png")),"3D should use actual cached elevation tiles");
  assert.equal(await studio.getByRole("button",{name:"Bird’s-eye",exact:true}).getAttribute("aria-pressed"),"true");
  assert.equal(await page.locator(".national-map").getAttribute("data-terrain-station"),"TARBELA");
  await mkdir("screenshots",{recursive:true});
  await page.locator(".map-workspace").screenshot({path:"screenshots/station-terrain-tarbela.png"});
  await studio.getByRole("button",{name:/^Mangla/}).click();
  await page.waitForFunction(()=>document.querySelector(".national-map")?.dataset.terrainStation==="MANGLA");
  await page.waitForFunction(()=>document.querySelector(".national-map")?.dataset.terrainLoaded==="true" && /~3\d\d m elevation/.test(document.querySelector(".station-terrain-readouts")?.textContent ?? ""));
  await page.locator(".map-workspace").screenshot({path:"screenshots/station-terrain-mangla.png"});
  await studio.getByRole("slider",{name:"Terrain visual exaggeration"}).fill("1.6");
  await page.waitForFunction(()=>document.querySelector(".national-map")?.dataset.terrainExaggeration==="1.6");
  await studio.getByRole("button",{name:"Face north",exact:true}).click();
  await page.waitForFunction(()=>Math.abs(Number(document.querySelector(".national-map")?.dataset.terrainBearing))<1);
  await studio.getByRole("button",{name:"Return to flat map",exact:true}).click();
  await page.waitForFunction(()=>document.querySelector(".national-map")?.dataset.stationTerrain==="false" && Number(document.querySelector(".national-map")?.dataset.terrainPitch)===0);
  await page.setViewportSize({width:560,height:950});
  await page.waitForFunction(()=>{const r=document.querySelector(".station-terrain-studio")?.getBoundingClientRect();return r && r.x>=0 && r.right<=560;});
  const bounds=await studio.boundingBox();
  assert(bounds.x>=0 && bounds.x+bounds.width<=560,"Terrain controls must fit a narrow viewport");
  assert.deepEqual(errors,[]);
  console.log("PASS: cached real DEM, bird's-eye camera, Tarbela/Mangla presets, exaggeration, north, flat reset, reduced motion, mobile, API/imagery unavailable");
}catch(error){
  console.error(error);
  if(page){console.error(await page.locator(".national-map").evaluate(e=>({...e.dataset})).catch(()=>null));await mkdir("screenshots",{recursive:true});await page.screenshot({path:"screenshots/station-terrain-error.png",fullPage:true,timeout:5000}).catch(()=>{});console.error((await page.locator(".station-terrain-studio").innerText({timeout:5000}).catch(()=>"Page unavailable")));}
  throw error;
}finally{await browser.close();}
