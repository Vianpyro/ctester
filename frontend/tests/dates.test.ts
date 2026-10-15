import { describe, expect, it } from "vitest";
import { dayOf } from "../src/lib/domain/dates";

describe("a day a student can read", () => {
  it("writes the server's instant as a day, in the page's language", () => {
    const day = dayOf("2026-10-15T14:00:00Z");
    expect(day).toContain("2026");
    expect(day).toContain("octobre");
    expect(day).not.toContain("T14");
  });

  it("says nothing for what is not a date, rather than echoing it", () => {
    expect(dayOf("held")).toBe("");
    expect(dayOf(null)).toBe("");
  });
});
