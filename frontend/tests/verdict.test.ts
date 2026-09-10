// WHAT A VERDICT MEANS FOR THE STUDENT. Every assertion here is a sentence somebody reads
// in front of a failing test, or a rule that decides whether a lab counts as validated.

import { describe, expect, it } from "vitest";
import {
  AFTER_FAILURE,
  OUTCOMES,
  STEPS,
  STEP_STATE,
  caseClass,
  caseInputs,
  estimatedWait,
  firstError,
  isJudgeFailure,
  restrictToScope,
  showsContract,
  verdictHeadline,
} from "../src/lib/domain/verdict";
import type { Verdict } from "../src/lib/api/types";

describe("the three stages", () => {
  it("agrees in gender and number with the stage -- `Tests pas atteinte` is gibberish", () => {
    expect(STEP_STATE[STEPS[0]![1]][""]).toBe("pas atteinte");
    expect(STEP_STATE[STEPS[2]![1]][""]).toBe("pas atteints");
  });

  it("names the stage NOT REACHED, which is what answers `did my program even run?`", () => {
    expect(OUTCOMES.compile_error!.etapes).toEqual(["ko", "", ""]);
    expect(OUTCOMES.timeout!.etapes).toEqual(["ok", "ko", ""]);
  });

  it("gives every failure exactly one next action", () => {
    for (const [status, outcome] of Object.entries(OUTCOMES)) {
      expect(outcome.titre, status).toBeTruthy();
      expect(outcome.suite, status).toBeTruthy();
    }
    for (const mode of ["io", "unity", "quiz"]) {
      expect(AFTER_FAILURE[mode], mode).toBeTruthy();
    }
  });
});

describe("firstError", () => {
  const gcc = [
    "submission.c:4:5: error: expected ';' before '}' token",
    "    4 |     int x = 1",
    "      |     ^",
    "submission.c:9:1: error: 'y' undeclared here",
    "    9 | y = 2;",
  ].join("\n");

  it("isolates the FIRST error and the excerpt that follows it", () => {
    // In C, errors cascade: one missing `;` produces six, five of which do not really
    // exist -- and the raw output scrolls, so what a beginner reads is the most derived one.
    const first = firstError(gcc)!;
    expect(first).toContain("expected ';'");
    expect(first).toContain("^");
    expect(first).not.toContain("undeclared");
  });

  it("returns null when there is no error line at all, so the raw output shows", () => {
    expect(firstError("submission.c:2:5: warning: unused variable 'x'")).toBeNull();
    expect(firstError("")).toBeNull();
    expect(firstError(undefined)).toBeNull();
  });

  it("reads the French wording too, which gcc emits under a French locale", () => {
    expect(firstError("submission.c:4:5: erreur: attendu ';'")).toContain("attendu");
  });
});

describe("caseClass", () => {
  it("names the KIND of failure so three folded cases still scan at a glance", () => {
    expect(caseClass("ton programme n'a pas terminé")).toBe("n'a pas fini");
    expect(caseClass("il a débordé de la mémoire réservée")).toBe("débordement mémoire");
    expect(caseClass("il s'est terminé anormalement")).toBe("a planté");
    expect(caseClass("la valeur attendue n'y est pas")).toBe("mauvaise sortie");
    expect(caseClass(undefined)).toBe("mauvaise sortie");
  });
});

describe("showsContract", () => {
  it("shows the grading contract only for a VALUE comparison", () => {
    // A program that crashed, or a case looking for a word, is not fixed by reformatting
    // its output.
    expect(showsContract({ case: 1, reason: "la valeur attendue n'y est pas" })).toBe(true);
    expect(showsContract({ case: 1, reason: "ton programme n'a pas terminé" })).toBe(false);
    expect(showsContract({ case: 1, reason: "le mot attendu n'apparaît pas" })).toBe(false);
  });
});

describe("caseInputs", () => {
  it("splits stdin into what the program actually receives, one value per line", () => {
    expect(caseInputs("12\n7\n")).toEqual(["12", "7"]);
    expect(caseInputs("")).toEqual([]);
    expect(caseInputs(undefined)).toEqual([]);
  });
});

describe("restrictToScope", () => {
  const graded: Verdict = {
    state: "done",
    status: "ok",
    kind: "quiz",
    total: 4,
    passed: 2,
    wrong: [
      { id: "q1", label: "une" },
      { id: "q3", label: "trois" },
    ],
  };

  it("restricts the READING only -- the judge graded the whole quiz", () => {
    // "Tester l'exercice" changes nothing about grading: it is from the COMPLETE verdict
    // that the API derives "solved", so a correct exercise cannot validate a half-filled lab.
    const shown = restrictToScope(graded, { titre: "Exercice 1", ids: ["q1", "q2"] });
    expect(shown.total).toBe(2);
    expect(shown.passed).toBe(1);
    expect(shown.wrong!.map((w) => w.id)).toEqual(["q1"]);
    // The original is untouched: it is what the API already read.
    expect(graded.total).toBe(4);
    expect(graded.passed).toBe(2);
  });

  it("says the whole page is right when none of its questions is wrong", () => {
    const shown = restrictToScope(graded, { titre: "Exercice 2", ids: ["q2", "q4"] });
    expect(shown.passed).toBe(2);
    expect(shown.total).toBe(2);
  });
});

describe("verdictHeadline", () => {
  it("counts in the mode's own unit", () => {
    const io: Verdict = { state: "done", status: "ok", kind: "io", total: 4, passed: 3 };
    expect(verdictHeadline(io, null)).toBe("3 / 4 cas réussis");
    const unity: Verdict = { state: "done", status: "ok", kind: "unity", total: 2, passed: 2 };
    expect(verdictHeadline(unity, null)).toBe("2 / 2 tests réussis");
  });

  it("frames a restricted quiz with the page it is about", () => {
    const quiz: Verdict = {
      state: "done",
      status: "ok",
      kind: "quiz",
      total: 4,
      passed: 2,
      wrong: [{ id: "q1", label: "une" }],
    };
    expect(verdictHeadline(quiz, { titre: "Exercice 1", ids: ["q1", "q2"] })).toBe(
      "1 / 2 réponses justes — Exercice 1",
    );
  });

  it("uses the outcome's short title on a failure, and falls back for an unknown status", () => {
    expect(
      verdictHeadline({ state: "done", status: "compile_error", kind: "io" }, null),
    ).toBe(OUTCOMES.compile_error!.titre);
    expect(
      verdictHeadline({ state: "done", status: "n_importe_quoi" as never, kind: "io" }, null),
    ).toBe(OUTCOMES.error!.titre);
  });
});

describe("estimatedWait", () => {
  it("rounds to five seconds under a minute, and to minutes above", () => {
    expect(estimatedWait(12)).toBe(" (environ 15 s)");
    expect(estimatedWait(90)).toBe(" (environ 2 min)");
  });

  it("says NOTHING rather than inventing a number", () => {
    // An older API, or an `eta` of 0: only the rank stays displayed.
    expect(estimatedWait(0)).toBe("");
    expect(estimatedWait(undefined)).toBe("");
  });
});

describe("isJudgeFailure", () => {
  it("tells a crashed student program from a broken judge", () => {
    // `error` covers both server-side, and only one of them belongs in the verdict channel.
    expect(
      isJudgeFailure({ state: "done", status: "error", kind: "io", message: "Erreur interne du juge" }),
    ).toBe(true);
    expect(
      isJudgeFailure({
        state: "done",
        status: "error",
        kind: "io",
        message: "ton programme s'est arrêté avant la fin",
      }),
    ).toBe(false);
  });
});
