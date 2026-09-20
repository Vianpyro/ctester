import { afterEach, describe, expect, it } from "vitest";
import { flushSync, mount, unmount } from "svelte";
import QuizPanel from "../src/components/QuizPanel.svelte";
import { quiz, type QuizSection } from "../src/lib/state/quiz.svelte";
import { submission } from "../src/lib/state/submission.svelte";
import { packAll } from "../src/lib/domain/answer";

const question = (id: string, label: string, group: string, row = "", col = "") => ({
  id,
  label,
  group,
  row,
  col,
  type: "bin8",
  width: 8,
  options: [],
  prompts: [],
  template: "",
  gaps: [] as string[][],
});

const PAGES: QuizSection[] = [
  { key: "g1", title: "Exercice 1 : décimal vers binaire", questions: [question("a", "23", "Exercice 1 : décimal vers binaire")] },
  { key: "g2", title: "Exercice 2 : masques", questions: [question("b", "0b1 & 0b1", "Exercice 2 : masques")] },
];

let host: HTMLElement | null = null;
let panel: Record<string, unknown> | null = null;

function show(): HTMLElement {
  host = document.createElement("div");
  document.body.appendChild(host);
  panel = mount(QuizPanel, { target: host });
  flushSync();
  return host;
}

afterEach(() => {
  if (panel) unmount(panel);
  host?.remove();
  panel = null;
  host = null;
  quiz.clear();
  submission.reset();
});

describe("the shape of an answer field", () => {
  const sized = (id: string, type: string, width: number) => ({
    ...question(id, id, "G"),
    type,
    width,
  });

  it("sizes every field on screen to the widest answer the sheet asks for", () => {
    quiz.sections = [
      {
        key: "g",
        title: "89,25",
        questions: [sized("signe", "bin", 1), sized("mantisse", "bin", 23)],
      },
    ];
    quiz.answers = { signe: "", mantisse: "" };
    quiz.sheets = [[0]];
    const node = show();
    expect(node.querySelector<HTMLElement>("#quiz")!.style.getPropertyValue("--slots")).toBe("23");
    expect(
      node.querySelector<HTMLInputElement>('input[data-qid="signe"]')!.style.getPropertyValue(
        "--slots",
      ),
    ).toBe("");
  });

  it("still says in the placeholder how long each answer is", () => {
    quiz.sections = [
      {
        key: "g",
        title: "Conversions",
        questions: [sized("bits", "bin8", 8), sized("hex", "hex8", 2)],
      },
    ];
    quiz.answers = { bits: "", hex: "" };
    const node = show();
    expect(node.querySelector<HTMLInputElement>('input[data-qid="bits"]')!.placeholder).toBe(
      "········",
    );
    expect(node.querySelector<HTMLInputElement>('input[data-qid="hex"]')!.placeholder).toBe("··");
  });

  it("leaves a field whose length nobody fixed without a placeholder", () => {
    quiz.sections = [{ key: "g", title: "G", questions: [sized("a", "text", 0)] }];
    quiz.answers = { a: "" };
    const input = show().querySelector<HTMLInputElement>('input[data-qid="a"]')!;
    expect(input.placeholder).toBe("");
  });

  it("never turns the width into a maxlength: the judge accepts separators", () => {
    quiz.sections = [{ key: "g", title: "G", questions: [sized("a", "bin8", 8)] }];
    quiz.answers = { a: "" };
    const input = show().querySelector<HTMLInputElement>('input[data-qid="a"]')!;
    expect(input.getAttribute("maxlength")).toBeNull();
  });
});

describe("a section the author laid out as a table", () => {
  const TABLE: QuizSection[] = [
    {
      key: "t",
      title: "Exercice 3",
      questions: [
        question("a", "", "Exercice 3", "-58", "signe-valeur"),
        question("b", "", "Exercice 3", "-58", "complément à 1"),
        question("c", "", "Exercice 3", "-100", "signe-valeur"),
        question("d", "", "Exercice 3", "-100", "complément à 1"),
      ],
    },
  ];

  it("draws one header per column and one field per cell", () => {
    quiz.sections = TABLE;
    quiz.answers = { a: "", b: "", c: "", d: "" };
    const node = show();
    expect([...node.querySelectorAll("thead th")].map((th) => th.textContent)).toEqual([
      "signe-valeur",
      "complément à 1",
    ]);
    expect([...node.querySelectorAll("tbody th")].map((th) => th.textContent)).toEqual([
      "-58",
      "-100",
    ]);
    expect(node.querySelectorAll("tbody input")).toHaveLength(4);
  });

  it("names each field by its row and column, since the cell carries no label of its own", () => {
    quiz.sections = TABLE;
    quiz.answers = { a: "", b: "", c: "", d: "" };
    const node = show();
    const input = node.querySelector<HTMLInputElement>('input[data-qid="d"]')!;
    const named = node.querySelector("#" + CSS.escape(input.getAttribute("aria-labelledby")!));
    expect(named?.textContent?.replace(/\s+/g, " ").trim()).toBe("-100 — complément à 1");
  });

  it("puts the hint in the cell that is wrong", () => {
    quiz.sections = TABLE;
    quiz.answers = { a: "1", b: "", c: "", d: "" };
    quiz.submitted = packAll(quiz.answers);
    submission.phase = {
      kind: "done",
      scope: null,
      verdict: {
        state: "done",
        status: "ok",
        kind: "quiz",
        total: 4,
        passed: 3,
        wrong: [{ id: "a", label: "-58", given: "1", hint: "8 bits demandés" }],
      },
    };
    const cells = [...show().querySelectorAll("tbody td")];
    expect(cells[0]!.querySelector(".qmark.wrong")?.textContent).toContain("8 bits demandés");
    expect(cells[1]!.querySelector(".qmark.wrong")).toBeNull();
    expect(cells[1]!.querySelector(".qmark.right")?.textContent?.trim()).toBe("✓");
  });
});

describe("the quiz panel", () => {
  it("puts the judge's hint under the question it belongs to, not in a list elsewhere", () => {
    quiz.sections = PAGES;
    quiz.answers = { a: "10111", b: "" };
    quiz.submitted = packAll(quiz.answers);
    submission.phase = {
      kind: "done",
      scope: null,
      verdict: {
        state: "done",
        status: "ok",
        kind: "quiz",
        total: 2,
        passed: 0,
        wrong: [{ id: "a", label: "23", given: "10111", hint: "l'énoncé demande 8 bits" }],
      },
    };
    const row = show().querySelector(".qq");
    expect(row?.querySelector("#qlabel-a")?.textContent).toBe("23");
    expect(row?.querySelector(".qmark.wrong")?.textContent).toContain("l'énoncé demande 8 bits");
  });

  it("drops a mark as soon as the field is retyped, so no stale verdict is left on screen", () => {
    quiz.sections = PAGES;
    quiz.answers = { a: "10111", b: "" };
    quiz.submitted = packAll(quiz.answers);
    submission.phase = {
      kind: "done",
      scope: null,
      verdict: { state: "done", status: "ok", kind: "quiz", total: 2, passed: 1, wrong: [{ id: "a", label: "23" }] },
    };
    const node = show();
    const row = node.querySelector(".qq")!;
    expect(row.querySelector(".qmark.wrong")).toBeTruthy();
    quiz.answers = { ...quiz.answers, a: "00010111" };
    flushSync();
    expect(row.querySelector(".qmark")).toBeNull();
  });

  it("counts the filled answers of the section on screen", () => {
    quiz.sections = PAGES;
    quiz.answers = { a: "1", b: "" };
    expect(show().querySelector(".qcount")?.textContent).toContain("1/1");
  });

  it("moves the focus to the new heading when the sheet changes", () => {
    quiz.sections = PAGES;
    quiz.answers = { a: "", b: "" };
    // jsdom lays nothing out, so the panel never packs: state the split the way a real
    // measurement would have, then check what changing sheet does.
    quiz.sheets = [[0], [1]];
    const node = show();
    quiz.showSection(1);
    flushSync();
    const headings = node.querySelectorAll(".qgroup");
    expect(quiz.sheet).toBe(1);
    expect(document.activeElement).toBe(headings[1]);
  });

  it("keeps sections that share a sheet on screen together", () => {
    quiz.sections = PAGES;
    quiz.answers = { a: "", b: "" };
    quiz.sheets = [[0, 1]];
    const node = show();
    quiz.showSection(1);
    flushSync();
    expect(quiz.sheet).toBe(0);
    expect([...node.querySelectorAll(".qsection")].every((s) => !s.hasAttribute("hidden"))).toBe(
      true,
    );
    expect(quiz.currentScope()).toEqual({
      title: "Exercice 1 : décimal vers binaire · Exercice 2 : masques",
      ids: ["a", "b"],
    });
  });

  it("offers one tile per section and none when there is a single one", () => {
    quiz.sections = PAGES;
    quiz.answers = { a: "", b: "" };
    const node = show();
    expect(node.querySelectorAll("#quizsections .tab")).toHaveLength(2);
    expect(node.querySelector("#quizsections")?.hasAttribute("hidden")).toBe(false);
  });
});
