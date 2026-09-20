import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushSync, mount, unmount } from "svelte";
import LabStrip from "../src/components/LabStrip.svelte";
import { catalog } from "../src/lib/state/catalog.svelte";
import { quiz } from "../src/lib/state/quiz.svelte";
import { normalize } from "../src/lib/domain/catalog";

const RELEASE = {
  collections: [{ id: "c1", title: "Cours 1", items: ["ex1", "ex2", "ex3"], access: "available" }],
  exercises: [
    { id: "ex1", title: "Ex.1 conversions", mode: "quiz", access: "available" },
    { id: "ex2", title: "Ex.2 masques", mode: "quiz", access: "available" },
    { id: "ex3", title: "Ex.3 IEEE 754", mode: "quiz", access: "available" },
  ],
  assignments: [],
};

const page = (...ids: string[]) =>
  ids.map((id) => ({ exerciseId: id, title: id, sections: [] }));

let host: HTMLElement | null = null;
let panel: Record<string, unknown> | null = null;
let scrolled: string[] = [];

function show(): HTMLElement {
  host = document.createElement("div");
  document.body.appendChild(host);
  panel = mount(LabStrip, { target: host, props: { openMenu: () => {} } });
  flushSync();
  return host;
}

const tile = (node: HTMLElement, label: string) =>
  [...node.querySelectorAll("button.tile")].find((b) =>
    b.textContent?.includes(label),
  ) as HTMLButtonElement;

beforeEach(() => {
  scrolled = [];
  vi.stubGlobal("fetch", () => Promise.resolve(new Response("{}", { status: 404 })));
  Element.prototype.scrollIntoView = function (this: Element) {
    scrolled.push(this.id);
  };
  catalog.model = normalize(RELEASE as never);
  catalog.selectedId = "ex1";
  // The blocks the panel would have rendered for the page.
  for (const id of ["ex1", "ex2", "ex3"]) {
    const block = document.createElement("div");
    block.id = "ex-" + id;
    document.body.appendChild(block);
  }
});

afterEach(() => {
  if (panel) unmount(panel);
  host?.remove();
  host = null;
  panel = null;
  document.querySelectorAll("[id^='ex-']").forEach((one) => one.remove());
  quiz.clear();
  vi.unstubAllGlobals();
});

describe("the exercise strip against a page holding several exercises", () => {
  it("marks every exercise the page shows, not only the one in the header", () => {
    quiz.setPage(page("ex1", "ex2"));
    const node = show();
    expect(tile(node, "ex.1").className).toContain("current");
    expect(tile(node, "ex.2").className).toContain("current");
    expect(tile(node, "ex.3").className).not.toContain("current");
  });

  it("scrolls to an exercise already on the page instead of re-entering it", () => {
    // Re-entering would refill the page from there and drop everything above it.
    quiz.setPage(page("ex1", "ex2", "ex3"));
    const node = show();
    tile(node, "ex.3").click();
    flushSync();
    expect(scrolled).toEqual(["ex-ex3"]);
    expect(catalog.selectedId).toBe("ex1");
  });

  it("opens an exercise the page does not show", () => {
    quiz.setPage(page("ex1"));
    const node = show();
    tile(node, "ex.3").click();
    flushSync();
    expect(scrolled).toEqual([]);
    expect(catalog.selectedId).toBe("ex3");
  });
});
