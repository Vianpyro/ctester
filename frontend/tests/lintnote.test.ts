import { afterEach, describe, expect, it } from "vitest";
import { flushSync, mount, unmount } from "svelte";
import VerdictPanel from "../src/components/VerdictPanel.svelte";
import { editor } from "../src/lib/state/editor.svelte";
import { submission } from "../src/lib/state/submission.svelte";

let app: ReturnType<typeof mount> | null = null;

function panel(): HTMLElement {
  const host = document.createElement("div");
  document.body.appendChild(host);
  app = mount(VerdictPanel, { target: host });
  flushSync();
  return host;
}

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = "";
  editor.issues = [];
  submission.phase = { kind: "idle" };
});

const issue = { from: 20, to: 21, level: "hint" as const, message: "« ; » manque" };

describe("the reminder beside the verdict", () => {
  it("recalls, during a run, what the checker had found", () => {
    editor.issues = [issue];
    submission.phase = { kind: "running" };
    const note = panel().querySelector(".lintnote");
    expect(note?.textContent).toContain("1 problème");
    expect(note?.querySelector("button")).toBeTruthy();
  });

  it("stays out of the way on clean code, and before any test", () => {
    submission.phase = { kind: "running" };
    expect(panel().querySelector(".lintnote")).toBeNull();
    unmount(app!);
    editor.issues = [issue];
    submission.phase = { kind: "idle" };
    expect(panel().querySelector(".lintnote")).toBeNull();
  });
});
