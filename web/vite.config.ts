import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API runs on :8000 during development; everything under /api is proxied there.
// PICKANDROLL_API points the proxy elsewhere, e.g. at a worktree's API on another port.
// Phone access over the user's tailnet (docs/DRAFT_DAY.md): PICKANDROLL_WEB_HOST binds another
// interface (the Mac's tailnet address, or 0.0.0.0) when the command line gives no --host, and
// PICKANDROLL_WEB_ALLOWED_HOSTS (comma-separated) lets a MagicDNS name through Vite's host check.
const allowedHosts = (process.env.PICKANDROLL_WEB_ALLOWED_HOSTS ?? "")
  .split(",")
  .map((h) => h.trim())
  .filter(Boolean);

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: process.env.PICKANDROLL_WEB_HOST || undefined,
    allowedHosts: allowedHosts.length ? allowedHosts : undefined,
    proxy: {
      "/api": {
        target: process.env.PICKANDROLL_API ?? "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
