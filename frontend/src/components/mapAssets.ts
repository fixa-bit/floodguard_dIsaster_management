const assets = new Map<string, Promise<unknown>>();
const compressedAsset = /-[a-f0-9]{16}\.geojson\.gz(?:\?|$)/;

async function readMapResponse(response: Response, compressed: boolean): Promise<unknown> {
  if (!compressed) return response.json();
  const buffer = await response.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  // Some hosts apply Content-Encoding themselves; fetch has already decoded those.
  if (bytes[0] !== 0x1f || bytes[1] !== 0x8b) return JSON.parse(new TextDecoder().decode(bytes));
  const stream = new Blob([buffer]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Response(stream).json();
}

async function fetchMapAsset(url: string): Promise<unknown> {
  const compressed = compressedAsset.test(url);
  const cache = compressed && typeof caches !== "undefined" ? await caches.open("floodguard-static-maps-v1").catch(() => null) : null;
  const cached = cache ? await cache.match(url).catch(() => undefined) : undefined;
  if (cached) {
    try {
      if (!cached.ok) throw new Error("Invalid cached map data");
      return await readMapResponse(cached, compressed);
    } catch {
      await cache?.delete(url).catch(() => {});
    }
  }
  const response = await fetch(url, { cache: compressed ? "force-cache" : "default" });
  if (!response.ok) throw new Error("Map boundary data unavailable");
  const copy = cache ? response.clone() : null;
  const data = await readMapResponse(response, compressed);
  if (cache && copy) void cache.put(url, copy).catch(() => {});
  return data;
}

// Shared requests survive view changes; failures remain retryable.
export function loadMapAsset<T>(url: string): Promise<T> {
  let pending = assets.get(url);
  if (!pending) {
    pending = fetchMapAsset(url).catch((error: unknown) => {
      assets.delete(url);
      throw error;
    });
    assets.set(url, pending);
  }
  return pending as Promise<T>;
}
