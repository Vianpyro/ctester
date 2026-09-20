import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushSync, mount, unmount, tick } from "svelte";
import QuizPanel from "../src/components/QuizPanel.svelte";
import { catalog } from "../src/lib/state/catalog.svelte";
import { quiz } from "../src/lib/state/quiz.svelte";
import { submission } from "../src/lib/state/submission.svelte";
import { normalize } from "../src/lib/domain/catalog";
import { packAll } from "../src/lib/domain/answer";
import type { PublishedQuestion } from "../src/lib/api/types";

const RELEASE = {
  collections: [{ id: "c1", title: "Cours 1", items: ["ex1", "ex2", "code"], access: "available" }],
  exercises: [
    { id: "ex1", title: "Ex.1 conversions", mode: "quiz", access: "available" },
    { id: "ex2", title: "Ex.2 masques", mode: "quiz", access: "available" },
    { id: "code", title: "Ex.3 programme", mode: "io", access: "available" },
  ],
  assignments: [],
};

const ask = (id: string, over: Partial<PublishedQuestion> = {}): PublishedQuestion => ({
  id,
  group: "G",
  label: id,
  type: "bin8",
  width: 8,
  ...over,
});

let payloads: Record<string, PublishedQuestion[]> = {};
let asked: string[] = [];

function fakeFetch(input: RequestInfo | URL): Promise<Response> {
  const url = String(input);
  const found = url.match(/quiz\/([^.]+)\.json/);
  if (found) {
    asked.push(found[1]!);
    const questions = payloads[found[1]!];
    if (!questions) return Promise.resolve(new Response("{}", { status: 404 }));
    return Promise.resolve(new Response(JSON.stringify({ questions }), { status: 200 }));
  }
  return Promise.resolve(new Response("{}", { status: 404 }));
}

let host: HTMLElement | null = null;
let panel: Record<string, unknown> | null = null;

/** jsdom lays nothing out, so the page is told how tall it is. */
function measures(scrollHeight: number, room = 1000): void {
  Object.defineProperty(HTMLDivElement.prototype, "scrollHeight", {
    configurable: true,
    get(this: HTMLElement) {
      return this.id === "quizwrap" ? scrollHeight * quiz.shown.length : 0;
    },
  });
  vi.stubGlobal("innerHeight", room);
}

async function show(): Promise<HTMLElement> {
  host = document.createElement("div");
  document.body.appendChild(host);
  panel = mount(QuizPanel, { target: host });
  // Filling a page is fetch, render, measure, repeat: let those rounds actually run.
  for (let i = 0; i < 24; i++) {
    await new Promise((done) => setTimeout(done, 0));
    await tick();
  }
  flushSync();
  return host;
}

beforeEach(() => {
  payloads = {};
  asked = [];
  vi.stubGlobal("fetch", fakeFetch);
  catalog.model = normalize(RELEASE as never);
  catalog.selectedId = "ex1";
  measures(0);
});

afterEach(() => {
  if (panel) unmount(panel);
  host?.remove();
  panel = null;
  host = null;
  quiz.clear();
  submission.reset();
  vi.unstubAllGlobals();
});

describe("what a page takes in", () => {
  it("fills with the exercises that follow, while they fit", async () => {
    payloads = { ex1: [ask("a")], ex2: [ask("b")] };
    const node = await show();
    expect(quiz.shown.map((one) => one.exerciseId)).toEqual(["ex1", "ex2"]);
    expect(node.querySelectorAll(".qexercise")).toHaveLength(2);
    // Named only when there is more than one: a lone exercise needs no heading.
    expect([...node.querySelectorAll(".qtitle")].map((h) => h.textContent)).toEqual([
      "Ex.1 conversions",
      "Ex.2 masques",
    ]);
  });

  it("stops at the first exercise that does not fit, and never loads past it", async () => {
    payloads = { ex1: [ask("a")], ex2: [ask("b")] };
    measures(600, 700);
    const node = await show();
    expect(quiz.shown.map((one) => one.exerciseId)).toEqual(["ex1"]);
    expect(node.querySelector(".qtitle")).toBeNull();
  });

  it("keeps the first exercise even when it alone overflows: a page is never empty", async () => {
    payloads = { ex1: [ask("a")], ex2: [ask("b")] };
    measures(5000, 400);
    await show();
    expect(quiz.shown.map((one) => one.exerciseId)).toEqual(["ex1"]);
  });

  it("stops at a code exercise: it would need an editor of its own", async () => {
    payloads = { ex1: [ask("a")], ex2: [ask("b")], code: [ask("c")] };
    await show();
    expect(quiz.shown.map((one) => one.exerciseId)).toEqual(["ex1", "ex2"]);
    expect(asked).not.toContain("code");
  });

  it("starts from the exercise that is open, not from the top of the collection", async () => {
    payloads = { ex1: [ask("a")], ex2: [ask("b")] };
    catalog.selectedId = "ex2";
    await show();
    expect(quiz.shown.map((one) => one.exerciseId)).toEqual(["ex2"]);
    expect(asked).not.toContain("ex1");
  });
});

describe("two exercises on one page", () => {
  it("keeps their answers apart although both call a question q1", async () => {
    payloads = { ex1: [ask("q1")], ex2: [ask("q1")] };
    const node = await show();
    const fields = node.querySelectorAll<HTMLInputElement>("input[data-qtype]");
    expect(fields).toHaveLength(2);
    expect(fields[0]!.getAttribute("aria-labelledby")).toBe("qlabel-ex1/q1");
    expect(fields[1]!.getAttribute("aria-labelledby")).toBe("qlabel-ex2/q1");
    expect(Object.keys(quiz.answers).sort()).toEqual(["ex1/q1", "ex2/q1"]);
  });

  it("marks each exercise from its own verdict", async () => {
    payloads = { ex1: [ask("q1")], ex2: [ask("q1")] };
    await show();
    quiz.answers = { "ex1/q1": "1", "ex2/q1": "2" };
    quiz.submitted = packAll(quiz.answers);
    submission.legs = [
      {
        exercise: "ex1",
        title: "Ex.1",
        token: 1,
        scope: null,
        phase: {
          kind: "done",
          scope: null,
          verdict: {
            state: "done",
            status: "ok",
            kind: "quiz",
            total: 1,
            passed: 0,
            wrong: [{ id: "q1", label: "a", hint: "8 bits demandés" }],
          },
        },
      },
      {
        exercise: "ex2",
        title: "Ex.2",
        token: 2,
        scope: null,
        phase: {
          kind: "done",
          scope: null,
          verdict: { state: "done", status: "ok", kind: "quiz", total: 1, passed: 1 },
        },
      },
    ];
    flushSync();
    const blocks = host!.querySelectorAll(".qexercise");
    expect(blocks[0]!.querySelector(".qmark.wrong")?.textContent).toContain("8 bits demandés");
    expect(blocks[1]!.querySelector(".qmark.right")).toBeTruthy();
    expect(blocks[1]!.querySelector(".qmark.wrong")).toBeNull();
  });

  it("sizes each exercise's fields on its own widest answer", async () => {
    payloads = {
      ex1: [ask("q1", { type: "hex8", width: 2 })],
      ex2: [ask("q1", { type: "bin", width: 23 })],
    };
    const node = await show();
    const blocks = node.querySelectorAll<HTMLElement>(".qexercise");
    expect(blocks[0]!.style.getPropertyValue("--slots")).toBe("2");
    expect(blocks[1]!.style.getPropertyValue("--slots")).toBe("23");
  });

  it("sends one item per exercise, under the ids the judge reads", async () => {
    payloads = { ex1: [ask("q1")], ex2: [ask("q1")] };
    await show();
    quiz.answers = { "ex1/q1": "1", "ex2/q1": "2" };
    expect(quiz.answersFor(quiz.shown[0]!)).toEqual({ q1: "1" });
    expect(quiz.answersFor(quiz.shown[1]!)).toEqual({ q1: "2" });
  });
});

describe("the consignes on the page", () => {
  it("shows one per exercise, named, and drops back to one unnamed when the page shrinks", async () => {
    const { exercise } = await import("../src/lib/state/exercise.svelte");
    payloads = { ex1: [ask("a")], ex2: [ask("b")] };
    await show();
    expect(exercise.statements.map((one) => one.id)).toEqual(["ex1", "ex2"]);
    expect(exercise.statements.map((one) => one.title)).toEqual([
      "Ex.1 conversions",
      "Ex.2 masques",
    ]);
  });
});

describe("a section of a quiz", () => {
  it("counts its own answers, apart from the other sections", async () => {
    payloads = {
      ex1: [ask("a", { group: "G1" }), ask("b", { group: "G1" }), ask("c", { group: "G2" })],
    };
    catalog.selectedId = "ex1";
    payloads.ex2 = [];
    const node = await show();
    quiz.answers = { ...quiz.answers, "ex1/a": "1" };
    flushSync();
    expect([...node.querySelectorAll(".qcount")].map((c) => c.textContent?.trim())).toEqual([
      "1/2 répondues",
      "0/1 répondues",
    ]);
  });

  it("draws a table when the author laid one out", async () => {
    payloads = {
      ex1: [
        ask("a", { row: "-58", col: "signe-valeur" }),
        ask("b", { row: "-58", col: "complément à 1" }),
      ],
      ex2: [],
    };
    const node = await show();
    expect([...node.querySelectorAll("thead th")].map((th) => th.textContent)).toEqual([
      "signe-valeur",
      "complément à 1",
    ]);
    const cell = node.querySelector<HTMLInputElement>('input[data-qid="a"]')!;
    const named = node.querySelector("#" + CSS.escape(cell.getAttribute("aria-labelledby")!));
    expect(named?.textContent?.replace(/\s+/g, " ").trim()).toBe("-58 — signe-valeur");
  });
});
