import { afterEach, describe, expect, it, vi } from "vitest";
import { transit } from "../src/lib/transit";
import { still, tween } from "../src/lib/motion";
import { play } from "../src/lib/verdictFx";

type WithTransitions = { startViewTransition?: (update: () => void) => unknown };

afterEach(() => {
  vi.unstubAllGlobals();
  delete (document as WithTransitions).startViewTransition;
  delete document.documentElement.dataset.vt;
  document.body.innerHTML = "";
});

describe("the View Transition hook", () => {
  it("updates at once where the browser has no View Transitions, as jsdom", () => {
    let shown = "";
    transit("in", () => (shown = "progress"));
    expect(shown).toBe("progress");
    expect(document.documentElement.dataset.vt).toBe("in");
  });

  it("hands the update to the browser's transition, which names its kind", () => {
    const start = vi.fn((update: () => void) => update());
    (document as WithTransitions).startViewTransition = start;
    let theme = "dark";
    transit("theme", () => (theme = "light"));
    expect(start).toHaveBeenCalledOnce();
    expect(theme).toBe("light");
    expect(document.documentElement.dataset.vt).toBe("theme");
  });
});

describe("the deferred motion", () => {
  it("keeps still without matchMedia, and whenever reduced motion is asked", () => {
    expect(still()).toBe(true);
    vi.stubGlobal("matchMedia", () => ({ matches: false }));
    expect(still()).toBe(false);
    vi.stubGlobal("matchMedia", () => ({ matches: true }));
    expect(still()).toBe(true);
  });

  it("lands a tween on its target at once when still, so a count is never left halfway", () => {
    const seen: number[] = [];
    tween(0, 1240, 1100, (value) => seen.push(value));
    expect(seen).toEqual([1240]);
  });

  it("celebrates nothing when still", () => {
    document.body.innerHTML = '<div id="out" class="ok"><div class="verdict ok count">8 / 8</div></div>';
    play();
    expect(document.querySelector(".burst")).toBeNull();
  });
});
