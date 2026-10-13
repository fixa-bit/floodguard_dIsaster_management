import { chromium } from 'playwright';
import { writeFile } from 'node:fs/promises';
import { output,pathOf,prepareDemo,installDemoRoutes } from './portal-video-demo.mjs';
const demo=await prepareDemo();
const browser=await chromium.launch({headless:true,args:['--enable-webgl','--ignore-gpu-blocklist']});
const context=await browser.newContext({viewport:{width:1600,height:800},timezoneId:'Asia/Karachi',recordVideo:{dir:pathOf(new URL('raw/',output)),size:{width:1600,height:800}}});
await installDemoRoutes(context,demo);
const page=await context.newPage();
try{
 await page.goto('http://127.0.0.1:3025/?mapDiagnostics=1',{waitUntil:'domcontentloaded'});
 await page.waitForFunction(()=>document.querySelector('.kpi-grid')?.innerText.includes('%')&&document.querySelector('.national-map')?.dataset.boundaryPainted==='true',null,{timeout:60000});
 await page.getByLabel('Target latitude',{exact:true}).fill('35.80');await page.getByLabel('Target longitude',{exact:true}).fill('76.30');await page.getByRole('button',{name:'Locate coordinates',exact:true}).click();await page.waitForTimeout(1800);
 await page.getByRole('button',{name:'Close coordinate details',exact:true}).click();
 await page.getByRole('checkbox',{name:'Glaciers & upstream drainage',exact:true}).check({timeout:120000});
 await page.getByLabel('Glacier coverage',{exact:true}).selectOption('contributors');
 await page.getByRole('button',{name:'Toggle map layers',exact:true}).click();
 const box=await page.locator('.national-map').boundingBox();await page.mouse.move(box.x+box.width*.62,box.y+box.height*.5);await page.mouse.wheel(0,620);await page.waitForTimeout(16000);
 await page.screenshot({path:pathOf(new URL('glacier-detail.png',output))});
 await writeFile(new URL('glacier-recording.json',output),JSON.stringify({videoPath:await page.video().path()},null,2));
 console.log('Detailed glacier view recorded');
}finally{await context.unrouteAll({behavior:'ignoreErrors'});await context.close();await browser.close();}
