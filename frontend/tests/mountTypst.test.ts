import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushSync, mount, unmount } from "svelte";
import App from "../src/App.svelte";
import { session } from "../src/lib/auth/session.svelte";
import { drafts } from "../src/lib/state/drafts.svelte";

const RELEASE = {
  collections: [{ id: "tp2", title: "TP 2", items: ["tp2-ex1"], access: "available" }],
  exercises: [
    {
      id: "tp2-ex1",
      title: "ex.1 conversion",
      mode: "io",
      files: [{ name: "submission.c" }],
      access: "available",
    },
  ],
  assignments: [],
};

const DETAIL = {
  statement: "",
  statement_format: "typst",
  statement_pages: 2,
  files: [{ name: "submission.c", template: "// écris ici" }],
};

let asked: string[] = [];

function fakeFetch(input: RequestInfo | URL): Promise<Response> {
  const url = String(input);
  asked.push(url);
  if (url === "catalog.json") {
    return Promise.resolve(new Response(JSON.stringify(RELEASE), { status: 200 }));
  }
  if (url.startsWith("exercise/")) {
    return Promise.resolve(new Response(JSON.stringify(DETAIL), { status: 200 }));
  }
  if (url === "oidc.json") {
    return Promise.resolve(new Response("{}", { status: 200 }));
  }
  if (url.startsWith("live")) {
    return Promise.resolve(new Response(JSON.stringify({ n: 1 }), { status: 200 }));
  }
  return Promise.resolve(new Response("{}", { status: 404 }));
}

let host: HTMLElement;
let app: Record<string, unknown> | null = null;

const settle = async () => {
  for (let i = 0; i < 30; i++) await Promise.resolve();
  flushSync();
};

beforeEach(() => {
  asked = [];
  vi.stubGlobal("fetch", fakeFetch);
  document.body.innerHTML = "";
  host = document.body;
  app = null;
  drafts.clearAll();
  session.deployment = null;
  session.setToken(null);
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
});

async function render() {
  app = mount(App, { target: host }) as Record<string, unknown>;
  await settle();
  await settle();
}

describe("a Typst statement, all the way to the page", () => {
  it("draws the pages as images instead of rendered Markdown", async () => {
    await render();
    const panel = document.getElementById("statementtext")!;
    expect(panel.classList.contains("md")).toBe(false);
    const images = [...panel.querySelectorAll("img")];
    expect(images).toHaveLength(2);
    expect(images.map((img) => img.getAttribute("src"))).toEqual([
      "statement/tp2-ex1/dark-1.svg",
      "statement/tp2-ex1/dark-2.svg",
    ]);
  });

  it("keeps the workspace grid at exactly three columns", async () => {
    await render();
    const travail = document.getElementById("work")!;
    expect([...travail.children].map((el) => el.id)).toEqual([
      "statement",
      "right",
      "chatdock",
    ]);
  });

  it("fills the editor anyway: the statement's format decides nothing else", async () => {
    await render();
    expect((document.getElementById("code") as HTMLTextAreaElement).value).toBe(
      "// écris ici",
    );
  });

  it("emits no request for the pages: an <img> is the browser's business", async () => {
    await render();
    const kinds = new Set(asked.map((u) => u.split("?")[0]!.replace(/^exercise\/.*/, "exercise/")));
    for (const kind of kinds) {
      expect(["catalog.json", "live", "oidc.json", "exercise/"], kind).toContain(kind);
    }
    expect(asked.some((u) => u.includes(".svg"))).toBe(false);
  });
});
