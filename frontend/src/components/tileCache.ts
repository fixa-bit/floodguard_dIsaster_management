// Shared helpers for the map's tile protocols: a persistent tile store in the
// browser's Cache Storage (survives reloads), abortable waits, and batching.

const storage = typeof caches === "undefined" ? null : caches;

/** Tile bytes from the named persistent cache, else from the network (then stored). */
export async function persistentTileBytes(url: string, cacheName: string): Promise<ArrayBuffer> {
  if (storage) {
    try {
      const hit = await (await storage.open(cacheName)).match(url);
      if (hit) return await hit.arrayBuffer();
    } catch { /* storage unavailable or blocked: fall through to the network */ }
  }
  const bytes = await fetchTileBytes(url);
  const contentType = bytes.contentType;
  if (storage) {
    const copy = new Response(bytes.data.slice(0), { headers: { "Content-Type": contentType } });
    void storage.open(cacheName).then((cache) => cache.put(url, copy)).catch(() => undefined);
  }
  return bytes.data;
}

/** One tile from the network. A failed request is tried twice more, so a passing network error does not leave a hole in the map. */
async function fetchTileBytes(url: string) {
  for (let attempt = 0; ; attempt++) {
    try {
      const response = await fetch(url);
      if (response.ok) return { data: await response.arrayBuffer(), contentType: response.headers.get("Content-Type") ?? "application/octet-stream" };
      // A missing tile will not appear on a second try.
      if (response.status === 404 || attempt === 2) throw new Error(`HTTP ${response.status}`);
    } catch (error) {
      if (attempt === 2 || (error instanceof Error && error.message === "HTTP 404")) throw error;
    }
    await new Promise((resolve) => setTimeout(resolve, 350 * (attempt + 1)));
  }
}

/** Deletes persistent caches whose name starts with `prefix`, except `keep`. */
export function prunePersistentCaches(prefix: string, keep: string) {
  if (!storage) return;
  void storage.keys()
    .then((names) => Promise.all(names.filter((name) => name.startsWith(prefix) && name !== keep).map((name) => storage.delete(name))))
    .catch(() => undefined);
}

export function untilAborted<T>(promise: Promise<T>, signal: AbortSignal) {
  if (signal.aborted) return Promise.reject(signal.reason);
  return new Promise<T>((resolve, reject) => {
    const abort = () => reject(signal.reason);
    signal.addEventListener("abort", abort, { once: true });
    promise.then(resolve, reject).finally(() => signal.removeEventListener("abort", abort));
  });
}

export async function inBatches<T>(items: T[], work: (item: T) => Promise<unknown>, concurrency = 6) {
  let next = 0;
  await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, async () => {
    while (next < items.length) await work(items[next++]).catch(() => undefined);
  }));
}
