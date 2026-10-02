import { describe, expect, it } from "vitest";
import { layout, type MetroLine, type MetroStation } from "../src/lib/domain/metro";

const FACTS = ["practiced", "solved", "labs", "solved_io", "skills", "tests", "days", "cards"];
const LINES: MetroLine[] = FACTS.map((on) => ({ on, name: on }));
// Like a real course: two to seven stations a line, the first few earned.
const STATIONS: MetroStation[] = FACTS.flatMap((on, i) =>
  Array.from({ length: 2 + (i % 6) }, (_, n) => ({
    id: `${on}-${n}`,
    on,
    unlocked_at: n < i % 3 ? "2026-09-03" : null,
  })),
);

describe("the metro layout", () => {
  for (const columns of [5, 7, 10]) {
    it(`places every station on its own cell, one step apart, never upward (${columns} columns)`, () => {
      const map = layout(LINES, STATIONS, columns);
      expect(map.nodes.filter((n) => n.kind !== "start")).toHaveLength(STATIONS.length);
      const cells = map.nodes.map((n) => n.at.join(","));
      expect(new Set(cells).size).toBe(cells.length);
      for (const n of map.nodes) {
        expect(n.at[0]).toBeGreaterThanOrEqual(0);
        expect(n.at[0]).toBeLessThan(columns);
        expect(n.at[1]).toBeLessThan(map.rows);
      }
      for (const s of map.segments) {
        expect(Math.abs(s.from[0] - s.to[0]) + Math.abs(s.from[1] - s.to[1])).toBe(1);
        expect(s.to[1]).toBeGreaterThanOrEqual(s.from[1]);
      }
    });
  }

  it("draws the same map every time for the same content", () => {
    expect(layout(LINES, STATIONS, 8)).toEqual(layout(LINES, STATIONS, 8));
  });

  it("leaves a line's start sideways, keeping the cell below for its name", () => {
    const map = layout(LINES, STATIONS, 8);
    const cells = new Set(map.nodes.map((n) => n.at.join(",")));
    for (const start of map.nodes.filter((n) => n.kind === "start")) {
      expect(cells.has(`${start.at[0]},${start.at[1] + 1}`)).toBe(false);
    }
  });

  it("lights a line up to what is earned, points at the next station and ends on a flag", () => {
    const map = layout(LINES, STATIONS, 8);
    const solved = map.nodes.filter((n) => n.line === "labs" && n.kind !== "start");
    expect(solved.map((n) => n.state)).toEqual(["earned", "earned", "next", "locked"]);
    expect(solved.map((n) => n.kind)).toEqual(["station", "station", "station", "flag"]);
    const lit = map.segments.filter((s) => s.line === "labs").map((s) => s.lit);
    expect(lit).toEqual([true, true, false, false]);
  });

  it("links every line after the first, colours each one, and skips a line with no station", () => {
    const map = layout([...LINES, { on: "comebacks", name: "x", color: "teal" }], STATIONS, 8);
    expect(map.links).toHaveLength(FACTS.length - 1);
    expect(map.nodes.some((n) => n.line === "comebacks")).toBe(false);
    const colours = new Set(map.nodes.filter((n) => n.kind === "start").map((n) => n.color));
    expect(colours.size).toBe(FACTS.length);
    expect(layout([{ on: "solved", name: "s", color: "teal" }], STATIONS, 8).nodes[0]!.color).toBe("teal");
  });
});
