// THE SHARED SURFACE IS REALLY SHARED, and this is the check that says so.
//
// The exercise editor and the Console were two copies of the same three elements,
// and the second one silently fell behind: the Tab key, the auto-closing pairs and
// the syntax checker were each written once and reached only one of them. They are
// one component now, so what has to be guarded is the WIRING -- that the checker
// reaches the gutter and the list, and that mounting it twice does not produce two
// elements wearing the same id.
//
// `keyEdit` itself is tested by calling it (`keys.test.ts`), and the checker by
// calling it (`syntax.test.ts`). Nothing here re-tests either.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mount, unmount, flushSync } from "svelte";
import CodeSurface from "../src/components/CodeSurface.svelte";

let host: HTMLDivElement;
const mounted: ReturnType<typeof mount>[] = [];

/** Mounts a surface and runs past the checker's 600 ms pause. */
function surface(value: string, idPrefix = "") {
  const app = mount(CodeSurface, {
    target: host,
    props: { value, label: "Code", placeholder: "", idPrefix },
  });
  mounted.push(app);
  flushSync();
  vi.advanceTimersByTime(700);
  flushSync();
  return app;
}

beforeEach(() => {
  vi.useFakeTimers();
  host = document.createElement("div");
  document.body.appendChild(host);
});

afterEach(() => {
  while (mounted.length) unmount(mounted.pop()!);
  host.remove();
  vi.useRealTimers();
});

describe("the surface renders the editor", () => {
  it("numbers the gutter one line at a time", () => {
    surface("int a;\nint b;\nint c;\n");
    expect(host.querySelector("#gutter")?.textContent).toBe("1\n2\n3\n4\n");
  });

  it("puts the coloured layer and the textarea in the same pane", () => {
    surface("int x;\n");
    const pane = host.querySelector(".pane");
    expect(pane?.querySelector("pre.hl")).toBeTruthy();
    expect(pane?.querySelector("textarea.codein")).toBeTruthy();
  });
});

describe("the checker reaches the screen", () => {
  it("says nothing about correct code", () => {
    surface("int main(void) {\n    return 0;\n}\n");
    expect(host.querySelector(".diags")?.hasAttribute("hidden")).toBe(true);
    expect(host.querySelector(".gutter .error")).toBeNull();
  });

  it("flags the gutter line AND lists the fault", () => {
    surface("int main(void) {\n    return 0;\n");
    expect(host.querySelector(".diags")?.hasAttribute("hidden")).toBe(false);
    // The unclosed brace is on line 1, and it is certain, so the number is red.
    const flagged = host.querySelectorAll(".gutter .error");
    expect(flagged).toHaveLength(1);
    expect(flagged[0]!.textContent).toBe("1");
    expect(host.querySelector(".diag")?.textContent).toContain("ligne 1");
  });

  it("tells a hint from a certain fault, because they are not equally sure", () => {
    surface("int main(void) {\n    if (x = 3) return 1;\n    return 0;\n}\n");
    expect(host.querySelector(".diag.hint")).toBeTruthy();
    expect(host.querySelector(".diag.error")).toBeNull();
  });

  it("SAYS NOTHING BEFORE THE PAUSE -- it must not scold while one types", () => {
    mounted.push(
      mount(CodeSurface, {
        target: host,
        props: { value: "int main(void) {\n", label: "Code", placeholder: "" },
      }),
    );
    flushSync();
    vi.advanceTimersByTime(300);
    flushSync();
    expect(host.querySelector(".diags")?.hasAttribute("hidden")).toBe(true);
  });
});

describe("two editors, one document", () => {
  it("KEEPS THE IDS APART -- `#travail` is hidden, not unmounted", () => {
    surface("int x;\n");
    surface("int y;\n", "scratch");
    for (const id of ["edwrap", "gutter", "pane", "hl", "hlcode", "code"]) {
      expect(host.querySelectorAll("#" + id)).toHaveLength(1);
      expect(host.querySelectorAll("#scratch" + id)).toHaveLength(1);
    }
  });

  it("gives each its own underline layer, so the class is not an id", () => {
    surface("int main(void) {\n", "");
    surface("int main(void) {\n", "scratch");
    expect(host.querySelectorAll(".squiggles")).toHaveLength(2);
  });
});
