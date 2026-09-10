// THE ONLY SCRIPT THAT RUNS BEFORE THE FIRST PAINT, and the only reason it is
// a separate file.
//
// It is NOT inline, and that is deliberate: served by GitHub Pages this
// document can carry no header, so its CSP lives in a `<meta>` -- and a
// `<meta>` cannot carry a hash computed on the served body. Copying a hash by
// hand goes stale at the first changed comma, silently, and takes the theme
// down with it. `script-src 'self'` needs no hash, and an inline script added
// by mistake is then blocked loudly.
//
// It is NOT part of the bundle either: a `<script type="module">` is deferred
// by spec, so the main bundle always runs AFTER the first paint. Reading the
// theme there would bring back the dark-to-light flash this file exists to
// avoid. A classic `<script src>` with no `defer` blocks rendering until it
// runs, which is exactly what is wanted, and costs one request on an
// already-open connection for a file of four lines.
//
// It stays in `public/` so Vite copies it verbatim, under a stable name --
// `app/routers/page.py` allow-lists that name.
try {
  var t = localStorage.getItem("ctester.theme");
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
} catch (e) {}
