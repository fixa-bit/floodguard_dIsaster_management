import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { compressedMapAssets } from "./build/compressedMapAssets.ts";
import { uiZoomViewportUnits } from "./build/uiZoom.ts";

export default defineConfig({
  plugins: [compressedMapAssets(), react()],
  css: { postcss: { plugins: [uiZoomViewportUnits()] } },
  server: {
    host: "127.0.0.1",
    port: 3000,
  },
});
