import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const backend = process.env.BACKEND_URL ?? "http://localhost:4000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    strictPort: true,
    proxy: {
      // The backend serves its routes unprefixed, as the specs name them.
      "/api": {
        target: backend,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
