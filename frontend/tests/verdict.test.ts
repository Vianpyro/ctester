import { describe, expect, it } from "vitest";
import {
  AFTER_FAILURE,
  OUTCOMES,
  afterFailure,
  caseClass,
  caseReason,
  caseInputs,
  caseNumbers,
  estimatedWait,
  firstError,
  isJudgeFailure,
  outcomeNext,
  outcomeTitle,
  quizHint,
  restrictToScope,
  showsContract,
  stepState,
  verdictExplain,
  verdictHeadline,
} from "../src/lib/domain/verdict";
import type { Verdict } from "../src/lib/api/types";

describe("the three stages", () => {
  it("agrees in gender and number with the stage", () => {
    expect(stepState(0, "")).toBe("pas atteinte");
    expect(stepState(2, "")).toBe("pas atteints");
  });

  it("names the stage not reached, which is what answers `did my program even run?`", () => {
    expect(OUTCOMES.compile_error!.steps).toEqual(["ko", "", ""]);
    expect(OUTCOMES.timeout!.steps).toEqual(["ok", "ko", ""]);
  });

  it("gives every failure exactly one next action", () => {
    for (const status of Object.keys(OUTCOMES)) {
      expect(outcomeTitle(status), status).not.toContain("verdict.");
      expect(outcomeNext(status), status).not.toContain("verdict.");
    }
    for (const mode of AFTER_FAILURE) {
      expect(afterFailure(mode), mode).not.toContain("verdict.");
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

  it("isolates the first error and the excerpt that follows it", () => {
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

describe("caseNumbers", () => {
  it("reads `numbers`, and still reads `nombres` from verdicts written before the rename", () => {
    expect(caseNumbers({ case: 1, reason: "", numbers: [1, 2] })).toEqual([1, 2]);
    expect(caseNumbers({ case: 1, reason: "", nombres: [3] })).toEqual([3]);
    expect(caseNumbers({ case: 1, reason: "" })).toBeUndefined();
  });
});

describe("caseClass", () => {
  it("names the kind of failure so three folded cases still scan at a glance", () => {
    expect(caseClass("unfinished")).toBe("unfinished");
    expect(caseClass("interrupted")).toBe("unfinished");
    expect(caseClass("memory")).toBe("memory");
    expect(caseClass("crashed")).toBe("crashed");
    expect(caseClass("wrong_values")).toBe("wrong");
    expect(caseClass(undefined)).toBe("wrong");
  });

  it("words the judge's reason with its values, and shows an unknown one as sent", () => {
    expect(caseReason({ case: 1, reason: "crashed", params: { code: 139 } })).toBe(
      "le programme s'est terminé anormalement (code 139)",
    );
    expect(
      caseReason({
        case: 1,
        reason: "out_of_range",
        params: { count: 1, low: "1", high: "6", needed: 5 },
      }),
    ).toBe("ta sortie contient 1 valeur entre 1 et 6, il en faut au moins 5");
    expect(caseReason({ case: 1, reason: "une vieille phrase" })).toBe("une vieille phrase");
    expect(quizHint("needs_8_bits")).toBe("bonne valeur, mais l'énoncé demande 8 bits");
  });
});

describe("showsContract", () => {
  it("shows the grading contract only for a value comparison", () => {
    expect(showsContract({ case: 1, reason: "wrong_values" })).toBe(true);
    expect(showsContract({ case: 1, reason: "unfinished" })).toBe(false);
    expect(showsContract({ case: 1, reason: "missing_word" })).toBe(false);
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

  it("restricts only the reading; the judge graded the whole quiz", () => {
    const shown = restrictToScope(graded, { title: "Exercice 1", ids: ["q1", "q2"] });
    expect(shown.total).toBe(2);
    expect(shown.passed).toBe(1);
    expect(shown.wrong!.map((w) => w.id)).toEqual(["q1"]);
    expect(graded.total).toBe(4);
    expect(graded.passed).toBe(2);
  });

  it("says the whole page is right when none of its questions is wrong", () => {
    const shown = restrictToScope(graded, { title: "Exercice 2", ids: ["q2", "q4"] });
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
    expect(verdictHeadline(quiz, { title: "Exercice 1", ids: ["q1", "q2"] })).toBe(
      "1 / 2 réponses justes — Exercice 1",
    );
  });

  it("uses the outcome's short title on a failure, and falls back for an unknown status", () => {
    expect(
      verdictHeadline({ state: "done", status: "compile_error", kind: "io" }, null),
    ).toBe("Ton fichier ne compile pas.");
    expect(
      verdictHeadline({ state: "done", status: "n_importe_quoi" as never, kind: "io" }, null),
    ).toBe(outcomeTitle("error"));
  });
});

describe("estimatedWait", () => {
  it("rounds to five seconds under a minute, and to minutes above", () => {
    expect(estimatedWait(12)).toBe(" (environ 15 s)");
    expect(estimatedWait(90)).toBe(" (environ 2 min)");
  });

  it("says nothing rather than inventing a number", () => {
    expect(estimatedWait(0)).toBe("");
    expect(estimatedWait(undefined)).toBe("");
  });
});

describe("isJudgeFailure", () => {
  it("tells a crashed student program from a broken judge", () => {
    expect(
      isJudgeFailure({ state: "done", status: "error", kind: "io", code: "judge_internal" }),
    ).toBe(true);
    expect(
      isJudgeFailure({ state: "done", status: "error", kind: "io", code: "tests_stopped" }),
    ).toBe(false);
  });

  it("explains a verdict by its code, then its status, then an old judge's text", () => {
    expect(verdictExplain({ state: "done", status: "error", kind: "io", code: "tests_stopped" }))
      .toContain("Les tests se sont arrêtés");
    expect(
      verdictExplain({
        state: "done",
        status: "forbidden_include",
        kind: "io",
        params: { headers: "stdlib.h" },
      }),
    ).toContain("stdlib.h");
    expect(
      verdictExplain({ state: "done", status: "compile_error", kind: "io", message: "vieux" }),
    ).toBe("vieux");
  });
});
