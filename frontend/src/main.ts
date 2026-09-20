import { mount } from "svelte";
import App from "./App.svelte";
import "./app.css";

// After load, so it never competes with the first paint. public/sw.js holds the rules;
// a browser without one, or a refusal, simply leaves the page unaccelerated.
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  addEventListener("load", () => void navigator.serviceWorker.register("/sw.js").catch(() => {}));
}

// No wrapper element: <body> is the flex column the layout relies on.
export default mount(App, { target: document.body });
