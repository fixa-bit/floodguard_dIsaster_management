// Refresh the shareable Riverine Forecast page:
//   1. capture the current API responses from the running backend into share/data/
//   2. bundle share/riverineShare.tsx into share/dist/
// Then publish share/dist/riverine-forecast.html (with share/dist/assets/*) as the shared link.
//
//   node share/build.mjs                    # backend at http://localhost:8000
//   node share/build.mjs http://host:8000   # another backend
import { execSync } from "node:child_process";
import { copyFileSync, mkdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const here = fileURLToPath(new URL(".", import.meta.url));
const api = `${process.argv[2] ?? "http://localhost:8000"}/api/v1`;
const sources = {
  monitoring: "/river/monitoring",
  station: "/predictive/marala-station-forecast",
  extended: "/predictive/riverine-extended-forecast",
  outlook: "/predictive/riverine-outlook/MARALA",
};

mkdirSync(`${here}data`, { recursive: true });
for (const [name, path] of Object.entries(sources)) {
  const response = await fetch(`${api}${path}`);
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  writeFileSync(`${here}data/${name}.json`, JSON.stringify(await response.json()));
  console.log(`captured ${name}`);
}
writeFileSync(`${here}data/meta.json`, JSON.stringify({ captured_at: new Date().toISOString() }));

execSync("npx vite build --config share/vite.share.config.ts", { cwd: `${here}..`, stdio: "inherit" });
copyFileSync(`${here}riverine-forecast.html`, `${here}dist/riverine-forecast.html`);
console.log("built share/dist/riverine-forecast.html");
