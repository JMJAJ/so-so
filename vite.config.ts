// The shared config package already includes: tanstackStart, viteReact,
// tailwindcss, tsConfigPaths, nitro (build-only, cloudflare target),
// componentTagger (dev-only), VITE_* env injection, @ path alias,
// React/TanStack dedupe, error logger plugins, and sandbox detection.
// Do NOT add those manually or the app will break with duplicate plugins.
import { defineConfig } from "@lovable.dev/vite-tanstack-config";

export default defineConfig({
  tanstackStart: {
    server: { entry: "server" },
    // Static single-page build (dist/client) so any static host can serve it; /api is proxied
    // to the Python backend by the dev server locally and by vercel.json in production.
    spa: { enabled: true },
  },
  vite: {
    build: {
      rolldownOptions: {
        output: {
          codeSplitting: {
            groups: [
              {
                name: "react-core",
                test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/,
                priority: 30,
              },
              {
                name: "tanstack",
                test: /node_modules[\\/]@tanstack[\\/]/,
                priority: 20,
              },
              {
                name: "terminal-ui",
                test: /node_modules[\\/](@radix-ui|lucide-react|sonner)[\\/]/,
                priority: 15,
              },
              {
                name: "vendor",
                test: /node_modules[\\/]/,
                maxSize: 240 * 1024,
                priority: 10,
              },
            ],
          },
        },
      },
    },
    server: {
      proxy: {
        "/api": {
          target: "http://localhost:8000",
          changeOrigin: true,
          configure: (proxy, _options) => {
            proxy.on("error", (err, _req, _res) => {
              console.log("[Proxy Error] Python backend not running on port 8000:", err.message);
              console.log(
                "[Proxy Error] Start backend with: cd server && uvicorn main:app --reload",
              );
            });
          },
        },
      },
    },
  },
});
