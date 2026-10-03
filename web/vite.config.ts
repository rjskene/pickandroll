import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API runs on :8000 during development; everything under /api is proxied there.
// PICKANDROLL_API points the proxy elsewhere, e.g. at a worktree's API on another port.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.PICKANDROLL_API ?? "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
