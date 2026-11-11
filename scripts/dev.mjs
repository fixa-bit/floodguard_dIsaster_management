import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
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

startService(
  "api",
  python,
  ["-m", "uvicorn", "app.main:app", "--reload", "--host", "127.0.0.1", "--port", "8000"],
  projectRoot,
);
startService(
  "web",
  windows ? "npm.cmd" : "npm",
  ["run", "dev", "--", "--host", "127.0.0.1", "--port", "3000"],
  frontendRoot,
  windows ? { shell: true } : {},
);

console.log("Open the app at http://127.0.0.1:3000 (API docs: http://127.0.0.1:8000/docs)");
