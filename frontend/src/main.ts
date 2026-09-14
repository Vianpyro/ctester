import { mount } from "svelte";
import App from "./App.svelte";
import "./app.css";

// No wrapper element: <body> is the flex column the layout relies on.
export default mount(App, { target: document.body });
