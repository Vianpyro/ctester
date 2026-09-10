// THE ENTRY POINT. It mounts the application and nothing else.
//
// The stylesheet is imported here so Vite emits it as a `<link rel="stylesheet">` in the
// built document: `style-src 'self'` covers that, and the CSP needs no hash for it.
//
// THE THEME IS NOT SET HERE. A module script is deferred by spec, so this runs AFTER the
// first paint -- `frontend/public/theme.js` is what avoids the dark-to-light flash, and it
// is a classic script for exactly that reason.

import { mount } from "svelte";
import App from "./App.svelte";
import "./app.css";

const target = document.getElementById("app");
if (!target) throw new Error("le point de montage #app est absent du document");

export default mount(App, { target });
