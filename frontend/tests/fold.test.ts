import { beforeEach, describe, expect, it, vi } from "vitest";
import { foldToFit } from "../src/lib/fold";

// A bar as base.css folds it: every level gives up 100px of what it needs on one row.
function barNeeding(needs: number, room: { width: number }): HTMLElement {
  const bar = document.createElement("div");
  const levels = () => (bar.dataset.fold ?? "").split(" ").filter(Boolean).length;
  Object.defineProperty(bar, "clientWidth", { get: () => room.width });
  Object.defineProperty(bar, "scrollWidth", { get: () => Math.max(room.width, needs - 100 * levels()) });
  return bar;
}

describe("the bar's fold", () => {
  let resized = () => {};

  beforeEach(() => {
    // jsdom has no ResizeObserver: this one hands its callback to the test.
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(callback: () => void) {
          resized = callback;
        }
        observe() {}
        disconnect() {}
      },
    );
  });

  it("stops at the first level that fits, and unfolds when the room comes back", () => {
    const room = { width: 1000 };
    const bar = barNeeding(1250, room);
    foldToFit(bar, 8);
    expect(bar.dataset.fold).toBe(" 1 2 3");

    room.width = 2000;
    resized();
    expect(bar.dataset.fold).toBe("");
  });

  it("goes no further than its last level, whatever is left over", () => {
    const bar = barNeeding(5000, { width: 300 });
    foldToFit(bar, 8);
    expect(bar.dataset.fold).toBe(" 1 2 3 4 5 6 7 8");
  });

  it("folds again when what the bar holds changes, and leaves it able to wrap", async () => {
    const room = { width: 1000 };
    const bar = barNeeding(900, room);
    bar.style.flexWrap = "wrap";
    foldToFit(bar, 8);
    expect(bar.dataset.fold).toBe("");

    room.width = 750;
    bar.textContent = "a longer name";
    await Promise.resolve();
    expect(bar.dataset.fold).toBe(" 1 2");
    expect(bar.style.flexWrap).toBe("wrap");
  });
});
