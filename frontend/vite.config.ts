import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { compressedMapAssets } from "./build/compressedMapAssets.ts";

export default defineConfig({
  plugins: [compressedMapAssets(), react()],
  server: {
    host: "127.0.0.1",
    port: 3000,
  },
});
