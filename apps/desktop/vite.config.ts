/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The packaged application loads built assets from disk through the Tauri protocol, so no
// development server, localhost origin, or bundler runtime survives into a release build.
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: { port: 5173, strictPort: true },
  build: { outDir: "dist", emptyOutDir: true, target: "chrome110", sourcemap: true },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx", "tests/**/*.test.ts"],
    // Generated contract guards run under the Node test runner, not Vitest.
    exclude: ["**/node_modules/**", "src/contracts/generated.test.ts"],
    setupFiles: ["src/shared/test/setup.ts"],
    restoreMocks: true,
    coverage: {
      provider: "v8",
      include: ["src/**/*.ts", "src/**/*.tsx"],
      exclude: ["src/contracts/**"],
    },
  },
});
