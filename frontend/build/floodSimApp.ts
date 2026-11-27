// Serves the separate Flood Simulation app (built by scripts/build-flood-sim.mjs) at /flood-sim/
// on the portal's own dev and preview servers, so the Simulation page can show it in a same-origin
// frame. Its API calls (/flood-sim/api/*) and published result rasters (/outputs/*) go to the
// app's Python service on port 8010 through the proxy entries below.
import { createReadStream, existsSync, statSync } from "node:fs";
import type { IncomingMessage, ServerResponse } from "node:http";
import { extname, join, normalize, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import type { Plugin, ProxyOptions } from "vite";

const portalRoot = fileURLToPath(new URL("../..", import.meta.url));
export const floodSimDist = resolve(process.env.FLOOD_SIM_DIST ?? join(portalRoot, "..", "..", "flood sim cursor", "flood sim cursor", "dist-portal"));
const floodSimApi = process.env.FLOOD_SIM_API ?? "http://127.0.0.1:8010";

// The simulation service accepts changes (load/run a case) only from its own local origins.
// A request from the portal opened on this machine carries the portal's origin (e.g. localhost:3000),
// so present it as the service's own origin. Any other origin, such as a public share link,
// is passed through unchanged and stays read-only.
const LOCAL_ORIGIN = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/;
const asServiceOrigin: ProxyOptions["configure"] = (proxy) => {
  proxy.on("proxyReq", (proxyReq, req) => {
    const origin = req.headers.origin;
    if (origin && LOCAL_ORIGIN.test(origin)) proxyReq.setHeader("origin", new URL(floodSimApi).origin);
  });
};

export const floodSimProxy: Record<string, ProxyOptions> = {
  "/flood-sim/api": { target: floodSimApi, changeOrigin: true, rewrite: (path) => path.replace(/^\/flood-sim/, ""), configure: asServiceOrigin },
  "/outputs": { target: floodSimApi, changeOrigin: true, configure: asServiceOrigin },
};

const TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
  ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp",
  ".ktx2": "image/ktx2", ".glb": "model/gltf-binary", ".gltf": "model/gltf+json", ".wasm": "application/wasm",
  ".xml": "application/xml", ".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf", ".txt": "text/plain; charset=utf-8",
};

function serve(req: IncomingMessage, res: ServerResponse, next: () => void) {
  // Mounted at /flood-sim, so req.url is the path below it. API calls fall through to the proxy.
  const path = decodeURIComponent(new URL(req.url ?? "/", "http://x").pathname);
  if (path === "/api" || path.startsWith("/api/") || (req.method !== "GET" && req.method !== "HEAD")) { next(); return; }
  if (!existsSync(join(floodSimDist, "index.html"))) {
    res.writeHead(503, { "Content-Type": "text/plain; charset=utf-8" }).end(`The Flood Simulation app is not built. Run: node scripts/build-flood-sim.mjs (looked in ${floodSimDist})`);
    return;
  }
  let file = normalize(join(floodSimDist, path));
  if (!file.startsWith(floodSimDist + sep) && file !== floodSimDist) { res.writeHead(400).end(); return; }
  if (!existsSync(file) || !statSync(file).isFile()) {
    if (extname(path)) { res.writeHead(404).end(); return; }
    file = join(floodSimDist, "index.html");
  }
  // A rebuild rewrites these files; an empty file seen mid-write must never be cached for a year.
  if (statSync(file).size === 0) {
    res.writeHead(503, { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store", "Retry-After": "2" })
      .end("The Flood Simulation app is being rebuilt; reload in a moment.");
    return;
  }
  res.writeHead(200, {
    "Content-Type": TYPES[extname(file).toLowerCase()] ?? "application/octet-stream",
    "Content-Length": statSync(file).size,
    "Cache-Control": file.includes(`${sep}assets${sep}`) ? "max-age=31536000, immutable" : "no-cache",
  });
  if (req.method === "HEAD") { res.end(); return; }
  createReadStream(file).pipe(res);
}

export function floodSimApp(): Plugin {
  return {
    name: "flood-sim-app",
    configureServer(server) { server.middlewares.use("/flood-sim", serve); },
    configurePreviewServer(server) { server.middlewares.use("/flood-sim", serve); },
  };
}
