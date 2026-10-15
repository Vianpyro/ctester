import { flushSync } from "svelte";

// The page's View Transitions. Reduced motion is the stylesheet's business: app.css drops every
// ::view-transition animation, so the swap is simply instant. No API (jsdom, older browsers):
// the update runs synchronously, exactly as before.
export function transit(kind: string, update: () => void): void {
  document.documentElement.dataset.vt = kind;
  if (document.startViewTransition) document.startViewTransition(() => flushSync(update));
  else update();
}
