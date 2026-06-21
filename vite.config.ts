// The shared config package already includes: tanstackStart, viteReact,
// tailwindcss, tsConfigPaths, nitro (build-only, cloudflare target),
// componentTagger (dev-only), VITE_* env injection, @ path alias,
// React/TanStack dedupe, error logger plugins, and sandbox detection.
// Do NOT add those manually or the app will break with duplicate plugins.
import { defineConfig } from "@lovable.dev/vite-tanstack-config";

export default defineConfig({
  tanstackStart: {
    server: { entry: "server" },
  },
  vite: {
    server: {
      proxy: {
        "/api": {
          target: "http://localhost:8000",
          changeOrigin: true,
          configure: (proxy, _options) => {
            proxy.on('error', (err, _req, _res) => {
              console.log('[Proxy Error] Python backend not running on port 8000:', err.message);
              console.log('[Proxy Error] Start backend with: cd server && uvicorn main:app --reload');
            });
          },
        },
      },
    },
  },
});
