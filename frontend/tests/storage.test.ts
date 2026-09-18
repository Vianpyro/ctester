import { beforeEach, describe, expect, it, vi } from "vitest";
import { moveRenamedKeys } from "../src/lib/storage";

describe("renamed storage keys", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it("moves an old value under its new name and drops the old key", () => {
    localStorage.setItem("old", "1");
    moveRenamedKeys(localStorage, [["old", "new"]]);
    expect(localStorage.getItem("new")).toBe("1");
    expect(localStorage.getItem("old")).toBeNull();
  });

  it("never overwrites a value already written under the new name", () => {
    localStorage.setItem("old", "stale");
    localStorage.setItem("new", "fresh");
    moveRenamedKeys(localStorage, [["old", "new"]]);
    expect(localStorage.getItem("new")).toBe("fresh");
    expect(localStorage.getItem("old")).toBeNull();
  });

  it("runs when the module loads, before any state module reads a key", async () => {
    localStorage.setItem("ctester.exercice", "tp2-ex3");
    sessionStorage.setItem("ctester.cle", "lab-key");
    vi.resetModules();
    const storage = await import("../src/lib/storage");
    expect(storage.localGet("ctester.exercise")).toBe("tp2-ex3");
    expect(storage.sessionGet("ctester.key")).toBe("lab-key");
    expect(localStorage.getItem("ctester.exercice")).toBeNull();
  });
});
