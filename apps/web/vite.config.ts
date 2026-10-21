import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";

// Two pages: the static landing page at "/" (index.html) and the workbench SPA at "/app" (app/index.html).
// Old workbench addresses from before the move (e.g. /queue, /cases/...) redirect to /app; vercel.json mirrors these rules.
const OLD_APP_PATHS = /^\/(queue|cases|network|agreements|audit|admin|supplier|ops)(\/|$|\?)/;

function appRouting(): Plugin {
  return {
    name: "nodal-app-routing",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = req.url ?? "/";
        if (OLD_APP_PATHS.test(url)) {
          res.statusCode = 302;
          res.setHeader("Location", `/app${url}`);
          res.end();
          return;
        }
        // Client-side routes under /app (no file extension) are served the app's HTML.
        if (/^\/app(\/[^.]*)?(\?.*)?$/.test(url) && req.headers.accept?.includes("text/html")) req.url = "/app/index.html";
        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), appRouting()],
  build: {
    rollupOptions: {
      input: {
        landing: fileURLToPath(new URL("./index.html", import.meta.url)),
        app: fileURLToPath(new URL("./app/index.html", import.meta.url)),
      },
    },
  },
  server: {
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: false } },
  },
});
