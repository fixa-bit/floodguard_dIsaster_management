import { chromium } from 'playwright';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { mapTestUrl } from './map-test-url.mjs';

const browser=await chromium.launch({headless:true,executablePath:process.env.EDGE_PATH ?? 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'});
const output=new URL('../screenshots/',import.meta.url);
try {
  await mkdir(output,{recursive:true});
  const page=await browser.newPage({viewport:{width:1440,height:1100}});
  const errors=[];
  page.on('console',message=>{ if(message.type()==='error' && message.text().includes('population')) console.log(message.text()); });
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(mapTestUrl(process.env.DASHBOARD_URL ?? 'http://127.0.0.1:3000'),{waitUntil:'domcontentloaded'});
  await page.getByRole('button',{name:'GIS Operations',exact:true}).click();
  const panel=page.getByRole('region',{name:'Flood-affected population analysis'});
  try {
    await panel.getByText('313,436',{exact:true}).waitFor({timeout:60000});
  } catch(error) {
    console.log(await panel.innerText());
    console.log(errors);
    await page.screenshot({path:fileURLToPath(new URL('population-error.png',output)),fullPage:true});
    throw error;
  }
  await panel.getByText('9.7%',{exact:true}).first().waitFor();
  await panel.getByText('57.4%',{exact:true}).waitFor();
  const map=page.locator('.national-map[data-population-analysis]:not([data-population-analysis=""])');
  await map.waitFor({timeout:60000});
  await page.waitForFunction(()=>Number(document.querySelector('.national-map')?.getAttribute('data-population-population-grid'))>0,{},{timeout:60000});
  const bounds=await map.boundingBox();
  await map.click({position:{x:bounds.width/2,y:bounds.height/2}});
  await page.locator('.population-map-popup').waitFor();
  await panel.getByLabel('Population administrative level').selectOption('ADM3');
  await panel.getByText('Tehsil boundaries unavailable. No tehsil totals have been invented.').waitFor();
  await panel.getByLabel('Population administrative level').selectOption('ADM2');
  await panel.getByLabel('Population density · yellow to red').uncheck();
  await page.waitForFunction(()=>document.querySelector('.national-map')?.getAttribute('data-population-population-grid')==='0');
  await panel.getByLabel('Population density · yellow to red').check();
  await page.waitForFunction(()=>Number(document.querySelector('.national-map')?.getAttribute('data-population-population-grid'))>0);
  await panel.getByLabel('Population flood source').selectOption('sample');
  await panel.getByLabel('Population flood source').selectOption('historical_reference');
  await page.screenshot({path:fileURLToPath(new URL('population-desktop.png',output)),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await page.waitForFunction(()=>Number(document.querySelector('.national-map')?.getAttribute('data-map-zoom'))>7);
  await page.waitForFunction(()=>Number(document.querySelector('.national-map')?.getAttribute('data-population-population-grid'))>0);
  await page.screenshot({path:fileURLToPath(new URL('population-mobile.png',output)),fullPage:true});
  if(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth)) throw new Error('Mobile horizontal overflow');
  if(errors.length) throw new Error(errors.join('\n'));
  console.log('Population UI passed: real summary, map layers, clickable regions, layer toggles, unavailable tehsils and responsive layout.');
} finally {await browser.close();}
