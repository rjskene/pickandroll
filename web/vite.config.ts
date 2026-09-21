import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API runs on :8000 during development; everything under /api is proxied there.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
