import { describe, expect, it } from "vitest";
import { tier } from "../src/lib/domain/rarity";

describe("tier", () => {
  it("stays neutral until the server publishes a measured rarity", () => {
    expect(tier(null)).toBe(0);
    expect(tier(undefined)).toBe(0);
  });

  it("brightens as fewer accounts hold the card, bounds included", () => {
    expect([0, 10, 11, 25, 26, 50, 51, 100].map(tier)).toEqual([4, 4, 3, 3, 2, 2, 1, 1]);
  });
});
