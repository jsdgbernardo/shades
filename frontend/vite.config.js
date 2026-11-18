import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The app calls /api/* on its own origin; Vite passes those requests to the Python API, which
// stays bound to 127.0.0.1. This lets one public https link (a Cloudflare tunnel) serve both.
const api = {
  "/api": { target: `http://127.0.0.1:${process.env.SHADES_API_PORT || 8000}`, changeOrigin: true },
};
// Vite refuses requests for unknown host names; allow Cloudflare quick-tunnel links.
const allowedHosts = [".trycloudflare.com"];

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: api,
    allowedHosts,
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
    proxy: api,
    allowedHosts,
  },
});
