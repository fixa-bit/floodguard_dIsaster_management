// Browser-only demo feeds. Stateful reports and simulations use the isolated backend DB.
import { readFile, writeFile } from 'node:fs/promises';
export const output = new URL('../../docs/portal-video/', import.meta.url);
export const apiBase = 'http://127.0.0.1:8025/api/v1';
export const pathOf = url => decodeURIComponent(url.pathname).replace(/^\/([A-Za-z]:)/, '$1');
const load = async name => JSON.parse((await readFile(new URL(name, output), 'utf8')).replace(/^\uFEFF/, ''));

export async function prepareDemo() {
 const now = new Date();
 const date = offset => new Date(now.getTime()+offset*86400000).toISOString();
 const fixtures = new Map();
 for (const path of ['/system/status','/simulation/status','/flood/model-forecasts',
  ...['JHG_001','RWP_001','MUL_001','ISB_001'].flatMap(id=>[`/weather/current?location_id=${id}`,`/river/current?location_id=${id}`,`/flood/risk?location_id=${id}`])]) {
  const response = await fetch(apiBase+path);
  if(!response.ok)throw new Error(`Demo setup ${path}: ${response.status}`);
  fixtures.set(path,await response.json());
 }
 fixtures.set('/gis/national-risk',await load('feed-national-risk.json'));
 fixtures.set('/gis/water-intelligence',await load('feed-water-intelligence-demo.json'));
 const rain=await load('feed-rainfall.json');
 rain.features.forEach((feature,i)=>{
  const [lon,lat]=feature.geometry.coordinates;
  const storm=90*Math.exp(-((lon-73)**2/12+(lat-32)**2/8))+28*Math.exp(-((lon-70)**2/7+(lat-29)**2/9));
  feature.properties.accumulations_mm={last_1h:+(storm*.055).toFixed(1),last_3h:+(storm*.18).toFixed(1),last_6h:+(storm*.4).toFixed(1),last_24h:+storm.toFixed(1),next_24h:+(storm*1.35).toFixed(1),next_72h:+(storm*1.9).toFixed(1)};
 });
 rain.metadata={...rain.metadata,source:'Illustrative storm scenario',generated_at:date(0),cache_status:'fresh',warning:'DEMO: synthetic rainfall scenario'};
 fixtures.set('/gis/rainfall',rain);
 const monitor=await load('feed-monitoring.json');
 const upstream=await load('feed-upstream-forecasts.json');
 const decorate=(feed, monitoring)=>{
  Object.assign(feed,{generated_at:date(0),cached_at:date(0),last_attempt_at:date(0),next_refresh_at:date(1/24),refreshing:false,refresh_error:null});
  feed.notes=['Illustrative browser-only readings and forecasts for the portal video.'];
  feed.stations.forEach((station,index)=>{
   const base=monitoring?1200+index*87:2100+index*330;
   const makeProvider=(provider, multiplier)=>{
    const series=Array.from({length:15},(_,i)=>({time:date(i-7).slice(0,10),value:Math.round((base+Math.sin(i*.4)*base*.09+Math.max(0,i-7)*base*.12)*multiplier),phase:i<=7?'past':'forecast',low:Math.round(base*.8),high:Math.round(base*1.8)}));
    return {provider,source:`DEMO ${provider} series`,status:'available',river_id:null,generated_at:date(0),current_cumecs:base*multiplier,peak_forecast_cumecs:Math.max(...series.map(p=>p.value)),peak_forecast_time:date(6),recent_trend_cumecs:120,series,retrospective:series.slice(0,7),note:'Illustrative values; not a live provider response.'};
   };
   station.providers=[makeProvider('GloFAS',1),...(!monitoring?[makeProvider('GEOGloWS',1.08)]:[])];
   station.rainfall=Array.from({length:10},(_,i)=>({date:date(i-3).slice(0,10),precipitation_mm:Math.round(8+30*Math.sin((i+1)*.35)**2),probability_percent:60+i*3,phase:i<3?'past':'forecast'}));
   station.flood_types=[{type:'Riverine',severity:'HIGH',probability:.76,basis:'Illustrative rising discharge scenario',lead_time:'24–48h'},{type:'Flash flood',severity:'MEDIUM',probability:.48,basis:'Illustrative forecast rainfall',lead_time:'0–6h'}];
   station.stats={...station.stats,current_mean_cumecs:base,highest_provider_peak_cumecs:base*1.8,peak_to_current_ratio:1.8,glofas_peak_cumecs:base*1.8,geoglows_peak_cumecs:base*1.9,max_forecast_rain_mm:38,max_rain_probability_percent:90,geoglows_max_step_rise_cumecs:170};
   if(monitoring)Object.assign(station,{current_discharge_cumecs:base,current_source:'DEMO observation',observed_at:date(0),forecast_discharge_cumecs:Math.round(base*1.24),forecast_valid_at:date(1),change_24h_cumecs:180,change_source:'DEMO 24h comparison',flood_category:index%4===0?'Medium':'Below low',expected_peak_at:date(5),expected_peak_cumecs:Math.round(base*1.8),official_forecast_text:null});
  });
  return feed;
 };
 fixtures.set('/river/monitoring',decorate(monitor,true));
 fixtures.set('/river/monitoring/refresh',monitor);
 fixtures.set('/river/upstream-forecasts',decorate(upstream,false));
 fixtures.set('/river/upstream-forecasts/refresh',upstream);
 fixtures.set('/gis/google-flood-hub',{type:'FeatureCollection',features:monitor.stations.slice(0,7).map((station,i)=>({type:'Feature',id:`demo-${i}`,geometry:{type:'Point',coordinates:[station.longitude,station.latitude]},properties:{id:`demo-${i}`,name:`Demo ${station.name}`,river:station.river,severity:['NO_FLOODING','ABOVE_NORMAL','SEVERE'][i%3],severity_label:['Normal','Warning','Danger'][i%3],country_code:'PK',issued_at:date(0),forecast_start:date(0),forecast_end:date(7),trend:'RISE',source:'ILLUSTRATIVE DEMO',quality_verified:false,source_url:'https://sites.research.google/floods/'}})),metadata:{status:'demo',message:'Illustrative gauge markers; no Google API connection is asserted.',fetched_at:date(0),source:'ILLUSTRATIVE DEMO',license:'Synthetic demonstration'}});
 await writeFile(new URL('demo-feed-provenance.json',output),JSON.stringify({createdAt:date(0),purpose:'Browser recording only. Models assumed trained on small datasets; no additional model training was performed.',database:'Separate demo.db, never floodguard.db',feeds:Object.fromEntries([...fixtures].map(([k,v])=>[k,k.includes('model-forecasts')?'Existing bundled dummy forecast series':k.includes('monitoring')||k.includes('upstream')||k.includes('google-flood')||k.includes('rainfall')?'Browser-only illustrative fixture':'Isolated backend simulation response']))},null,2));
 return {fixtures,monitor,now};
}

export async function installDemoRoutes(context,demo) {
 await context.route('**/api/v1/**',async route=>{
  const u=new URL(route.request().url());const key=u.pathname.replace('/api/v1','')+u.search;
  if(demo.fixtures.has(key))return route.fulfill({json:demo.fixtures.get(key)});
  const match=u.pathname.match(/\/river\/monitoring\/([^/]+)\/(history|official-history)$/);
  if(match){
   const station=demo.monitor.stations.find(s=>s.id===match[1]);
   const samples=Array.from({length:17},(_,i)=>({time:new Date(demo.now.getTime()-(16-i)*3*3600000).toISOString(),value:Math.round((station?.current_discharge_cumecs??1600)*(.8+i*.012)),source:'DEMO stored observations'}));
   return route.fulfill({json:{station_id:match[1],source:'DEMO observations',samples,gauge:'INFLOW',error:null,official_forecast:null}});
  }
  if(u.pathname.endsWith('/flood/water-extent/location')) {
   const lat=Number(u.searchParams.get('latitude')),lon=Number(u.searchParams.get('longitude'));
   return route.fulfill({json:{model:'U-Net demonstration output',label:'ILLUSTRATIVE water mask',threshold:.5,water_pixels:10486,valid_pixels:65536,water_percent:16.0,coordinates:[[lon-.04,lat+.04],[lon+.04,lat+.04],[lon+.04,lat-.04],[lon-.04,lat-.04]],image_data_url:demo.waterImage,during_date:'2026-10-10T00:00:00Z',pre_date:'2026-09-28T00:00:00Z'}});
  }
  const response=await route.fetch();await route.fulfill({response});
 });
}
