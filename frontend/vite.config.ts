import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { compressedMapAssets } from "./build/compressedMapAssets.ts";
import { floodSimApp, floodSimProxy } from "./build/floodSimApp.ts";
import { readableTextSizes } from "./build/readableText.ts";
import { uiZoomViewportUnits } from "./build/uiZoom.ts";

export default defineConfig({
  plugins: [compressedMapAssets(), floodSimApp(), react()],
  css: { postcss: { plugins: [uiZoomViewportUnits(), readableTextSizes()] } },
  server: {
    host: "127.0.0.1",
    port: 3000,
    // Port 3000 is FloodGuard's: fail instead of moving to 3001, where the API would not answer.
    strictPort: true,
    proxy: floodSimProxy,
  },
  preview: { proxy: floodSimProxy },
});
