import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Dev: the API runs on :8000 and is reached through /api (proxy).
// Build: the app is served by FastAPI at /ui and calls the API on the same origin.
export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, ".", "");
  return {
    base: command === "build" ? "/ui/" : "/",
    plugins: [react(), tailwindcss()],
    server: {
      port: 5173,
      proxy: {
        "/api": {
          target: env.API_PROXY_TARGET || "http://localhost:8000",
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ""),
        },
      },
    },
  };
});
