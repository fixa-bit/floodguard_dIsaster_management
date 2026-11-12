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
  const response = await fetch(url);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const bytes = await response.arrayBuffer();
  if (storage) {
    const copy = new Response(bytes.slice(0), { headers: { "Content-Type": response.headers.get("Content-Type") ?? "application/octet-stream" } });
    void storage.open(cacheName).then((cache) => cache.put(url, copy)).catch(() => undefined);
  }
  return bytes;
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
