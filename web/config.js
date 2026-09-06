// THE PAGE'S FIRST SCRIPT, AND THE ONLY ONE THAT RUNS BEFORE THE FIRST PAINT.
// It carries two startup settings: the theme and the API's address.
//
// IT IS EXTERNAL AND NOT INLINE, AND THAT IS DELIBERATE. Served by GitHub
// Pages, this document can carry no header: its CSP therefore goes into a
// <meta>, and a <meta> cannot carry a hash computed on the served body the
// way `csp()` used to. The choice was between copying a hash by hand --
// which goes stale silently at the first changed comma, and takes the theme
// down with it -- and having no inline script left at all. The second option
// removes the problem instead of adding a test to watch it: `script-src
// 'self'` is enough, no hash needed, and an inline script added by mistake
// is THEN blocked loudly.
//
// Loaded WITHOUT `defer` at the very top of <head>: a plain <script src>
// blocks rendering until it runs, so the theme is set before the first paint
// exactly as the inline script used to do it. What it costs is one request
// on an already-open connection, for a one-kilobyte file.
try {
  var t = localStorage.getItem("ctester.theme");
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
} catch (e) {}

// THE API'S ADDRESS, ONE SINGLE PLACE. No build step, no substitution: what
// the repo contains is what the browser gets.
//
// The page ships from GitHub Pages under `tch009.thevhome.com` -- the name
// students know, unchanged, so their `localStorage` drafts and Rauthy's
// `redirect_uri` stay unchanged too. Only the API moves, under a name only
// it knows.
//
// `tch099` and not `api.tch009`: Cloudflare's universal certificate covers
// `thevhome.com` and `*.thevhome.com`, ONE single label. `api.tch009` makes
// two and would have no valid certificate without Advanced Certificate
// Manager.
window.CTESTER_API = (() => {
  const h = location.hostname;
  // THE PAGE'S TWO ORIGINS both point at the same API. `tch009` is the name
  // students know, served by GitHub Pages; `github.io` is the staging
  // deployment, used to exercise the page before the DNS switch.
  if (h === "tch009.thevhome.com") return "https://tch099.thevhome.com";
  if (h.endsWith(".github.io")) return "https://tch099.thevhome.com";
  // Local development: `app/main.py` still serves the page, so relative
  // paths. This fallback is what keeps `CTESTER_PAGE=web python3 app/main.py`
  // alive, and what makes the switch reversible by changing one line.
  return "";
})();

// The prefix for API calls, and nothing else. The on-demand modules and the
// two vendor libraries live on Pages, next to this page: they stay relative,
// `charger()` does not change.
window.API = (path) => window.CTESTER_API ? window.CTESTER_API + "/" + path
                                          : path;
