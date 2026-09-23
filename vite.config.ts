import { existsSync, readFileSync } from "node:fs";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig, type Plugin } from "vitest/config";

const trim = (value: string) => value.replace(/\/+$/, "");

// One knob per deployment, and index.html carries no hostname of its own. The wss:// form
// is derived here rather than configured, so the two can never disagree.
// Unit tests assert the engine's own behaviour, so they never inherit a deployment's
// values; the bundle tests read the real build, which is not a vitest run.
const setting = (name: string) => (process.env.VITEST ? "" : process.env[name] ?? "");

const API = trim(setting("CTESTER_API_ORIGIN"));
const AUTH = trim(setting("CTESTER_AUTH_ORIGIN"));
// The instance's language, for <html lang> and the tab's title before the page runs.
// en.json is the source every other language falls back to.
const locale = (lang: string): Record<string, string> => {
  const path = `frontend/src/locales/${lang}.json`;
  return existsSync(path) ? JSON.parse(readFileSync(path, "utf8")) : {};
};
const LANG = setting("CTESTER_LANG") || "en";
if (!existsSync(`frontend/src/locales/${LANG}.json`)) {
  throw new Error(`CTESTER_LANG="${LANG}" has no frontend/src/locales/${LANG}.json.`);
}
// The header prints the name and the tagline side by side, and index.html joins them for
// the tab. A title carrying the whole sentence shows it twice, which is easy to do and
// invisible until someone looks at the page.
const TAGLINE = locale(LANG)["app.tagline"] ?? locale("en")["app.tagline"] ?? "";
const TITLE = setting("CTESTER_TITLE") || "CTester";
if (TAGLINE && TITLE.includes(TAGLINE)) {
  throw new Error(
    `CTESTER_TITLE must be the instance's name alone, not "${TITLE}": ` +
      `"${TAGLINE}" is already shown next to it.`,
  );
}
const DOMAIN = trim(setting("CTESTER_PAGES_DOMAIN"));

export const SUBSTITUTIONS: Record<string, string> = {
  "%API_ORIGIN%": API,
  "%API_WS%": API ? "wss://" + API.split("://")[1] : "",
  "%AUTH_ORIGIN%": AUTH,
  "%TITLE%": TITLE,
  "%TAGLINE%": TAGLINE,
  "%LANG%": LANG,
};

function deployment(): Plugin {
  return {
    name: "ctester-deployment",
    transformIndexHtml(html: string) {
      for (const [token, value] of Object.entries(SUBSTITUTIONS)) {
        html = html.split(token).join(value);
      }
      // An empty origin leaves a bare preconnect, which the browser ignores but which is
      // noise in the document; drop the hint rather than emit it pointing nowhere.
      html = html.replace(/^\s*<link rel="(?:preconnect|dns-prefetch)" href=""[^>]*>\n/gm, "");
      // An unset token leaves a gap in the CSP list. Close it, so the served policy reads
      // exactly like the one app/csp.py builds.
      return html.replace(
        /(<meta http-equiv="Content-Security-Policy" content=")([^"]*)(")/,
        (_, open, policy: string, close) =>
          open + policy.replace(/ {2,}/g, " ").replace(/ +;/g, ";").trim() + close,
      );
    },
    generateBundle() {
      // GitHub Pages reads CNAME from the published root. No domain configured, no file.
      if (DOMAIN) {
        this.emitFile({ type: "asset", fileName: "CNAME", source: DOMAIN + "\n" });
      }
    },
  };
}

export default defineConfig({
  root: "frontend",
  base: "/",
  plugins: [svelte(), deployment()],
  define: {
    __API_ORIGIN__: JSON.stringify(API),
    __TITLE__: JSON.stringify(TITLE),
    __LANG__: JSON.stringify(LANG),
  },
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
