// THE DRAFTS, AND THE EASIEST WAY TO LOSE CODE ON THIS PAGE.
//
// What is checked here is that a poisoned store never reaches the editor, that the status
// line SAYS WHERE the work is, and that a shared document does not get copied into the
// individual draft on top of itself.

import { describe, expect, it, vi } from "vitest";
import { drafts, sanitizeDrafts } from "../src/lib/state/drafts.svelte";
import { editor } from "../src/lib/state/editor.svelte";

describe("sanitizeDrafts", () => {
  it("keeps the well-formed entry and drops the poisoned ones, entry by entry", () => {
    // WHAT COMES OUT OF STORAGE IS NOT TRUSTED DATA -- and one bad exercise must not lose
    // the others. This was a real fixture in the old harness.
    const clean = sanitizeDrafts({
      "tp2-ex3": { "submission.c": "// travail d'hier" },
      "tp2-ex0": { "submission.c": { pas: "une chaîne" } },
      "tp7-ex1": "pas un objet de fichiers",
    });
    expect(clean["tp2-ex3"]).toEqual({ "submission.c": "// travail d'hier" });
    // The exercise survives, minus the file that was not a string.
    expect(clean["tp2-ex0"]).toEqual({});
    expect(clean["tp7-ex1"]).toBeUndefined();
  });

  it("refuses anything that is not an object of exercises", () => {
    expect(sanitizeDrafts(null)).toEqual({});
    expect(sanitizeDrafts("texte")).toEqual({});
    expect(sanitizeDrafts([1, 2])).toEqual({});
  });
});

describe("the status line", () => {
  it("says WHERE the work is, not only when", () => {
    // "saved at 14:32" does not answer the real question, which is "will I find this again
    // on the other machine?".
    drafts.put("tp2-ex1", { "submission.c": "int main(void){}" }, false);
    expect(drafts.status).toMatch(/cet appareil/);
    expect(drafts.statusFailed).toBe(false);
  });

  it("says so LOUDLY when the write did not happen", () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("plein");
    });
    drafts.put("tp2-ex1", { "submission.c": "int main(void){}" }, false);
    expect(drafts.statusFailed).toBe(true);
    expect(drafts.status).toMatch(/NON enregistré/);
    setItem.mockRestore();
  });

  it("is never empty on arrival: a fresh exercise says saving is automatic", () => {
    // It used to stay EMPTY until the student had typed for a second and a half.
    drafts.opened("tp9-ex1", false);
    expect(drafts.status).toBe("enregistrement automatique");
    drafts.opened("tp9-ex1", true);
    expect(drafts.status).toBe("brouillon retrouvé");
  });

  it("keeps the export's message in its OWN slot", () => {
    // The two used to share one and erase each other: "main.c exported" would replace
    // "draft NOT saved", the page's only data-loss warning.
    drafts.put("tp2-ex1", { "submission.c": "x" }, false);
    const saved = drafts.status;
    drafts.sayExport("main.c exporté — 2 exercices sur 2");
    expect(drafts.status).toBe(saved);
    expect(drafts.exportNote).toMatch(/main\.c exporté/);
  });
});

describe("the store itself", () => {
  it("round-trips through localStorage so another tab finds the work", () => {
    drafts.put("tp3-ex2", { "submission.c": "// hier soir" }, false);
    expect(JSON.parse(localStorage.getItem("ctester.drafts")!)["tp3-ex2"]).toEqual({
      "submission.c": "// hier soir",
    });
    expect(drafts.get("tp3-ex2")).toEqual({ "submission.c": "// hier soir" });
  });

  it("clears everything and says so", () => {
    drafts.put("tp3-ex2", { "submission.c": "x" }, false);
    drafts.clearAll();
    expect(drafts.get("tp3-ex2")).toBeNull();
    expect(drafts.hasAny).toBe(false);
    expect(drafts.status).toBe("brouillons effacés");
  });

  it("keeps the quiz's answers in the same store, so one button erases both", () => {
    drafts.putLocal("tp1", { q1: "42", q2: "" });
    expect(drafts.get("tp1")).toEqual({ q1: "42", q2: "" });
  });
});

describe("a shared document is not an individual draft", () => {
  it("still keeps the LOCAL copy, which costs nothing and is a real backup", () => {
    drafts.put("devoir-a", { "main.c": "// à quatre" }, true);
    expect(drafts.get("devoir-a")).toEqual({ "main.c": "// à quatre" });
  });

  it("is what `editor.sharedFor` answers, and only for the exercise the room holds", () => {
    editor.attach({ owns: (id) => id === "devoir-a" });
    expect(editor.sharedFor("devoir-a")).toBe(true);
    expect(editor.sharedFor("tp2-ex1")).toBe(false);
    expect(editor.sharedFor(null)).toBe(false);
    editor.attach(null);
    expect(editor.sharedFor("devoir-a")).toBe(false);
  });
});

describe("the editor's own state", () => {
  it("seeds from the templates when there is no draft, and from the draft when there is", () => {
    editor.open("tp2-ex1", [{ name: "submission.c", template: "// gabarit" }], null);
    expect(editor.text).toBe("// gabarit");
    editor.open("tp2-ex1", [{ name: "submission.c", template: "// gabarit" }], {
      "submission.c": "// le mien",
    });
    expect(editor.text).toBe("// le mien");
  });

  it("opens a tab with no template empty rather than refusing to open it", () => {
    // NAMES come from the catalog and are authoritative; templates come from the detail
    // and may simply be missing.
    editor.open("tp5-ex1", [{ name: "calendrier.h", template: "" }, { name: "calendrier.c", template: "" }], null);
    expect(editor.activeFile).toBe("calendrier.h");
    expect(editor.text).toBe("");
  });

  it("cycles tabs the way a tablist is expected to, wrapping around", () => {
    editor.open("tp5-ex1", [{ name: "a.h", template: "" }, { name: "b.c", template: "" }], null);
    editor.cycle(1);
    expect(editor.activeFile).toBe("b.c");
    editor.cycle(1);
    expect(editor.activeFile).toBe("a.h");
    editor.cycle(-1);
    expect(editor.activeFile).toBe("b.c");
  });

  it("writes a non-active file without disturbing the one on screen", () => {
    editor.open("tp5-ex1", [{ name: "a.h", template: "" }, { name: "b.c", template: "" }], null);
    editor.write("b.c", "int f(void){}");
    expect(editor.activeFile).toBe("a.h");
    expect(editor.read("b.c")).toBe("int f(void){}");
    expect(editor.text).toBe("");
  });

  it("locks as a real STATE, not as a disabled button", () => {
    // A workspace whose library did not load must stop accepting typing rather than accept
    // it and lose it.
    editor.lock(true);
    expect(editor.readOnly).toBe(true);
    editor.lock(false);
    expect(editor.readOnly).toBe(false);
  });

  it("never lets a collaboration hook break typing", () => {
    editor.open("tp2-ex1", [{ name: "submission.c", template: "" }], null);
    editor.attach({
      owns: () => true,
      onCaret: () => {
        throw new Error("une salle qui lève");
      },
    });
    expect(() => editor.notify("onCaret")).not.toThrow();
    editor.attach(null);
  });
});
