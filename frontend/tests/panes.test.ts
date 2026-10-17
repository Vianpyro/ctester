import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const read = (name: string) => readFileSync(join(import.meta.dirname, "..", "src", "styles", name), "utf8");

// The area names in the first `grid-template` of the rule for `selector`.
function areas(css: string, selector: string): string[] {
  const rule = new RegExp("(?:^|\\n)\\s*" + selector + "\\s*\\{[^}]*?grid-template:([^;]*);").exec(css);
  expect(rule, selector + " has no grid-template").not.toBeNull();
  return [...rule![1]!.matchAll(/"([^"]+)"/g)].flatMap((row) => row[1]!.trim().split(/\s+/));
}

describe("the bench's areas", () => {
  it("are the same names on a wide bench and in a phone's panes", () => {
    // The parts of #right are placed by name: on a phone #right steps aside and #work lays the
    // same names out as panes, plus the statement's own. A name missing on either side would
    // leave a part in an implicit cell, off the screen.
    const bench = new Set(areas(read("bench.css"), "#right"));
    const panes = new Set(areas(read("layout.css"), "#work"));
    expect(panes.delete("st")).toBe(true);
    expect([...panes].sort()).toEqual([...bench].sort());
  });
});
