import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { VitePWA } from "vite-plugin-pwa";

// Dev: /api/* is proxied to FastAPI (the prefix is stripped). Production: FastAPI serves this build and mounts the API at /api.
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: "autoUpdate",
      injectRegister: "script-defer",
      includeAssets: ["favicon.png", "icon.svg", "apple-touch-icon.png", "theme-init.js"],
      manifest: {
        id: "/",
        name: "Veyra: competitive intelligence",
        short_name: "Veyra",
        description: "Hypothesis-driven competitive intelligence that tests its own conclusions.",
        start_url: "/",
        scope: "/",
        display: "standalone",
        display_override: ["window-controls-overlay", "standalone"],
        orientation: "any",
        background_color: "#040d20",
        theme_color: "#06122a",
        categories: ["business", "productivity"],
        icons: [
          { src: "/pwa-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
          { src: "/pwa-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
          { src: "/pwa-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
        shortcuts: [
          { name: "Ask Veyra", url: "/ask", icons: [{ src: "/pwa-192.png", sizes: "192x192" }] },
          { name: "Intelligence Feed", url: "/feed", icons: [{ src: "/pwa-192.png", sizes: "192x192" }] },
          { name: "Hypotheses", url: "/hypotheses", icons: [{ src: "/pwa-192.png", sizes: "192x192" }] },
        ],
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,svg,png,ico}"],
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api\//, /^\/healthz/],
        cleanupOutdatedCaches: true,
        runtimeCaching: [
          { // fonts: cache on first use (all unicode subsets would bloat the precache)
            urlPattern: ({ request }) => request.destination === "font",
            handler: "CacheFirst",
            options: { cacheName: "veyra-fonts", expiration: { maxEntries: 40, maxAgeSeconds: 60 * 60 * 24 * 365 } },
          },
          // /api/* is deliberately NOT cached: it's private data behind a login and must always be fresh.
        ],
      },
      devOptions: { enabled: false },
    }),
  ],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8000", rewrite: (p) => p.replace(/^\/api/, "") } },
  },
  build: { sourcemap: false, chunkSizeWarningLimit: 900 },
});
