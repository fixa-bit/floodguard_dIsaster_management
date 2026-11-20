// Build the Flood Simulation app (separate repository) to run inside the portal at /flood-sim/.
//
//   node scripts/build-flood-sim.mjs            # uses FLOOD_SIM_DIR or ../../flood sim cursor/flood sim cursor
//
// Output: <flood sim>/dist-portal (its own git-ignored build folder). The portal serves it at
// /flood-sim/ and forwards /flood-sim/api/* and /outputs/* to the app's Python service on port 8010
// (see frontend/vite.config.ts and ops/share/gateway.mjs). Rerun after changing the simulation app.
import { spawnSync } from "node:child_process";
import { existsSync, renameSync, rmSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const portalRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const simDir = resolve(process.env.FLOOD_SIM_DIR ?? join(portalRoot, "..", "..", "flood sim cursor", "flood sim cursor"));
if (!existsSync(join(simDir, "package.json"))) throw new Error(`Flood Simulation app not found at ${simDir}; set FLOOD_SIM_DIR`);
if (!existsSync(join(simDir, "node_modules"))) throw new Error(`Run npm install in ${simDir} first`);

const outDir = join(simDir, "dist-portal");
const result = spawnSync(process.platform === "win32" ? "npx.cmd" : "npx", ["vite", "build", "--base", "/flood-sim/", "--outDir", "dist-portal", "--emptyOutDir"], {
  cwd: simDir, stdio: "inherit", shell: process.platform === "win32",
});
if (result.status !== 0) process.exit(result.status ?? 1);

// vite-plugin-cesium copies Cesium to <outDir>/<base>/cesium; the page asks for <base>/cesium, which is <outDir>/cesium.
const nested = join(outDir, "flood-sim", "cesium");
if (existsSync(nested)) {
  rmSync(join(outDir, "cesium"), { recursive: true, force: true });
  renameSync(nested, join(outDir, "cesium"));
  rmSync(join(outDir, "flood-sim"), { recursive: true, force: true });
}
if (!existsSync(join(outDir, "cesium", "Cesium.js"))) throw new Error("Cesium assets missing from the build");
console.log(`Flood Simulation built for the portal: ${outDir}`);
