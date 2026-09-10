// THE ENTRY POINT. It mounts the application and nothing else.
//
// The stylesheet is imported here so Vite emits it as a `<link rel="stylesheet">` in the
// built document: `style-src 'self'` covers that, and the CSP needs no hash for it.
//
// THE THEME IS NOT SET HERE. A module script is deferred by spec, so this runs AFTER the
// first paint -- `frontend/public/theme.js` is what avoids the dark-to-light flash, and it
// is a classic script for exactly that reason.
//
// IT MOUNTS ONTO `document.body`, NOT INTO A WRAPPER, and that is a layout contract rather
// than a preference: `body` is the flex column, and `#top` and `<main>` have to be ITS
// children for the bar to size to content and the workbench to take the rest. A wrapper
// div in between collapses the whole page to content height.

import { mount } from "svelte";
import App from "./App.svelte";
import "./app.css";

export default mount(App, { target: document.body });
