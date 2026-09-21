import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { shapeNote } from "../src/lib/domain/answerShape";

interface Case {
  type: string;
  given: string;
  formed: boolean;
}

// The same file the judge reads: what the page calls malformed, the judge must be unable
// to call right.
const cases: Case[] = JSON.parse(
  readFileSync(join(import.meta.dirname, "..", "..", "tests", "vectors", "answer_shape.json"), "utf8"),
).cases;

describe("the shape of an answer, against the shared vectors", () => {
  it("covers every type the page can check", () => {
    expect(new Set(cases.map((one) => one.type))).toEqual(
      new Set(["bin8", "bin", "hex8", "int", "number"]),
    );
  });

  for (const one of cases) {
    it(`${one.type} ${JSON.stringify(one.given)} is ${one.formed ? "formed" : "not"}`, () => {
      expect(shapeNote(one.type, one.given) === "").toBe(one.formed);
    });
  }
});

describe("what the shape check refuses to say", () => {
  it("says nothing about an empty field: a blank is not a mistake, it is unfinished", () => {
    for (const type of ["bin8", "bin", "hex8", "int", "number"]) {
      expect(shapeNote(type, "")).toBe("");
      expect(shapeNote(type, "   ")).toBe("");
    }
  });

  it("says nothing about the types that have no shape to check", () => {
    for (const type of ["choice", "multi", "bool", "match", "order", "cloze", "text"]) {
      expect(shapeNote(type, "n'importe quoi")).toBe("");
    }
  });

  it("counts the bits it found, so the note says what to fix", () => {
    expect(shapeNote("bin8", "1011101")).toBe("7 bits sur 8");
    expect(shapeNote("bin8", "1")).toBe("1 bit sur 8");
  });
});
