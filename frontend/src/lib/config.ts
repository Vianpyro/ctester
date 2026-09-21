// The API origin is a deployment setting, not a hostname the app knows. It is baked at
// build time by the plugin in vite.config.ts, the same value the CSP in index.html names:
// a page served from the API's own origin leaves it empty and uses relative paths.
declare const __API_ORIGIN__: string;
declare const __TITLE__: string;

function apiOrigin(): string {
  const configured = typeof __API_ORIGIN__ === "string" ? __API_ORIGIN__ : "";
  if (!configured) return "";
  // Same origin as the page: relative paths are shorter and dodge CORS entirely.
  if (typeof location !== "undefined" && location.origin === configured) return "";
  return configured;
}

export const API_ORIGIN = apiOrigin();

// What this instance is called. A course sets it; the engine calls itself CTester.
export const TITLE =
  (typeof __TITLE__ === "string" && __TITLE__) || "CTester";

export const api = (path: string): string =>
  API_ORIGIN ? API_ORIGIN + "/" + path : path;

export function socketUrl(path: string): string {
  if (API_ORIGIN) return API_ORIGIN.replace(/^http/, "ws") + path;
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return scheme + "//" + location.host + path;
}
