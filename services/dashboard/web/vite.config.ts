import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev/preview proxy target. Defaults to a local backend; override to point dev
// at a remote deployment, e.g. VITE_PROXY_TARGET=http://192.168.5.100:8081
const target = process.env.VITE_PROXY_TARGET ?? "http://localhost:8080";
const wsTarget = target.replace(/^http/, "ws");
const proxy = {
  "/api": target,
  "/ws": { target: wsTarget, ws: true },
};

export default defineConfig({
  plugins: [react()],
  server: { proxy },
  preview: { proxy },
});
