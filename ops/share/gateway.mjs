// Password-protected gateway for sharing the full FloodGuard app through a tunnel.
//
//   /api/*    -> the FastAPI backend (default http://127.0.0.1:8300, the share's own; 8000 is npm run dev's)
//   anything  -> the built frontend in frontend/dist (single-page app fallback to index.html)
//
// Every request needs HTTP Basic credentials: user "floodguard" and the password in
// ops/share/.share-password (created on first run). Browsers ask once and then send it with
// every page, API and map request automatically. Listens on 127.0.0.1 only; the tunnel
// (cloudflared) is what makes it reachable from outside.
//
// --open turns the password off: anyone who has the link can open the app (start-share.ps1 -NoPassword).
//
//   node ops/share/gateway.mjs [--port 4300] [--api http://127.0.0.1:8300] [--open]
import { createReadStream, existsSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { request as httpRequest, createServer } from "node:http";
import { randomBytes, timingSafeEqual } from "node:crypto";
import { extname, join, normalize, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const here = fileURLToPath(new URL(".", import.meta.url));
const root = resolve(here, "..", "..");
const dist = resolve(root, "frontend", "dist");
const arg = (name, fallback) => { const i = process.argv.indexOf(`--${name}`); return i > 0 ? process.argv[i + 1] : fallback; };
const port = Number(arg("port", 4300));
const api = new URL(arg("api", "http://127.0.0.1:8300"));
// The separate Flood Simulation app (Simulation → Flood simulation lab): its portal build and its data service.
const simDist = resolve(process.env.FLOOD_SIM_DIST ?? join(root, "..", "..", "flood sim cursor", "flood sim cursor", "dist-portal"));
const simApi = new URL(arg("sim-api", "http://127.0.0.1:8010"));
const USER = "floodguard";
const OPEN = process.argv.includes("--open");

const passwordFile = join(here, ".share-password");
if (!existsSync(passwordFile)) writeFileSync(passwordFile, `${randomBytes(9).toString("base64url")}\n`, { mode: 0o600 });
const PASSWORD = readFileSync(passwordFile, "utf8").trim();
if (PASSWORD.length < 8) throw new Error(`${passwordFile} must hold a password of at least 8 characters`);
const expected = Buffer.from(`${USER}:${PASSWORD}`);

// Slow down password guessing: after 10 failures from one address in 10 minutes, refuse for the rest of the window.
const failures = new Map();
const WINDOW_MS = 10 * 60_000;
const clientIp = (req) => String(req.headers["cf-connecting-ip"] ?? req.socket.remoteAddress ?? "unknown");
function lockedOut(ip) {
  const entry = failures.get(ip);
  if (!entry || Date.now() - entry.since > WINDOW_MS) { failures.delete(ip); return false; }
  return entry.count >= 10;
}
function noteFailure(ip) {
  const entry = failures.get(ip);
  if (!entry || Date.now() - entry.since > WINDOW_MS) failures.set(ip, { count: 1, since: Date.now() });
  else entry.count += 1;
}
function authorised(req) {
  if (OPEN) return true;
  const header = req.headers.authorization ?? "";
  if (!header.startsWith("Basic ")) return false;
  const given = Buffer.from(header.slice(6), "base64");
  return given.length === expected.length && timingSafeEqual(given, expected);
}

const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8", ".json": "application/json", ".geojson": "application/geo+json", ".svg": "image/svg+xml",
  ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".ico": "image/x-icon",
  ".woff2": "font/woff2", ".woff": "font/woff", ".mp4": "video/mp4", ".webm": "video/webm", ".pbf": "application/x-protobuf",
  ".wasm": "application/wasm", ".txt": "text/plain; charset=utf-8", ".gz": "application/gzip", ".bin": "application/octet-stream",
};
const baseHeaders = { "X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "same-origin", "X-Content-Type-Options": "nosniff" };

function serveStatic(req, res, dist, path = decodeURIComponent(new URL(req.url, "http://x").pathname)) {
  let file = normalize(join(dist, path));
  if (!file.startsWith(dist + sep) && file !== dist) { res.writeHead(400, baseHeaders).end(); return; }
  let isFile = existsSync(file) && statSync(file).isFile();
  if (!isFile) {
    if (extname(path)) { res.writeHead(404, baseHeaders).end("Not found"); return; }
    file = join(dist, "index.html");
    isFile = existsSync(file);
  }
  if (!isFile) { res.writeHead(503, { ...baseHeaders, "Content-Type": "text/plain" }).end("The app has not been built. Run ops/share/start-share.ps1."); return; }
  const immutable = file.includes(`${sep}assets${sep}`);
  res.writeHead(200, {
    ...baseHeaders,
    "Content-Type": TYPES[extname(file).toLowerCase()] ?? "application/octet-stream",
    "Content-Length": statSync(file).size,
    "Cache-Control": immutable ? "private, max-age=31536000, immutable" : "no-cache",
  });
  if (req.method === "HEAD") { res.end(); return; }
  createReadStream(file).pipe(res);
}

function proxyApi(req, res, target = api, path = req.url) {
  const headers = { ...req.headers, host: target.host };
  delete headers.authorization; // the backend never needs the share password
  const upstream = httpRequest({ protocol: target.protocol, hostname: target.hostname, port: target.port, method: req.method, path, headers }, (answer) => {
    res.writeHead(answer.statusCode ?? 502, { ...answer.headers, ...baseHeaders });
    answer.pipe(res);
  });
  upstream.on("error", () => {
    if (!res.headersSent) res.writeHead(502, { ...baseHeaders, "Content-Type": "application/json" });
    res.end(JSON.stringify({ detail: target === api ? "The FloodGuard backend is not running on the host PC." : "The flood simulation data service is not running on the host PC." }));
  });
  req.pipe(upstream);
}

const server = createServer((req, res) => {
  const ip = clientIp(req);
  if (lockedOut(ip)) { res.writeHead(429, { ...baseHeaders, "Retry-After": "600" }).end("Too many wrong passwords. Try again in 10 minutes."); return; }
  if (!authorised(req)) {
    if (req.headers.authorization) noteFailure(ip);
    res.writeHead(401, { ...baseHeaders, "WWW-Authenticate": 'Basic realm="FloodGuard", charset="UTF-8"', "Content-Type": "text/plain; charset=utf-8" })
      .end("FloodGuard: enter the shared username and password.");
    return;
  }
  failures.delete(ip);
  if (req.url.startsWith("/api/") || req.url === "/api") proxyApi(req, res);
  else if (req.url.startsWith("/flood-sim/api/")) proxyApi(req, res, simApi, req.url.slice("/flood-sim".length));
  else if (req.url.startsWith("/outputs/")) proxyApi(req, res, simApi);
  else if (req.url.startsWith("/flood-sim/") && (req.method === "GET" || req.method === "HEAD")) serveStatic(req, res, simDist, decodeURIComponent(new URL(req.url, "http://x").pathname).slice("/flood-sim".length));
  else if (req.method === "GET" || req.method === "HEAD") serveStatic(req, res, dist);
  else res.writeHead(405, baseHeaders).end();
});

server.listen(port, "127.0.0.1", () => {
  console.log(`FloodGuard share gateway on http://127.0.0.1:${port} -> app ${dist}, API ${api.origin}`);
  console.log(OPEN ? "No password (--open): anyone with the link can open the app." : `Username: ${USER}. Password: see ${passwordFile}`);
});
