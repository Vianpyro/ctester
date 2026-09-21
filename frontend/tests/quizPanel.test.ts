import { afterEach, describe, expect, it, vi } from "vitest";
import { flushSync, mount, unmount } from "svelte";
import QuizPanel from "../src/components/QuizPanel.svelte";
import { packAll, quiz, type QuizPage } from "../src/lib/state/quiz.svelte";
import { submission } from "../src/lib/state/submission.svelte";
import type { Verdict } from "../src/lib/api/types";

const question = (id: string, label: string, type = "bin8") => ({
  id,
  label,
  group: "G",
  type,
  options: [] as string[],
  prompts: [] as string[],
  template: "",
  gaps: [] as string[][],
});

const PAGES: QuizPage[] = [
  { key: "g", title: "Conversions", questions: [question("a", "23"), question("b", "167")] },
];

const graded = (wrong: { id: string; label: string }[]): Verdict => ({
  state: "done",
  status: "ok",
  kind: "quiz",
  total: 2,
  passed: 2 - wrong.length,
  wrong,
});

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
  vi.useRealTimers();
});

describe("the judge's mark, beside its field", () => {
  it("puts a tick or a cross right after the input it judges", () => {
    quiz.pages = PAGES;
    quiz.answers = { a: "00010111", b: "10111" };
    quiz.submitted = packAll(quiz.answers);
    submission.phase = { kind: "done", scope: null, verdict: graded([{ id: "b", label: "167" }]) };
    const rows = show().querySelectorAll(".qrow");
    // The mark follows the widget on the same line, right after the field it judges.
    expect(rows[0]!.querySelector("input")!.nextElementSibling?.className).toBe("qmark right");
    expect(rows[0]!.querySelector(".qmark")?.textContent).toBe("✓");
    expect(rows[1]!.querySelector(".qmark.wrong")?.textContent).toBe("✗");
    expect(rows[0]!.querySelector(".qmark")?.getAttribute("aria-hidden")).toBe("true");
    expect(rows[0]!.querySelector(".offscreen")?.textContent).toBe("juste");
  });

  it("drops the mark the moment the field is retyped", () => {
    quiz.pages = PAGES;
    quiz.answers = { a: "10111", b: "" };
    quiz.submitted = packAll(quiz.answers);
    submission.phase = { kind: "done", scope: null, verdict: graded([{ id: "a", label: "23" }]) };
    const row = show().querySelector(".qrow")!;
    expect(row.querySelector(".qmark.wrong")).toBeTruthy();
    quiz.answers = { ...quiz.answers, a: "00010111" };
    flushSync();
    expect(row.querySelector(".qmark")?.textContent).toBe("");
    expect(row.querySelector(".offscreen")).toBeNull();
  });

  it("keeps the slot empty but present, so a verdict never shifts the field sideways", () => {
    quiz.pages = PAGES;
    quiz.answers = { a: "00010111", b: "10100111" };
    const node = show();
    // Two rows, two slots, no glyph and nothing announced.
    expect(node.querySelectorAll(".qmark")).toHaveLength(2);
    expect([...node.querySelectorAll(".qmark")].every((one) => one.textContent === "")).toBe(true);
    expect(node.querySelector(".offscreen")).toBeNull();
  });
});

describe("the shape note, while typing", () => {
  it("stays quiet until a second after the last keystroke, then says what is missing", async () => {
    vi.useFakeTimers();
    quiz.pages = PAGES;
    quiz.answers = { a: "1011101", b: "" };
    const node = show();
    const field = node.querySelector<HTMLInputElement>('input[data-qid="a"]')!;
    field.dispatchEvent(new Event("input", { bubbles: true }));
    flushSync();
    expect(node.querySelector(".qshape")).toBeNull();

    await vi.advanceTimersByTimeAsync(1000);
    flushSync();
    expect(node.querySelector(".qshape")?.textContent).toBe("7 bits sur 8");

    // The next keystroke silences it again, without waiting for the answer to be right.
    field.dispatchEvent(new Event("input", { bubbles: true }));
    flushSync();
    expect(node.querySelector(".qshape")).toBeNull();
  });

  it("says nothing about an empty field, nor about a well-formed one", async () => {
    vi.useFakeTimers();
    quiz.pages = PAGES;
    quiz.answers = { a: "00010111", b: "" };
    const node = show();
    node.querySelector("input")!.dispatchEvent(new Event("input", { bubbles: true }));
    await vi.advanceTimersByTimeAsync(1000);
    flushSync();
    expect(node.querySelectorAll(".qshape")).toHaveLength(0);
  });
});
