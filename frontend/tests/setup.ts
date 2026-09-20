process.env.TZ = "America/Toronto";

import { beforeEach, vi } from "vitest";

// jsdom ships no ResizeObserver, and the quiz panel measures itself with one. Nothing
// resizes in a test, so observing is enough: a stub that never fires is the real behaviour.
if (!("ResizeObserver" in globalThis)) {
  globalThis.ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  } as unknown as typeof ResizeObserver;
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  vi.restoreAllMocks();
});
