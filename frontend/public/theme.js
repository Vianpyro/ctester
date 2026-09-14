// Not inline (the CSP <meta> cannot carry a hash) and not in the bundle
// (module scripts are deferred, which would flash the wrong theme).
try {
  var t = localStorage.getItem("ctester.theme");
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
} catch (e) {}
