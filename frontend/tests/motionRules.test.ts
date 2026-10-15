import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const CSS = readFileSync(join(import.meta.dirname, "..", "src", "app.css"), "utf8");

// Every loop that never ends, by the name of its keyframes.
const endless = [...CSS.matchAll(/animation:\s*([a-z-]+)[^;]*\binfinite\b/g)].map((m) => m[1]!);

describe("the stylesheet's motion charter", () => {
  it("lets nothing loop forever but a loading indicator (WCAG 2.2.2)", () => {
    // scan, comet, pulse-run and beacon: a test is out. sheen: Test is busy. underway: a
    // screen is on its way. Nothing else may keep moving beside the code.
    const loading = ["scan", "comet", "sheen", "pulse-run", "beacon", "underway"];
    expect(endless.length).toBeGreaterThan(0);
    for (const name of endless) expect(loading, name).toContain(name);
  });

  it("keeps the invitations it trimmed bounded, not removed", () => {
    expect(CSS).toMatch(/animation:\s*respire [^;]*\s1;/);
    expect(CSS).toMatch(/animation:\s*ping [^;]*\s1;/);
    expect(CSS).toMatch(/station 2\.4s ease-in-out calc\(var\(--at\) \+ 400ms\) 2;/);
  });

  it("collapses every duration under prefers-reduced-motion", () => {
    const reduce = CSS.split("@media (prefers-reduced-motion: reduce)")[1] ?? "";
    for (const token of ["--t-1", "--t-2", "--t-3", "--t-4", "--t-5"]) {
      expect(reduce, token).toMatch(new RegExp(token + ":\\s*1ms"));
    }
  });
});
