// Builds the shareable Riverine Forecast page (share/riverineShare.tsx) as one ES module + one CSS file.
// The main app build (vite.config.ts) is unaffected.
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

const here = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  root: here,
  plugins: [react()],
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    outDir: `${here}dist/assets`,
    emptyOutDir: true,
    cssCodeSplit: false,
    lib: { entry: `${here}riverineShare.tsx`, formats: ["es"], fileName: () => "riverine.js", cssFileName: "riverine" },
  },
});
