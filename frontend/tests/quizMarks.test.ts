import { describe, expect, it } from "vitest";
import { answered, keyOf, packAll } from "../src/lib/domain/answer";
import {
  fillPage,
  marksFor,
  pageStatus,
  slotsOnScreen,
  tableFor,
} from "../src/lib/domain/quizMarks";
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
  // A page keys answers by exercise and question; the judge answers in question ids alone.
  const k = (id: string) => keyOf("ex", id);

  it("marks a graded question right when it is absent from the wrong list", () => {
    const answers = { [k("a")]: "00010111", [k("b")]: "42" };
    const marks = marksFor(graded([]), packAll(answers), answers, "ex");
    expect(marks[k("a")]).toEqual({ state: "right" });
    expect(marks[k("b")]).toEqual({ state: "right" });
  });

  it("carries the judge's hint on a wrong answer, never the expected value", () => {
    const answers = { [k("a")]: "10111" };
    const marks = marksFor(
      graded([{ id: "a", label: "23", hint: "bonne valeur, mais l'énoncé demande 8 bits" }]),
      packAll(answers),
      answers,
      "ex",
    );
    expect(marks[k("a")]).toEqual({
      state: "wrong",
      hint: "bonne valeur, mais l'énoncé demande 8 bits",
    });
  });

  it("drops the mark as soon as the field no longer holds what was graded", () => {
    const sent = packAll({ [k("a")]: "10111" });
    const marks = marksFor(graded([{ id: "a", label: "23" }]), sent, { [k("a")]: "00010111" }, "ex");
    expect(marks[k("a")]).toBeUndefined();
  });

  it("leaves a question that was never submitted unmarked", () => {
    const marks = marksFor(
      graded([]),
      packAll({ [k("a")]: "1" }),
      { [k("a")]: "1", [k("b")]: "" },
      "ex",
    );
    expect(marks[k("b")]).toBeUndefined();
  });

  it("marks questions from every section, since the server grades the whole quiz", () => {
    const answers = { [k("p1")]: "1", [k("p2")]: "2" };
    const marks = marksFor(graded([{ id: "p2", label: "b" }]), packAll(answers), answers, "ex");
    expect(marks[k("p1")]!.state).toBe("right");
    expect(marks[k("p2")]!.state).toBe("wrong");
  });

  it("never marks a question of another exercise sharing the page", () => {
    // Two quizzes may both call a question "q1": the mark must not cross over.
    const answers = { "ex/q1": "1", "autre/q1": "1" };
    const marks = marksFor(graded([{ id: "q1", label: "a" }]), packAll(answers), answers, "ex");
    expect(marks["ex/q1"]!.state).toBe("wrong");
    expect(marks["autre/q1"]).toBeUndefined();
  });

  it("marks nothing when the run did not grade -- a compile error is not a quiz result", () => {
    const answers = { [k("a")]: "1" };
    const broken: Verdict = { state: "done", status: "error", kind: "quiz", message: "juge" };
    expect(marksFor(broken, packAll(answers), answers, "ex")).toEqual({});
    expect(marksFor(null, packAll(answers), answers, "ex")).toEqual({});
  });

  it("compares structured answers on their packed form", () => {
    const answers = { [k("m")]: { x: "1" } };
    const sent = packAll(answers);
    expect(marksFor(graded([]), sent, answers, "ex")[k("m")]).toEqual({ state: "right" });
    expect(marksFor(graded([]), sent, { [k("m")]: { x: "2" } }, "ex")[k("m")]).toBeUndefined();
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

describe("filling a page one exercise at a time", () => {
  /** A fake DOM: the page fits while the first `room` exercises are on it. */
  const upTo = (room: number) => {
    const asked: number[] = [];
    return {
      asked,
      attempt: async (n: number) => {
        asked.push(n);
        return n <= room;
      },
    };
  };

  it("keeps adding while they fit, and stops at the first that does not", async () => {
    const dom = upTo(2);
    expect(await fillPage(5, dom.attempt)).toBe(2);
    // It asks for one more than it keeps: that is how it learns where to stop.
    expect(dom.asked).toEqual([1, 2, 3]);
  });

  it("keeps the first exercise even when it does not fit on its own", async () => {
    const dom = upTo(0);
    expect(await fillPage(3, dom.attempt)).toBe(1);
    expect(dom.asked).toEqual([1, 2]);
  });

  it("stops at the end of the list without asking for one that is not there", async () => {
    const dom = upTo(10);
    expect(await fillPage(3, dom.attempt)).toBe(3);
    expect(dom.asked).toEqual([1, 2, 3]);
  });

  it("has nothing to fill a page with when the collection offers nothing", async () => {
    const dom = upTo(10);
    expect(await fillPage(0, dom.attempt)).toBe(0);
    expect(dom.asked).toEqual([]);
  });
});

describe("the width every field on screen shares", () => {
  const q = (type: string, width: number) => ({ type, width });

  it("takes the widest answer the sheet asks for", () => {
    expect(slotsOnScreen([q("bin", 1), q("bin8", 8), q("bin", 23)])).toBe(23);
    expect(slotsOnScreen([q("bin8", 8), q("hex8", 2)])).toBe(8);
  });

  it("lets a field of unknown length pull the row up to the default, never below it", () => {
    expect(slotsOnScreen([q("hex8", 2), q("text", 0)])).toBe(12);
    expect(slotsOnScreen([q("bin", 23), q("text", 0)])).toBe(23);
  });

  it("ignores the types that draw their own controls", () => {
    expect(slotsOnScreen([q("bin8", 8), q("choice", 0), q("order", 0)])).toBe(8);
    expect(slotsOnScreen([q("choice", 0)])).toBe(12);
    expect(slotsOnScreen([])).toBe(12);
  });
});
