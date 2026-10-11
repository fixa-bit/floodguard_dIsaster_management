import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { dirname, parse, resolve } from "node:path";
import { gzipSync } from "node:zlib";
import type { IncomingMessage, ServerResponse } from "node:http";
import type { Plugin, ResolvedConfig } from "vite";

const prefix = "\0compressed-map:";
const assetName = /^[\w.-]+-[a-f0-9]{16}\.geojson\.gz$/;

export function compressedMapAssets(): Plugin {
  let config: ResolvedConfig;
  const devAssets = new Map<string, Buffer>();
  const send = (request: IncomingMessage, response: ServerResponse, name: string, bytes: Buffer) => {
    const etag = `"${name}"`;
    response.setHeader("Cache-Control", "public, max-age=31536000, immutable");
    response.setHeader("ETag", etag);
    if (request.headers["if-none-match"] === etag) { response.statusCode = 304; response.end(); return; }
    response.setHeader("Content-Type", "application/gzip");
    response.setHeader("Content-Length", bytes.length);
    response.end(request.method === "HEAD" ? undefined : bytes);
  };
  return {
    name: "compressed-map-assets",
    enforce: "pre",
    configResolved(resolved) { config = resolved; },
    resolveId(source, importer) {
      if (!source.endsWith(".geojson?compressed") || !importer) return;
      return prefix + resolve(dirname(importer.split("?")[0]), source.slice(0, -"?compressed".length));
    },
    async load(id) {
      if (!id.startsWith(prefix)) return;
      const file = id.slice(prefix.length);
      this.addWatchFile(file);
      const raw = await readFile(file);
      const hash = createHash("sha256").update(raw).digest("hex").slice(0, 16);
      const name = `${parse(file).name}-${hash}.geojson.gz`;
      const compressed = gzipSync(raw, { level: 9 });
      if (config.command === "serve") {
        devAssets.set(name, compressed);
        return `export default ${JSON.stringify(`${config.base}__map_assets/${name}`)};`;
      }
      const reference = this.emitFile({ type: "asset", fileName: `assets/${name}`, source: compressed });
      return `export default import.meta.ROLLUP_FILE_URL_${reference};`;
    },
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const pathname = new URL(request.url ?? "/", "http://localhost").pathname;
        if (!pathname.startsWith(`${config.base}__map_assets/`)) return next();
        const name = pathname.slice(pathname.lastIndexOf("/") + 1);
        const bytes = devAssets.get(name);
        if (!bytes) return next();
        send(request, response, name, bytes);
      });
    },
    configurePreviewServer(server) {
      server.middlewares.use((request, response, next) => {
        const pathname = new URL(request.url ?? "/", "http://localhost").pathname;
        const name = pathname.slice(pathname.lastIndexOf("/") + 1);
        if (!pathname.startsWith(`${config.base}assets/`) || !assetName.test(name)) return next();
        void readFile(resolve(config.root, config.build.outDir, "assets", name)).then((bytes) => send(request, response, name, bytes)).catch(() => next());
      });
    },
  };
}
