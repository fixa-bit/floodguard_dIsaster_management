import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { waterPolygons } from "../src/components/stormReplayData.ts";

const browser = await chromium.launch({ executablePath: process.env.EDGE_PATH ?? "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", headless: true });
const errors=[], writes=[];
let page;
try {
  page=await browser.newPage({ viewport: { width:1600, height:1100 } });
  page.on("pageerror",error=>errors.push(error.message));
  page.on("request",request=>{ if(!["GET","OPTIONS"].includes(request.method())) writes.push(request.url()); });
  await page.route("**/api/v1/**",route=>new URL(route.request().url()).pathname.endsWith("/simulation/monitoring/stations") ? route.fulfill({json:[{code:"TAUNSA",name:"Taunsa",river:"Indus",thresholds:[]}]}) : route.fulfill({status:503,json:{error:{code:"MATERIAL_CHECK",message:"Operational feeds excluded from water-material check"}}}));
  if (process.env.LIVE_IMAGERY !== "1") await page.route("**/World_Imagery/MapServer/tile/**",route=>route.abort());
  await page.goto(process.env.FRONTEND_URL ?? "http://127.0.0.1:3000/",{waitUntil:"domcontentloaded"});
  await page.locator(".sidebar nav").getByRole("button",{name:"Simulation",exact:true}).click();
  await page.getByRole("tab",{name:"Storm replay",exact:true}).click();
  const root=page.locator(".storm-replay"), canvas=root.locator(".storm-replay-currents"), map=root.locator(".storm-replay-map");
  await page.waitForFunction(()=>Number(document.querySelector(".storm-replay-currents")?.dataset.streaks)>100);
  assert.equal(await canvas.getAttribute("data-renderer"),"advected-water-v2");
  await page.getByRole("button",{name:"Jump to peak",exact:true}).click();
  await root.locator(".storm-replay-stage").scrollIntoViewIfNeeded();
  await page.waitForFunction(()=>document.querySelector(".storm-replay-map").dataset.realTerrain==="true");
  const terrain=await (await page.request.get(new URL("/simulation-terrain/jhang-metadata.json",page.url()).href)).json();
  assert.equal(terrain.sample_spacing_m_approx,262);
  assert.equal((await page.request.get(new URL("/simulation-terrain/jhang-dem.tif",page.url()).href)).status(),200);
  await page.getByRole("button",{name:"Terrain",exact:true}).click();
  assert.equal(await map.getAttribute("data-real-terrain"),"false");
  await page.getByRole("button",{name:"Terrain",exact:true}).click();
  const fingerprint=()=>canvas.evaluate(element=>{
    const pixels=element.getContext("2d").getImageData(0,0,element.width,element.height).data;
    let hash=2166136261;
    for(let i=0;i<pixels.length;i+=37) hash=Math.imul(hash^pixels[i],16777619);
    return hash>>>0;
  });
  const before=await fingerprint();
  await page.getByRole("button",{name:"Play replay",exact:true}).click();
  await page.waitForFunction(()=>Number(document.querySelector(".storm-replay-currents").dataset.frames)>15);
  assert.notEqual(await fingerprint(),before,"Actual water pixels advect, rather than only the timeline changing");
  await page.getByRole("button",{name:"Pause replay",exact:true}).click();
  const paused=await fingerprint(), pausedFrame=await canvas.getAttribute("data-frames");
  await page.waitForTimeout(300);
  assert.equal(await fingerprint(),paused,"Pause preserves the exact developed water/trail image");
  assert.equal(await canvas.getAttribute("data-frames"),pausedFrame);
  assert(Number(await canvas.getAttribute("data-streaks"))>520,"Density is view-local, replacing the previous sparse global dashes");
  const source=JSON.parse(await readFile(new URL("../src/data/outlook-exposure/jhang.geojson",import.meta.url),"utf8"));
  const clip=await canvas.evaluate((element,polygons)=>{
    const container=document.querySelector(".storm-replay-map"), [lng,lat]=container.dataset.center.split(",").map(Number);
    const world=512*2**Number(container.dataset.zoom), mercatorY=(1-Math.log(Math.tan(Math.PI/4+lat*Math.PI/360))/Math.PI)/2;
    const ringContains=(point,ring)=>{let inside=false;for(let i=0,j=ring.length-1;i<ring.length;j=i++){const a=ring[i],b=ring[j];if((a[1]>point[1])!==(b[1]>point[1])&&point[0]<(b[0]-a[0])*(point[1]-a[1])/(b[1]-a[1])+a[0])inside=!inside;}return inside;};
    const wet=(x,y)=>{const point=[lng+(x-container.clientWidth/2)/world*360,Math.atan(Math.sinh(Math.PI*(1-2*(mercatorY+(y-container.clientHeight/2)/world))))*180/Math.PI];return polygons.some(p=>ringContains(point,p.coordinates[0])&&!p.coordinates.slice(1).some(r=>ringContains(point,r)));};
    const context=element.getContext("2d"),ratio=element.width/container.clientWidth,pixels=context.getImageData(0,0,element.width,element.height).data;
    let outside=0,leaks=0,painted=0;
    for(let y=20;y<container.clientHeight-20;y+=13)for(let x=20;x<container.clientWidth-20;x+=13){
      const alpha=pixels[(Math.floor(y*ratio)*element.width+Math.floor(x*ratio))*4+3];
      if(alpha>20)painted++;
      if(!wet(x,y)&&!wet(x-5,y)&&!wet(x+5,y)&&!wet(x,y-5)&&!wet(x,y+5)){outside++;if(alpha>3)leaks++;}
    }
    return {outside,leaks,painted};
  },waterPolygons(source,5));
  assert(clip.outside>30&&clip.painted>100);
  assert.equal(clip.leaks,0,"Material and trails cannot paint dry land or polygon holes");
  await root.locator(".storm-replay-layout").screenshot({path:fileURLToPath(new URL(process.env.LIVE_IMAGERY === "1" ? "../screenshots/simulation-natural-water-satellite.png" : "../screenshots/simulation-natural-water.png",import.meta.url))});
  await page.getByRole("button",{name:"Currents",exact:true}).click();
  assert.equal(await canvas.getAttribute("data-streaks"),"0");
  assert.notEqual(await fingerprint(),paused,"Current toggle hides trails while retaining the water material");
  await page.getByRole("button",{name:"Currents",exact:true}).click();
  await page.getByRole("slider",{name:"Storm replay elapsed time",exact:true}).fill("0");
  assert.equal(await canvas.evaluate(element=>element.getContext("2d").getImageData(0,0,element.width,element.height).data.some((value,index)=>index%4===3&&value>0)),false,"Level zero clears all water material and history");
  await page.locator(".storm-replay-method summary").click();
  assert.match(await page.locator(".storm-replay-method").innerText(),/not aligned to a station gauge datum/);
  assert.match(await page.locator(".storm-replay-method").innerText(),/FFC Jhang\/Bhakkar/);
  await page.getByLabel("Storm replay district",{exact:true}).selectOption("lahore");
  assert.equal(await page.getByRole("button",{name:"Terrain",exact:true}).isDisabled(),true,"Terrain coverage is not invented for other districts");
  await page.getByRole("tab",{name:"Monitoring scenario",exact:true}).click();
  assert.equal(await root.count(),0);
  assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
  console.log(`PASS: dense advected water pixels, exact freeze on pause, strict mask clipping (${clip.outside} dry samples), layer toggles, real terrain assets/coverage, level-zero cleanup, unchanged operational writes and no browser errors.`);
}catch(error){if(page&&!page.isClosed())await page.screenshot({path:fileURLToPath(new URL("../screenshots/simulation-natural-water-failure.png",import.meta.url)),fullPage:true}).catch(()=>{});throw error;}finally{await browser.close();}
