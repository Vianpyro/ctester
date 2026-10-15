// Motion helpers for the deferred chunks only: nothing eager imports this module, so none of it
// counts against the anonymous budget. jsdom has no matchMedia, which reads as "keep still".
// No Svelte transitions (in:, out:, animate:) anywhere: Rolldown hoists their runtime into the
// eager chunk it shares with every screen. Web Animations do the same work for nothing.
export const still = (): boolean =>
  typeof matchMedia !== "function" || matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Eases `step` from `from` to `to`, instantly when still. Returns a canceller for `$effect`. */
export function tween(from: number, to: number, ms: number, step: (value: number) => void): () => void {
  if (still() || from === to) {
    step(to);
    return () => {};
  }
  const start = performance.now();
  let frame = requestAnimationFrame(function tick(now) {
    const k = Math.min(1, (now - start) / ms);
    step(from + (to - from) * (1 - (1 - k) ** 3));
    if (k < 1) frame = requestAnimationFrame(tick);
  });
  return () => cancelAnimationFrame(frame);
}
