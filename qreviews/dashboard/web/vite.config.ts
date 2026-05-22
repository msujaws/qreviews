import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Build output lands in ../web_dist so FastAPI can mount it via StaticFiles.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: path.resolve(__dirname, "../web_dist"),
    emptyOutDir: true,
    assetsDir: "assets",
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8765",
      "/phabricator": "http://127.0.0.1:8765",
    },
  },
});
