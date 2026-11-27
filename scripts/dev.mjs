import { spawn, spawnSync } from "node:child_process";
import { existsSync, watch } from "node:fs";
import { connect } from "node:net";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const frontendRoot = resolve(projectRoot, "frontend");
const windows = process.platform === "win32";
const venvPython = resolve(projectRoot, ".venv", "Scripts", "python.exe");
const python = existsSync(venvPython) ? venvPython : windows ? "python" : "python3";

const services = [];
let stopping = false;

function stopService(service) {
  if (!service?.child?.pid) return;

  if (windows) {
    spawnSync("taskkill", ["/PID", String(service.child.pid), "/T", "/F"], {
      stdio: "ignore",
    });
  } else {
    service.child.kill("SIGTERM");
  }
}

function stopAll(exitCode = 0) {
  if (stopping) return;
  stopping = true;
  for (const service of services) stopService(service);
  process.exitCode = exitCode;
}

function startService(name, command, args, cwd, options = {}) {
  console.log(`[${name}] starting`);
  const child = spawn(command, args, {
    cwd,
    stdio: "inherit",
    ...options,
  });
  const service = { name, child };
  services.push(service);

  child.on("error", (error) => {
    console.error(`[${name}] failed to start: ${error.message}`);
    stopAll(1);
  });
  child.on("exit", (code, signal) => {
    if (stopping) return;
    if (signal) {
      console.log(`[${name}] stopped (${signal})`);
    } else {
      console.log(`[${name}] stopped (exit ${code ?? "unknown"})`);
    }
    stopAll(code === 0 ? 0 : 1);
  });
}

process.on("SIGINT", () => stopAll(0));
process.on("SIGTERM", () => stopAll(0));

const portFree = (port) => new Promise((done) => {
  const socket = connect({ host: "127.0.0.1", port }, () => { socket.destroy(); done(false); });
  socket.on("error", () => done(true));
});

// ---- Ports 3000 (app) and 8000 (API) belong to `npm run dev` --------------------------------
// A FloodGuard backend or app left on either port (an old `npm run dev`, a preview) is stopped so
// this one gets the port. Anything else on it is named, and nothing starts: the app never drifts
// to 3001, where the API would not answer it.
const WEB_PORT = 3000, API_PORT = 8000;

/** Process ids listening on a local port. */
function listeners(port) {
  if (windows) {
    const out = spawnSync("netstat", ["-ano", "-p", "tcp"], { encoding: "utf8" }).stdout ?? "";
    return [...new Set(out.split(/\r?\n/).map((line) => line.trim().split(/\s+/))
      .filter((cols) => cols[3] === "LISTENING" && cols[1]?.endsWith(`:${port}`)).map((cols) => Number(cols[4])).filter(Boolean))];
  }
  const out = spawnSync("lsof", ["-ti", `tcp:${port}`, "-sTCP:LISTEN"], { encoding: "utf8" }).stdout ?? "";
  return [...new Set(out.split(/\s+/).filter(Boolean).map(Number))];
}

/** [parent id, command line] of a process. */
function processInfo(pid) {
  if (windows) {
    const script = `$p = Get-CimInstance Win32_Process -Filter "ProcessId=${pid}"; if ($p) { "$($p.ParentProcessId)|$($p.CommandLine)" }`;
    const [parent, ...command] = (spawnSync("powershell", ["-NoProfile", "-Command", script], { encoding: "utf8" }).stdout ?? "").trim().split("|");
    return [Number(parent) || 0, command.join("|")];
  }
  const out = (spawnSync("ps", ["-o", "ppid=,command=", "-p", String(pid)], { encoding: "utf8" }).stdout ?? "").trim();
  const [, parent, command] = /^(\d+)\s+(.*)$/.exec(out) ?? [];
  return [Number(parent) || 0, command ?? ""];
}

const inProject = (command) => command.toLowerCase().includes(projectRoot.toLowerCase());
const isFloodGuard = (command) => command.includes("app.main:app") || (/\bvite\b/.test(command) && inProject(command));

const pause = (ms) => new Promise((done) => setTimeout(done, ms));

async function claimPort(port, label) {
  // A few rounds: stopping an old `npm run dev`'s API also makes it close its own app, so a
  // process can vanish between being listed and being looked at.
  for (let round = 0; round < 4 && !(await portFree(port)); round += 1) {
    for (const pid of listeners(port)) {
      const [parent, command] = processInfo(pid);
      if (!command) continue; // already gone (or unreadable): the wait below settles it
      const [, parentCommand] = parent ? processInfo(parent) : [0, ""];
      // uvicorn --reload: the socket can sit with its worker, whose parent is the FloodGuard reloader.
      const ours = isFloodGuard(command) || (parentCommand.includes("app.main:app") && command.includes("multiprocessing"));
      if (!ours) {
        console.error(`[${label}] port ${port} is used by another program (pid ${pid}: ${command.slice(0, 120)}).`);
        console.error(`[${label}] Close it, then run npm run dev again. Port ${port} is kept for FloodGuard's ${label}.`);
        process.exit(1);
      }
      console.log(`[${label}] stopping the FloodGuard ${label} already on port ${port} (pid ${pid}) so this one can use it`);
      const target = parentCommand.includes("app.main:app") ? parent : pid;
      if (windows) spawnSync("taskkill", ["/PID", String(target), "/T", "/F"], { stdio: "ignore" });
      else try { process.kill(target, "SIGTERM"); } catch { /* already gone */ }
    }
    for (let i = 0; i < 20 && !(await portFree(port)); i += 1) await pause(250);
  }
  if (!(await portFree(port))) {
    console.error(`[${label}] port ${port} is still busy (pid ${listeners(port).join(", ") || "unknown"}); close what uses it and try again.`);
    process.exit(1);
  }
}

await claimPort(API_PORT, "api");
await claimPort(WEB_PORT, "web");

// ---- The API, restarted here when backend code changes ---------------------------------------
// Not uvicorn --reload: on Windows its reloader restarts by sending Ctrl+C, which Windows delivers to
// every program in this terminal, so each backend edit stopped the whole `npm run dev`
// ("Terminate batch job (Y/N)?"). Here the API process alone is ended and started again.
const api = { name: "api", child: null, restarting: false };
services.push(api);

function startApi() {
  const child = spawn(python, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(API_PORT)], { cwd: projectRoot, stdio: "inherit" });
  api.child = child;
  child.on("error", (error) => { console.error(`[api] failed to start: ${error.message}`); stopAll(1); });
  child.on("exit", (code, signal) => {
    if (stopping || api.restarting || api.child !== child) return;
    // A crash (often a code error) leaves the rest running; the next saved change starts it again.
    console.log(`[api] stopped (${signal ?? `exit ${code ?? "unknown"}`}); save a backend file to start it again`);
    api.child = null;
  });
}

async function restartApi(reason) {
  if (stopping || api.restarting) return;
  api.restarting = true;
  console.log(`[api] ${reason}; restarting`);
  const old = api.child;
  if (old && old.exitCode === null) {
    const exited = new Promise((done) => old.once("exit", done));
    stopService(api);
    await Promise.race([exited, pause(5000)]);
  }
  for (let i = 0; i < 40 && !(await portFree(API_PORT)); i += 1) await pause(250);
  api.restarting = false;
  if (!stopping) startApi();
}

// Watch the backend's Python files (and .env), as uvicorn --reload did; a burst of saves restarts once.
let changeTimer = null;
const watchBackend = (dir, recursive) => {
  try {
    watch(dir, { recursive }, (_event, file) => {
      const name = String(file ?? "");
      if (!(name.endsWith(".py") || name === ".env") || name.includes("__pycache__")) return;
      clearTimeout(changeTimer);
      changeTimer = setTimeout(() => void restartApi(`change in ${name.replaceAll("\\", "/")}`), 400);
    });
  } catch (error) {
    console.log(`[api] cannot watch ${dir} for changes (${error.message}); restart npm run dev after backend edits`);
  }
};

console.log("[api] starting (restarts when backend files change)");
startApi();
watchBackend(resolve(projectRoot, "app"), true);
watchBackend(projectRoot, false);

startService(
  "web",
  windows ? "npm.cmd" : "npm",
  ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(WEB_PORT), "--strictPort"],
  frontendRoot,
  windows ? { shell: true } : {},
);

// Optional: the separate Flood Simulation app's Python service (port 8010), shown under
// Simulation → Flood simulation lab. Started only if its folder exists and the port is free;
// if it stops, the rest of the portal keeps running.
const floodSimDir = resolve(process.env.FLOOD_SIM_DIR ?? resolve(projectRoot, "..", "..", "flood sim cursor", "flood sim cursor"));
const floodSimPython = resolve(floodSimDir, ".venv", "Scripts", "python.exe");
if (existsSync(floodSimPython)) {
  if (await portFree(8010)) {
    console.log("[flood-sim] starting its data service on port 8010");
    const child = spawn(floodSimPython, ["-m", "uvicorn", "server.app:app", "--host", "127.0.0.1", "--port", "8010"], { cwd: floodSimDir, stdio: "ignore" });
    services.push({ name: "flood-sim", child });
    child.on("exit", (code) => { if (!stopping) console.log(`[flood-sim] data service stopped (exit ${code ?? "unknown"}); the rest of the portal keeps running`); });
  } else {
    console.log("[flood-sim] port 8010 already in use; assuming its data service is running");
  }
}

console.log("Open the app at http://127.0.0.1:3000 (API docs: http://127.0.0.1:8000/docs)");
