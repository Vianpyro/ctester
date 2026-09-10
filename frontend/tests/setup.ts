// A TIMEZONE THAT IS NOT UTC, DELIBERATELY. The forum renders instants in the reader's
// zone and the hand-in file is dated in it: under UTC those checks would prove nothing,
// and dating a hand-in one day ahead is exactly the kind of detail that comes up out loud.
process.env.TZ = "America/Toronto";

import { beforeEach, vi } from "vitest";

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  vi.restoreAllMocks();
});
