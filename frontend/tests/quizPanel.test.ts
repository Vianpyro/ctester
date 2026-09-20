import { afterEach, describe, expect, it } from "vitest";
import { flushSync, mount, unmount } from "svelte";
import QuizPanel from "../src/components/QuizPanel.svelte";
import { quiz, type QuizPage } from "../src/lib/state/quiz.svelte";
import { submission } from "../src/lib/state/submission.svelte";
import { packAll } from "../src/lib/domain/answer";

const question = (id: string, label: string, group: string) => ({
  id,
  label,
  group,
  type: "bin8",
  options: [],
  prompts: [],
  template: "",
  gaps: [] as string[][],
});

const PAGES: QuizPage[] = [
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

describe("the quiz panel", () => {
  it("puts the judge's hint under the question it belongs to, not in a list elsewhere", () => {
    quiz.pages = PAGES;
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
    quiz.pages = PAGES;
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
    quiz.pages = PAGES;
    quiz.answers = { a: "1", b: "" };
    expect(show().querySelector(".qcount")?.textContent).toContain("1/1");
  });

  it("moves the focus to the new heading when the section changes", () => {
    quiz.pages = PAGES;
    quiz.answers = { a: "", b: "" };
    const node = show();
    quiz.showPage(1);
    flushSync();
    const headings = node.querySelectorAll(".qgroup");
    expect(document.activeElement).toBe(headings[1]);
  });

  it("offers one tile per section and none when there is a single one", () => {
    quiz.pages = PAGES;
    quiz.answers = { a: "", b: "" };
    const node = show();
    expect(node.querySelectorAll("#quizsections .tab")).toHaveLength(2);
    expect(node.querySelector("#quizsections")?.hasAttribute("hidden")).toBe(false);
  });
});
