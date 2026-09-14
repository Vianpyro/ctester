import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vitest/config";

export default defineConfig({
  root: "frontend",
  base: "/",
  plugins: [svelte()],
  // Component tests mount Svelte, which needs its browser build.
  resolve: process.env.VITEST ? { conditions: ["browser"] } : {},
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // The polyfill is an inline script, which the CSP blocks.
    modulePreload: { polyfill: false },
    // Inlined assets become data: URIs, which img-src refuses.
    assetsInlineLimit: 0,
    sourcemap: true,
  },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.ts"],
    setupFiles: ["tests/setup.ts"],
  },
});
