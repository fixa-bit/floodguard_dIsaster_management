import * as maplibregl from "maplibre-gl";

const base = `${import.meta.env.BASE_URL}station-terrain/`;
const remote = "https://elevation-tiles-prod.s3.amazonaws.com/terrarium/";
type TileIndex = {tiles: Record<string, unknown>;station_elevations_m?:Record<string,number>};
let indexPromise: Promise<TileIndex> | null = null;
let cachedIndex:TileIndex | null=null;
const tileIndex = () => indexPromise ??= fetch(base+"manifest.json").then(async r => {
  if (!r.ok) throw new Error("Terrain manifest unavailable");
  const result=await r.json() as TileIndex;cachedIndex=result;return result;
}).catch(():TileIndex => ({tiles:{}}));
export const stationCatalogElevation = (id:string) => cachedIndex?.station_elevations_m?.[id];

// Elevation bytes stay in memory so tiles preloaded in the background (for the
// next monitoring stop) are served instantly when the map asks for them.
const maxCachedTiles = 700;
const tileBytes = new Map<string, Promise<ArrayBuffer>>();
function cachedTileBytes(url:string) {
  const hit=tileBytes.get(url);
  if (hit) {tileBytes.delete(url);tileBytes.set(url,hit);return hit;}
  const pending=fetch(url).then(async response => {
    if(!response.ok)throw new Error(`HTTP ${response.status}`);
    return response.arrayBuffer();
  });
  tileBytes.set(url,pending);
  pending.catch(() => {if(tileBytes.get(url)===pending)tileBytes.delete(url);});
  for (const key of tileBytes.keys()) {if(tileBytes.size<=maxCachedTiles)break;tileBytes.delete(key);}
  return pending;
}
const tileUrl = (manifest:TileIndex,key:string) => (manifest.tiles[key] ? base : remote)+key;
function untilAborted<T>(promise:Promise<T>,signal:AbortSignal) {
  if (signal.aborted) return Promise.reject(signal.reason);
  return new Promise<T>((resolve,reject) => {
    const abort=() => reject(signal.reason);
    signal.addEventListener("abort",abort,{once:true});
    promise.then(resolve,reject).finally(() => signal.removeEventListener("abort",abort));
  });
}

maplibregl.addProtocol("station-dem",async (params, controller) => {
  const key = params.url.replace("station-dem://","");
  if (!/^\d+\/\d+\/\d+\.png$/.test(key)) throw new Error("Invalid elevation tile request");
  const manifest = await tileIndex();
  try {
    // Copy: the map may transfer the buffer to a worker, which would empty the cached one.
    return {data:(await untilAborted(cachedTileBytes(tileUrl(manifest,key)),controller.signal)).slice(0)};
  } catch(error) {
    if(controller.signal.aborted)throw error;
    // A tilted view can extend beyond the detailed cache. Use a real cached
    // parent tile there if offline, preserving encoded heights with nearest
    // sampling rather than fabricating flat land or interpolating RGB values.
    const [z,x,y]=key.replace(".png","").split("/").map(Number);
    for(let delta=1;delta<=Math.min(3,z);delta++) {
      const factor=2**delta, parent=`${z-delta}/${Math.floor(x/factor)}/${Math.floor(y/factor)}.png`;
      if(!manifest.tiles[parent])continue;
      const bytes=await untilAborted(cachedTileBytes(base+parent),controller.signal).catch(() => null);
      if(controller.signal.aborted)throw controller.signal.reason;
      if(!bytes)continue;
      const bitmap=await createImageBitmap(new Blob([bytes],{type:"image/png"}),{colorSpaceConversion:"none",premultiplyAlpha:"none"});
      const canvas=new OffscreenCanvas(256,256),ctx=canvas.getContext("2d")!;
      ctx.imageSmoothingEnabled=false;
      const size=256/factor;
      ctx.drawImage(bitmap,(x%factor)*size,(y%factor)*size,size,size,0,0,256,256);
      bitmap.close();
      return {data:canvas.transferToImageBitmap()};
    }
    throw new Error(`Elevation tile ${key} unavailable`);
  }
});

export async function inBatches<T>(items:T[],work:(item:T)=>Promise<unknown>,concurrency=6) {
  let next=0;
  await Promise.all(Array.from({length:Math.min(concurrency,items.length)},async () => {
    while (next<items.length) await work(items[next++]).catch(() => undefined);
  }));
}

/** Fetch elevation tiles ("z/x/y.png") into memory ahead of the camera. */
export async function preloadTerrainTiles(keys:string[]) {
  const manifest=await tileIndex();
  await inBatches([...new Set(keys)].filter(key => Number(key.split("/")[0])<=13),key => cachedTileBytes(tileUrl(manifest,key)));
}
