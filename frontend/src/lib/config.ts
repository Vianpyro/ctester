// THE API'S ADDRESS, ONE SINGLE PLACE, and it describes what each deployment
// really is rather than the target.
//
//   tch009.thevhome.com  the page, served by GitHub Pages
//   tch099.thevhome.com  the API, served by the Dell behind Cloudflare
//
// `tch099` and not `api.tch009`: Cloudflare's universal certificate covers
// `thevhome.com` and `*.thevhome.com`, ONE single label. Two labels would need
// Advanced Certificate Manager.
//
// A BUILD-TIME VARIABLE WAS DELIBERATELY NOT USED. The rule is a function of
// the hostname the page is opened from, so one bundle serves Pages, the
// staging `github.io` deployment and `python3 app/main.py` -- and there is no
// way to deploy the wrong value.
function apiOrigin(): string {
  const host = typeof location === "undefined" ? "" : location.hostname;
  // The name students know, and the staging deployment used to exercise the
  // page before a DNS switch. Both point at the same API.
  if (host === "tch009.thevhome.com") return "https://tch099.thevhome.com";
  if (host.endsWith(".github.io")) return "https://tch099.thevhome.com";
  // Local development: `app/main.py` serves the built page AND the API on one
  // origin, so relative paths. Same fallback for `npm run dev`, where Vite's
  // proxy (see vite.config.ts is not used -- the dev server talks to whatever
  // origin it is opened on).
  return "";
}

export const API_ORIGIN = apiOrigin();

/** Prefix an API path, and nothing else. Never used for the page's own files. */
export const api = (path: string): string =>
  API_ORIGIN ? API_ORIGIN + "/" + path : path;

// http -> ws, https -> wss, honouring `API_ORIGIN` when the page is served
// from a different origin than the API. ONE copy for all three sockets: the
// forum bell, the team room and the Console.
export function socketUrl(path: string): string {
  if (API_ORIGIN) return API_ORIGIN.replace(/^http/, "ws") + path;
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return scheme + "//" + location.host + path;
}
