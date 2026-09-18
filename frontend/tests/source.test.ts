import { describe, expect, it } from "vitest";
import cases from "./fixtures/source.json";
import { canonicalize, canonicalizeFiles, decodeImported } from "../src/lib/domain/source";

describe("the canonical form of a source", () => {
  it("REALLY READS THE SHARED FIXTURE", () => {
    expect(cases.encoding.length).toBeGreaterThanOrEqual(6);
    expect(cases.dead_whitespace.length).toBeGreaterThanOrEqual(5);
    expect(cases.untouched.length).toBeGreaterThanOrEqual(7);
  });

  it("removes the BOM and turns line endings into LF", () => {
    for (const c of cases.encoding) {
      expect(canonicalize(c.in), c.why).toBe(c.out);
      expect(decodeImported(c.in), c.why).toBe(c.out);
    }
  });

  it("trims dead whitespace at line ends, except on a continuation", () => {
    for (const c of cases.dead_whitespace) expect(canonicalize(c.in), c.why).toBe(c.out);
  });

  it("STAYS SILENT ON EVERYTHING ELSE -- that is the half that makes it invisible", () => {
    for (const c of cases.untouched) {
      expect(c.out, "this case must be a fixed point").toBe(c.in);
      expect(canonicalize(c.in), c.why).toBe(c.in);
    }
  });

  it("\"open a file\" ACTUALLY DOES LESS, deliberately", () => {
    for (const c of cases.dead_whitespace) expect(decodeImported(c.in), c.why).toBe(c.in);
  });

  it("NEVER CHANGES THE LINE COUNT, and can only shorten", () => {
    for (const c of [...cases.encoding, ...cases.dead_whitespace, ...cases.untouched]) {
      const got = canonicalize(c.in);
      if (!c.in.includes("\r")) {
        expect(got.split("\n").length, c.why).toBe(c.in.split("\n").length);
      }
      expect(got.length, c.why).toBeLessThanOrEqual(c.in.length);
      expect(canonicalize(got), "idempotence: " + c.why).toBe(got);
    }
  });

  it("applies file by file, into a NEW object", () => {
    const source = { "calendrier.h": "int f(void);  \n", "calendrier.c": "int f(void){\r\n}\r\n" };
    const out = canonicalizeFiles(source);
    expect(out).toEqual({ "calendrier.h": "int f(void);\n", "calendrier.c": "int f(void){\n}\n" });
    expect(source["calendrier.h"]).toBe("int f(void);  \n");
  });
});
