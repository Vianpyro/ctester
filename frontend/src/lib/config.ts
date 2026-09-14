function apiOrigin(): string {
  const host = typeof location === "undefined" ? "" : location.hostname;
  if (host === "tch009.thevhome.com") return "https://tch099.thevhome.com";
  if (host.endsWith(".github.io")) return "https://tch099.thevhome.com";
  return "";
}

export const API_ORIGIN = apiOrigin();

export const api = (path: string): string =>
  API_ORIGIN ? API_ORIGIN + "/" + path : path;

export function socketUrl(path: string): string {
  if (API_ORIGIN) return API_ORIGIN.replace(/^http/, "ws") + path;
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return scheme + "//" + location.host + path;
}
