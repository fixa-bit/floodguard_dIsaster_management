import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import { output, pathOf, prepareDemo, installDemoRoutes } from './portal-video-demo.mjs';

const dry=process.env.VIDEO_PREFLIGHT==='1';
const resume=process.env.VIDEO_RESUME==='1';
const frames=new URL(dry?'preflight/':resume?'frames-rest/':'frames/',output);
await mkdir(frames,{recursive:true});await mkdir(new URL('raw/',output),{recursive:true});
const demo=await prepareDemo();
const browser=await chromium.launch({headless:true,args:['--enable-webgl','--ignore-gpu-blocklist']});
const context=await browser.newContext({viewport:{width:1600,height:800},timezoneId:'Asia/Karachi',locale:'en-GB',acceptDownloads:true,...(!dry?{recordVideo:{dir:pathOf(new URL('raw/',output)),size:{width:1600,height:800}}}:{})});
await installDemoRoutes(context,demo);
const page=await context.newPage();
const errors=[],chapters=[],downloads=[];let videoStart,contentStart,current;
page.on('pageerror',e=>errors.push(e.message));
page.on('download',async download=>{const file=download.suggestedFilename();await download.saveAs(pathOf(new URL(file,output)));downloads.push(file);});
await page.addInitScript(()=>{
 addEventListener('DOMContentLoaded',()=>{
  const pointer=document.createElement('div');pointer.id='walkthrough-pointer';pointer.style.cssText='position:fixed;left:0;top:0;width:17px;height:23px;pointer-events:none;z-index:2147483647;transform:translate(-40px,-40px);filter:drop-shadow(0 1px 2px #0008)';
  pointer.innerHTML='<svg viewBox="0 0 20 26"><path d="M2 1 L2 22 L7 17 L11 25 L15 23 L11 15 L18 15 Z" fill="#fff" stroke="#062b2c" stroke-width="1.4"/></svg>';
  const ring=document.createElement('div');ring.style.cssText='position:fixed;width:38px;height:38px;border:3px solid #3eefd1;border-radius:50%;pointer-events:none;z-index:2147483646;opacity:0';
  document.body.append(pointer,ring);
  addEventListener('mousemove',e=>{pointer.style.transform=`translate(${e.clientX}px,${e.clientY}px)`;});
  addEventListener('mousedown',e=>{ring.style.left=`${e.clientX-19}px`;ring.style.top=`${e.clientY-19}px`;ring.animate([{opacity:1,transform:'scale(.7)'},{opacity:0,transform:'scale(1.7)'}],{duration:650});});
 });
});
const pause=async seconds=>page.waitForTimeout(dry?150:seconds*1000);
const move=async (x,y)=>{await page.mouse.move(x,y,{steps:dry?2:14});};
const click=async locator=>{
 await locator.waitFor({state:'visible',timeout:30000});
 await locator.evaluate(el=>el.scrollIntoView({block:'nearest',inline:'nearest',behavior:'smooth'}));await page.waitForTimeout(dry?70:300);
 const box=await locator.boundingBox();if(!box)throw new Error('Missing click target');await move(box.x+box.width/2,box.y+box.height/2);await locator.click({timeout:120000});await pause(.35);
};
const check=async (name,on=true)=>{const loc=page.getByRole('checkbox',{name,exact:true}).first();if(await loc.isChecked()!==on)await click(loc);};
const nav=async name=>{await click(page.locator('.sidebar nav').getByRole('button',{name,exact:true}));await pause(.8);};
const layerPanel=async open=>{const loc=page.getByRole('button',{name:'Toggle map layers',exact:true});if((await loc.getAttribute('aria-expanded')==='true')!==open)await click(loc);};
const fill=async (name,value)=>{const loc=page.getByLabel(name,{exact:true}).first();await click(loc);await loc.fill(value);await pause(.4);};
const select=async (name,value)=>{const loc=page.getByLabel(name,{exact:true}).first();await click(loc);await loc.selectOption(value);await pause(.7);};
const segment=async (title,caption,action,seconds=4)=>{
 if(current)current.end=(Date.now()-contentStart)/1000;
 current={title,caption,start:(Date.now()-contentStart)/1000};chapters.push(current);console.log(`${dry?'Check':'Record'}: ${title}`);
 await action();await pause(seconds);
 await page.screenshot({path:pathOf(new URL(`${String(chapters.length).padStart(2,'0')}.png`,frames))});
};
const closeIf=async name=>{const loc=page.getByRole('button',{name,exact:true});if(await loc.isVisible())await click(loc);};
const locate=async (lat,lon)=>{await layerPanel(true);await fill('Target latitude',lat);await fill('Target longitude',lon);await click(page.getByRole('button',{name:'Locate coordinates',exact:true}));await page.waitForTimeout(dry?800:1200);};

try {
 videoStart=Date.now();await page.goto('http://127.0.0.1:3025/?mapDiagnostics=1',{waitUntil:'domcontentloaded'});
 demo.waterImage=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=c.height=256;const ctx=c.getContext('2d');ctx.fillStyle='rgba(32,150,255,.75)';ctx.beginPath();for(let y=0;y<=256;y+=4){const x=112+25*Math.sin(y*.04);ctx.lineTo(x-15-10*Math.sin(y*.02),y);}for(let y=256;y>=0;y-=4){const x=112+25*Math.sin(y*.04);ctx.lineTo(x+15+14*Math.sin(y*.023),y);}ctx.closePath();ctx.fill();ctx.beginPath();ctx.ellipse(167,165,39,19,-.4,0,Math.PI*2);ctx.fill();return c.toDataURL('image/png');});
 await page.waitForFunction(()=>document.querySelector('.kpi-grid')?.innerText.includes('%')||document.querySelector('.command-stats-deck')?.innerText.includes('simulation'),null,{timeout:60000});
 await page.waitForFunction(()=>document.querySelector('.national-map')?.dataset.mapZoom,null,{timeout:60000});
 await page.waitForTimeout(dry?1000:3500);await layerPanel(false);contentStart=Date.now();

 if(!resume){
 await segment('01 / Operational overview','FloodGuard AI: an actual browser walkthrough. Models are assumed trained on small datasets; all demonstrated readings are illustrative.',async()=>{},6);
 for(const [label,caption] of [
  ['National Risk','National screening summarizes district risk, priorities, and monitoring intervals in one command view.'],
  ['Rivers','The river summary compares city discharge and forecast values, with timestamps and a manual refresh control.'],
  ['Rainfall','The rainfall table compares current, recent, and forecast rainfall across the four operational cities.'],
  ['System','System information shows the configured data mode, monitoring interval, and active risk engine.']]){
  await segment('02 / Command statistics',caption,async()=>{await click(page.locator('.command-stats-tabs').getByRole('button',{name:label,exact:true}));},3);
  await click(page.locator('.command-stats-tabs').getByRole('button',{name:label,exact:true}));
 }
 await segment('03 / National GIS layers','Toggle district boundaries, screening, waterways, catchments, and monitoring categories on the interactive map.',async()=>{
  await layerPanel(true);for(const label of ['District names & boundaries','District screening','Rivers, lakes & dams','Risk locations','Catchment areas','Major barrages & headworks','Upstream river stations','Major dams & reservoirs','Confluence watch locations'])await check(label);
  await layerPanel(false);await pause(2);
 },5);
 await segment('03 / Reference outlines and Flood Hub integration','Compare the available Kashmir outlines and enable Flood Hub markers. The gauges shown here are illustrative integration examples.',async()=>{
  await layerPanel(true);await select('Kashmir boundary source','previous');await pause(1);await select('Kashmir boundary source','districts');await check('Google Flood Hub');await layerPanel(false);
 },4);
 await layerPanel(true);await check('Google Flood Hub',false);await layerPanel(false);
 await segment('04 / Coordinate lookup','Enter latitude and longitude to inspect local coverage. The selected coordinate is pinned on the map.',async()=>{
  await locate('31.1448','72.1460');await layerPanel(false);await page.getByRole('complementary',{name:'Coordinate details',exact:true}).waitFor();
 },5);
 await segment('05 / Catchment study mode','Enable corresponding layers to focus on the selected district and hydrological sub-basin, including matching river features.',async()=>{
  await check('Enable corresponding layers');await pause(2);
 },5);
 await check('Enable corresponding layers',false);await closeIf('Close coordinate details');
 await layerPanel(true);await closeIf('Deselect location');
 await check('Catchment areas',false);await check('District screening',false);await layerPanel(false);
 await segment('06 / Station hover cards','Hover and pin a priority monitoring station to inspect readings, provenance, and stored trends.',async()=>{
  await locate('30.518528','70.836721');await closeIf('Close coordinate details');await layerPanel(false);
  const marker=page.getByLabel('Located coordinate',{exact:true});await marker.waitFor();const b=await marker.boundingBox();
  const x=b.x+b.width/2,y=b.y+b.height;await move(x,y);await pause(1);await page.mouse.click(x,y);await page.locator('.station-info-card').waitFor({timeout:15000});
 },4);
 await click(page.getByRole('button',{name:'Open station details',exact:true}));await page.getByRole('complementary',{name:'River station details',exact:true}).waitFor();
 await segment('07 / Station discharge forecast','Station details link to an interactive forecast, separate historical series, date inspection, a readings table, and CSV download.',async()=>{
  await click(page.getByRole('tab',{name:'Discharge forecast',exact:true}));await page.locator('.station-forecast-plot').waitFor();const b=await page.locator('.station-forecast-plot').boundingBox();await move(b.x+b.width*.67,b.y+b.height*.5);await pause(2);
  await click(page.getByRole('button',{name:'Download discharge readings',exact:true}));
 },5);
 await closeIf('Close station forecast');await closeIf('Close station details');
 await segment('08 / Glaciers and headwaters','Inspect glacier coverage and upstream drainage, then fit the map to the glacier headwaters.',async()=>{
  await layerPanel(true);await check('Glaciers & upstream drainage');await click(page.getByRole('button',{name:'Show glacier headwaters',exact:true}));await layerPanel(false);await pause(2);
 },4);
 await layerPanel(true);await check('Glaciers & upstream drainage',false);await click(page.getByRole('button',{name:'Show regional Pakistan overview',exact:true}));
 }
 if(resume)await layerPanel(true);
 await segment('09 / Satellite water extent','Select a place to display a dated satellite water-mask overlay. This recording uses an illustrative U-Net output.',async()=>{
  const control=page.locator('.sar-water-control');await click(control.locator('summary'));await click(control.getByRole('button',{name:'Select place on map',exact:true}));await layerPanel(false);
  const canvas=page.locator('.national-map canvas');const b=await canvas.boundingBox();await move(b.x+b.width*.62,b.y+b.height*.62);await page.mouse.click(b.x+b.width*.62,b.y+b.height*.62);await pause(1);await layerPanel(true);await control.getByText('16% of valid pixels',{exact:false}).waitFor({state:'attached'});await control.evaluate(el=>{for(let parent=el;parent;parent=parent.parentElement)if(parent.tagName==='DETAILS')parent.open=true;});await control.getByText('16% of valid pixels',{exact:false}).scrollIntoViewIfNeeded();
 },4);
 await layerPanel(false);await pause(2);
 await segment('10 / Rainfall heatmap','Switch between observed accumulation windows and 24-hour or 72-hour forecasts. Colors follow the rainfall scale.',async()=>{
  await nav('Rainfall heatmap');await page.locator('.national-map').waitFor();await layerPanel(true);await click(page.getByRole('button',{name:'Last 24 hours',exact:true}));await layerPanel(false);await pause(3);
  await layerPanel(true);await click(page.getByRole('button',{name:'Next 24 hours',exact:true}));await layerPanel(false);
 },5);
 await segment('11 / Population exposure analysis','GIS Operations estimates exposed people and mapped settlements, with district or tehsil breakdowns and coverage information.',async()=>{
  await nav('GIS Operations');await page.locator('.population-cards').waitFor({timeout:30000});await page.locator('.population-analysis').evaluate(el=>el.scrollIntoView({behavior:'smooth',block:'start'}));await pause(2);
 },5);
 await segment('12 / Exposure controls and map overlays','The analysis supports historical water, configured segmentation, uploaded polygons, and synthetic scenarios; inspect the existing result and its layers.',async()=>{
  await select('Population administrative level','ADM3');await pause(2);await select('Population administrative level','ADM2');
  await click(page.getByRole('checkbox',{name:'Population density · yellow to red',exact:true}));await pause(1);await click(page.getByRole('checkbox',{name:'Population density · yellow to red',exact:true}));
  await page.locator('.national-map').evaluate(el=>el.scrollIntoView({behavior:'smooth',block:'center'}));await pause(2);await layerPanel(false);
 },4);
 await segment('13 / Predictive model views','Five predictive views cover riverine, flash, urban, seasonal basin, and upstream or transboundary risk, with forecast times and target selectors.',async()=>{
  await nav('Predictive Risk Views');await page.locator('.multiview-card').first().waitFor();await page.evaluate(()=>window.scrollTo({top:0,behavior:'smooth'}));
 },5);
 for(const [index,title,caption] of [
  [0,'Riverine short-term model','Riverine forecasts: XGBoost baseline inputs, Trimmu and Balloki targets, discharge forecasts, and flood classes over 24–48 hours.'],
  [1,'Flash-flood model','Flash-flood guidance combines rainfall, soil moisture, and GIS features for catchment risk within six hours.'],
  [2,'Urban flooding model','Urban susceptibility uses city-scale targets, rainfall, drainage context, and selectable forecast intervals.'],
  [3,'Seasonal basin model','Seasonal basin risk shows forecasts over weeks to months, with target-specific risk series.'],
  [4,'Upstream anomaly model','Upstream and transboundary risk highlights anomalous flow changes over hours to days. Model outputs are illustrative in this demo.']]){
  await segment(`14 / ${title}`,caption,async()=>{
   const card=page.locator('.multiview-card').nth(index);await card.evaluate(el=>el.scrollIntoView({block:'center',behavior:'smooth'}));await pause(.7);const tabs=card.locator('.forecast-target-tabs button');if(await tabs.count()>1)await click(tabs.nth(1));
  },4);
 }
 await segment('15 / Upstream source flood watch','Select upper-basin stations, compare GloFAS and GEOGloWS series, and inspect historical trends, rainfall, and forecast risk signals.',async()=>{
  await nav('Upstream Source Flood Watch');await page.locator('.source-station-selector button').first().waitFor();await click(page.locator('.source-station-selector button').nth(2));await pause(2);
 },5);
 await segment('16 / Source forecast context','Each station includes provider summaries, expected peaks, rainfall context, location details, and scheduled or manual refresh.',async()=>{
  await page.locator('.source-lower-grid').evaluate(el=>el.scrollIntoView({block:'center',behavior:'smooth'}));
 },4);
 await segment('17 / River monitoring table','Filter monitoring stations by river or name, switch units, and compare current flow, forecasts, flood categories, and expected peaks.',async()=>{
  await nav('River Monitoring');await page.locator('.monitoring-station-toggle').first().waitFor();await select('Monitoring view river','Indus');await select('Monitoring view units','cusecs');await fill('Search monitoring stations','Taunsa');
 },4);
 await segment('18 / Station network and chart','Open a station to inspect its upstream network and forecast. Chart legends and date inspection help distinguish the displayed series.',async()=>{
  await click(page.locator('.monitoring-station-toggle').first());await click(page.getByRole('tab',{name:'Discharge forecast',exact:true}));await page.locator('.station-forecast-plot').waitFor();const plot=await page.locator('.station-forecast-plot').boundingBox();await move(plot.x+plot.width*.8,plot.y+plot.height*.5);
 },5);
 await closeIf('Close station forecast');await closeIf('Close station details');
 await segment('19 / Citizen reports','Citizen reports provide a scrollable database-backed feed, coordinates, optional image or video links, priority flags, and closure status.',async()=>{
  await nav('Citizen Reports');await page.locator('.report-list-scroll').waitFor();await click(page.getByRole('button',{name:'Create report',exact:true}));
 },4);
 await segment('20 / Submit a geolocated report','Create a report using coordinates, browser location, or a Google Maps link. Image GPS fields remain visible when no geotag is available.',async()=>{
  await fill('Google Maps link','https://maps.google.com/?q=31.1448,72.1460');await click(page.getByRole('button',{name:'Apply map link',exact:true}));
  await fill('Report','DEMO VIDEO: Water crossing a low road near Trimmu. Request field verification.');await fill('Depth cm','22');await fill('Source','portal-video-demo');
  await click(page.getByRole('button',{name:'Save report',exact:true}));await page.getByText('DEMO VIDEO: Water crossing a low road near Trimmu. Request field verification.',{exact:true}).first().waitFor();
 },5);
 await segment('21 / Prioritize and close reports','Flag a report for attention, then close it in the database. New reports appear in the active window before remaining in the saved feed.',async()=>{
  const card=page.locator('.report-card').filter({hasText:'DEMO VIDEO: Water crossing a low road near Trimmu.'}).first();await click(card.locator('.important-button'));await pause(2);await click(card.locator('.close-report-button'));await pause(1);
 },4);
 await segment('22 / Monitoring simulation','Configure a station, measurement, units, test thresholds, and a reading profile to exercise the monitoring workflow.',async()=>{
  await nav('Simulation');await page.getByLabel('Station',{exact:true}).waitFor();await select('Station','TAUNSA');await click(page.getByRole('button',{name:'Custom test thresholds',exact:true}));await fill('Warning (cusecs)','300000');await fill('Danger (cusecs)','600000');await select('Testing profile','danger');
 },5);
 await segment('23 / Threshold crossing and saved results','Play the test scenario. Threshold crossings save simulated readings and create linked alerts and incidents.',async()=>{
  await click(page.getByRole('button',{name:'Play',exact:true}));await page.getByRole('heading',{name:'Threshold reached',exact:true}).waitFor({timeout:30000});
 },4);
 await segment('24 / Alert review','Review threshold alerts, distinguish operational and simulated flows, and open the linked incident.',async()=>{
  await nav('Alerts');await click(page.getByRole('button',{name:'Simulated flow',exact:true}));await page.locator('.alert-incident-link').first().waitFor();
 },5);
 await segment('25 / Incident management','The incident view records severity, status, location, and timestamps. Linked details preserve the simulated-flow context.',async()=>{
  await click(page.locator('.alert-incident-link').first());await page.getByRole('dialog').waitFor();
 },5);
 await click(page.getByRole('dialog').getByRole('button',{name:'Close',exact:true}));
 await segment('26 / System activity','The activity timeline records model decisions, monitoring changes, report actions, and simulated response events.',async()=>{
  await nav('System Activity');await page.locator('.timeline').waitFor();
 },5);
 await segment('27 / Command overview','The walkthrough covers the portal as it runs in a web browser. Small-dataset training is an assumption; this video does not validate model accuracy.',async()=>{
  await closeIf('Dismiss simulation alert');await nav('Overview');await page.waitForFunction(()=>document.querySelector('.national-map')?.dataset.boundaryPainted==='true',null,{timeout:60000});await layerPanel(false);
 },6);
 current.end=(Date.now()-contentStart)/1000;
 if(errors.length)throw new Error(`Browser errors: ${errors.join(' | ')}`);
 if(await page.locator('.error-banner').count())throw new Error('Unexpected dashboard error banner at end');
 const videoPath=dry?null:await page.video().path();
 await writeFile(new URL(dry?'preflight-manifest.json':resume?'recording-rest-manifest.json':'recording-manifest.json',output),JSON.stringify({viewport:{width:1600,height:800},trimStartSeconds:(contentStart-videoStart)/1000,durationSeconds:current.end,videoPath,chapters,downloads,browserErrors:errors},null,2));
 console.log(JSON.stringify({success:true,chapters:chapters.length,duration:current.end,videoPath,downloads}));
}catch(error){
 await page.screenshot({path:pathOf(new URL(dry?'preflight-failure.png':'recording-failure.png',output))}).catch(()=>{});
 await writeFile(new URL('failure.json',output),JSON.stringify({message:error.message,chapter:current,errors,body:await page.locator('main').innerText().catch(()=>''),controls:await page.locator('main button,main input,main select').evaluateAll(es=>es.map(e=>({text:e.innerText,aria:e.getAttribute('aria-label'),title:e.getAttribute('title')}))).catch(()=>[])},null,2));
 throw error;
}finally{await context.unrouteAll({behavior:'ignoreErrors'});await context.close();await browser.close();}
