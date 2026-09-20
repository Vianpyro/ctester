import { describe, expect, it } from "vitest";
import { answered, packAll } from "../src/lib/domain/answer";
import { marksFor, pageStatus, sectionLabel, tableFor } from "../src/lib/domain/quizMarks";
import type { Verdict } from "../src/lib/api/types";

const graded = (wrong: { id: string; label: string; hint?: string }[]): Verdict => ({
  state: "done",
  status: "ok",
  kind: "quiz",
  total: 3,
  passed: 3 - wrong.length,
  wrong,
});

describe("the mark a question carries", () => {
  it("marks a graded question right when it is absent from the wrong list", () => {
    const answers = { a: "00010111", b: "42" };
    const marks = marksFor(graded([]), packAll(answers), answers);
    expect(marks.a).toEqual({ state: "right" });
    expect(marks.b).toEqual({ state: "right" });
  });

  it("carries the judge's hint on a wrong answer, never the expected value", () => {
    const answers = { a: "10111" };
    const marks = marksFor(
      graded([{ id: "a", label: "23", hint: "bonne valeur, mais l'énoncé demande 8 bits" }]),
      packAll(answers),
      answers,
    );
    expect(marks.a).toEqual({
      state: "wrong",
      hint: "bonne valeur, mais l'énoncé demande 8 bits",
    });
  });

  it("drops the mark as soon as the field no longer holds what was graded", () => {
    const sent = packAll({ a: "10111" });
    const marks = marksFor(graded([{ id: "a", label: "23" }]), sent, { a: "00010111" });
    expect(marks.a).toBeUndefined();
  });

  it("leaves a question that was never submitted unmarked", () => {
    const marks = marksFor(graded([]), packAll({ a: "1" }), { a: "1", b: "" });
    expect(marks.b).toBeUndefined();
  });

  it("marks questions from every section, since the server grades the whole quiz", () => {
    const answers = { p1: "1", p2: "2" };
    const marks = marksFor(graded([{ id: "p2", label: "b" }]), packAll(answers), answers);
    expect(marks.p1!.state).toBe("right");
    expect(marks.p2!.state).toBe("wrong");
  });

  it("marks nothing when the run did not grade -- a compile error is not a quiz result", () => {
    const answers = { a: "1" };
    const broken: Verdict = { state: "done", status: "error", kind: "quiz", message: "juge" };
    expect(marksFor(broken, packAll(answers), answers)).toEqual({});
    expect(marksFor(null, packAll(answers), answers)).toEqual({});
  });

  it("compares structured answers on their packed form", () => {
    const answers = { m: { x: "1" } };
    const sent = packAll(answers);
    expect(marksFor(graded([]), sent, answers).m).toEqual({ state: "right" });
    expect(marksFor(graded([]), sent, { m: { x: "2" } }).m).toBeUndefined();
  });
});

describe("what a section tile shows", () => {
  const answers = { a: "1", b: "", c: "3" };

  it("counts the filled fields, blanks apart", () => {
    expect(pageStatus(["a", "b", "c"], answers, {})).toEqual({
      answered: 2,
      total: 3,
      state: "unknown",
    });
  });

  it("calls a section wrong as soon as one of its questions is", () => {
    const marks = { a: { state: "right" as const }, c: { state: "wrong" as const } };
    expect(pageStatus(["a", "b", "c"], answers, marks).state).toBe("wrong");
  });

  it("calls a section right only when every one of its questions is marked right", () => {
    const all = { a: { state: "right" as const }, c: { state: "right" as const } };
    expect(pageStatus(["a", "c"], answers, all).state).toBe("right");
    expect(pageStatus(["a", "b", "c"], answers, all).state).toBe("unknown");
  });

  it("holds an empty section to unknown rather than declaring it right", () => {
    expect(pageStatus([], answers, {}).state).toBe("unknown");
  });
});

describe("the tile's short label", () => {
  it("keeps the stem of a heading and drops its description", () => {
    expect(sectionLabel("Exercice 1 : décimal vers binaire (8 bits)")).toBe("Exercice 1");
    expect(sectionLabel("Exercice 2 — masques sur 8 bits")).toBe("Exercice 2");
  });

  it("truncates a heading that has no stem to cut", () => {
    expect(sectionLabel("Conversions et masques binaires")).toBe("Conversions et masque…");
    expect(sectionLabel("Les types")).toBe("Les types");
  });
});

describe("a blank answer", () => {
  it("reads emptiness through the shape the question expects", () => {
    expect(answered("")).toBe(false);
    expect(answered("   ")).toBe(false);
    expect(answered("0")).toBe(true);
    expect(answered([])).toBe(false);
    expect(answered(["", "x"])).toBe(true);
    expect(answered({})).toBe(false);
    expect(answered({ p: "q" })).toBe(true);
    expect(answered(undefined)).toBe(false);
  });
});

describe("the table a section draws", () => {
  const cell = (id: string, row: string, col: string) => ({ id, row, col });

  it("keeps the author's order for both headers rather than sorting them", () => {
    const table = tableFor([
      cell("a", "-58", "signe-valeur"),
      cell("b", "-58", "complément à 1"),
      cell("c", "-100", "signe-valeur"),
      cell("d", "-100", "complément à 1"),
    ])!;
    expect(table.cols).toEqual(["signe-valeur", "complément à 1"]);
    expect(table.rows.map((r) => r.label)).toEqual(["-58", "-100"]);
    expect(table.rows[1]!.cells.map((q) => q?.id)).toEqual(["c", "d"]);
  });

  it("draws the single-row case the IEEE 754 fields need", () => {
    const table = tableFor([
      cell("s", "89,25", "Signe (1 bit)"),
      cell("e", "89,25", "Exposant (8 bits)"),
      cell("m", "89,25", "Mantisse (23 bits)"),
    ])!;
    expect(table.cols).toHaveLength(3);
    expect(table.rows).toHaveLength(1);
  });

  it("leaves a hole where the author declared no question, rather than shifting the row", () => {
    const table = tableFor([
      cell("a", "-58", "signe-valeur"),
      cell("b", "-58", "complément à 1"),
      cell("c", "-100", "complément à 1"),
    ])!;
    expect(table.rows[1]!.cells.map((q) => q?.id)).toEqual([undefined, "c"]);
  });

  it("stays a list when any question has no cell -- an older release has none at all", () => {
    expect(tableFor([cell("a", "-58", "signe-valeur"), cell("b", "", "")])).toBeNull();
    expect(tableFor([{ id: "a", row: "", col: "" }])).toBeNull();
    expect(tableFor([])).toBeNull();
  });

  it("refuses a one-cell table, which is a list wearing a table's clothes", () => {
    expect(tableFor([cell("a", "89,25", "Signe")])).toBeNull();
  });
});
