import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vitest/config";

// THE PAGE IS BUILT, THE API IS NOT. `frontend/` is the whole frontend root;
// the build output is a static bundle GitHub Pages serves at the apex of
// `tch009.thevhome.com` (see frontend/public/CNAME). Nothing here runs on a
// server -- there is no SSR, no prerender step and no Node process in
// production.
export default defineConfig({
  root: "frontend",
  // THE CUSTOM DOMAIN SERVES THE PAGE AT `/`, so absolute asset paths are
  // right. It is NOT `/ctester/`: the CNAME means Pages does not prefix the
  // repository name. `base` is also what `app/routers/page.py` assumes when it
  // serves the built bundle for `python3 app/main.py`.
  base: "/",
  plugins: [svelte()],
  // COMPONENTS ARE MOUNTED IN THE TEST SUITE, so Svelte has to resolve to its BROWSER
  // build there. Without this condition it resolves to the server build and `mount()`
  // refuses to run -- which would quietly cost the one check that proves the page actually
  // starts. Guarded on `VITEST` so the production build is untouched.
  resolve: process.env.VITEST ? { conditions: ["browser"] } : {},
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // NO INLINE SCRIPT, EVER. The document's CSP is `script-src 'self'` and it
    // exists in two copies (the `<meta>` here and the header `app/csp.py`
    // sets); a `<meta>` cannot carry a hash computed on the served body, so an
    // inline script would have to be hashed by hand and would go stale
    // silently. Vite's module-preload polyfill is the only inline script it
    // emits, and this turns it off -- every browser this course runs on
    // supports modulepreload natively.
    modulePreload: { polyfill: false },
    // Inlining a small asset turns it into a `data:` URI inside CSS or JS.
    // `img-src 'self'` refuses those, so nothing may be inlined.
    assetsInlineLimit: 0,
    // Source maps ship: the page is 30 KB of our own code, students and
    // whoever debugs a production report both benefit, and there is no
    // proprietary anything in it.
    sourcemap: true,
  },
  test: {
    environment: "jsdom",
    // A TIMEZONE THAT IS NOT UTC, DELIBERATELY: the forum renders instants in
    // the reader's zone, and under UTC those tests would prove nothing.
    include: ["tests/**/*.test.ts"],
    setupFiles: ["tests/setup.ts"],
  },
});
