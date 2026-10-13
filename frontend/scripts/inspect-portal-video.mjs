import { chromium } from 'playwright';
import { writeFile, mkdir } from 'node:fs/promises';
const out = new URL('../../docs/portal-video/', import.meta.url);
await mkdir(out, { recursive: true });
const browser = await chromium.launch({headless:true, args:['--enable-webgl','--ignore-gpu-blocklist']});
const context = await browser.newContext({viewport:{width:1600,height:900},timezoneId:'Asia/Karachi'});
const page = await context.newPage();
const errors=[];page.on('pageerror', e=>errors.push(e.message));
await page.goto('http://127.0.0.1:3025/',{waitUntil:'domcontentloaded'});
await page.waitForTimeout(12000);
await page.screenshot({path:new URL('inspect-overview.png',out).pathname.slice(1)});
const views=['Overview','Predictive Risk Views','Upstream Source Flood Watch','River Monitoring','Citizen Reports','Simulation','GIS Operations','Rainfall heatmap'];
const data={};
for(const name of views){
 await page.locator('.sidebar nav').getByRole('button',{name,exact:true}).click();
 await page.waitForTimeout(2500);
 data[name]={text:await page.locator('main').innerText(),controls:await page.locator('main button,main input,main select,main summary').evaluateAll(es=>es.map(e=>({tag:e.tagName,text:(e.innerText||'').slice(0,80),aria:e.getAttribute('aria-label'),title:e.getAttribute('title'),type:e.getAttribute('type')})))};
 if(name==='Predictive Risk Views')await page.screenshot({path:new URL('inspect-models.png',out).pathname.slice(1)});
}
await writeFile(new URL('inspection.json',out),JSON.stringify({errors,data},null,2));
console.log(JSON.stringify({errors,views:Object.fromEntries(Object.entries(data).map(([k,v])=>[k,v.text.slice(0,1200)]))}));
await browser.close();
