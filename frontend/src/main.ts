import { mount } from "svelte";
import App from "./App.svelte";
import { i18n } from "./lib/i18n.svelte";
import "./app.css";

// After load, so it never competes with the first paint. public/sw.js holds the rules;
// a browser without one, or a refusal, simply leaves the page unaccelerated.
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  addEventListener("load", () => void navigator.serviceWorker.register("/sw.js").catch(() => {}));
}

// The strings come first: mounting without them would flash every key. No wrapper element:
// <body> is the flex column the layout relies on.
void i18n.load(i18n.initial()).then(() => mount(App, { target: document.body }));
