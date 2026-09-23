import { describe, expect, it } from "vitest";
import { marksFor } from "../src/lib/domain/quizMarks";
import { packAll } from "../src/lib/state/quiz.svelte";
import type { Verdict } from "../src/lib/api/types";

const graded = (wrong: { id: string; label: string }[]): Verdict => ({
  state: "done",
  status: "ok",
  kind: "quiz",
  total: 3,
  passed: 3 - wrong.length,
  wrong,
});

describe("the mark a question wears", () => {
  it("marks a graded question right when it is absent from the wrong list", () => {
    const answers = { a: "00010111", b: "42" };
    expect(marksFor(graded([]), packAll(answers), answers)).toEqual({ a: "right", b: "right" });
  });

  it("marks the ones the judge named, and only those", () => {
    const answers = { a: "10111", b: "42" };
    const marks = marksFor(graded([{ id: "a", label: "23" }]), packAll(answers), answers);
    expect(marks).toEqual({ a: "wrong", b: "right" });
  });

  it("drops the mark as soon as the field no longer holds what was graded", () => {
    const sent = packAll({ a: "10111" });
    expect(marksFor(graded([{ id: "a", label: "23" }]), sent, { a: "00010111" })).toEqual({});
  });

  it("leaves a question that was never submitted unmarked", () => {
    const marks = marksFor(graded([]), packAll({ a: "1" }), { a: "1", b: "" });
    expect(marks.b).toBeUndefined();
  });

  it("marks the questions of every page: the server grades the whole quiz", () => {
    const answers = { p1: "1", p2: "2" };
    const marks = marksFor(graded([{ id: "p2", label: "b" }]), packAll(answers), answers);
    expect(marks).toEqual({ p1: "right", p2: "wrong" });
  });

  it("marks nothing when the run did not grade", () => {
    const answers = { a: "1" };
    const broken: Verdict = { state: "done", status: "error", kind: "quiz", message: "juge" };
    expect(marksFor(broken, packAll(answers), answers)).toEqual({});
    expect(marksFor(null, packAll(answers), answers)).toEqual({});
  });

  it("compares structured answers on their packed form", () => {
    const answers = { m: { x: "1" } };
    const sent = packAll(answers);
    expect(marksFor(graded([]), sent, answers)).toEqual({ m: "right" });
    expect(marksFor(graded([]), sent, { m: { x: "2" } })).toEqual({});
  });
});
