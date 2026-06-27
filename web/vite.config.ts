import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiPort = process.env.SKILLROUTE_UI_PORT ?? "8765";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": `http://127.0.0.1:${apiPort}`
    }
  }
});
