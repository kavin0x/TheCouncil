import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(process.cwd()) },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: [path.resolve(process.cwd(), "config/testing/vitest.setup.ts")],
    exclude: ["__tests__/e2e/**", "node_modules/**"],
  },
});
