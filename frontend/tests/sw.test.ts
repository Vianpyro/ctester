import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

// The worker runs in a context vitest cannot host, so this reads the one rule that would
// hurt if it were wrong: a cached per-account answer would be served to the next student
// on a shared machine.
const source = readFileSync(join(__dirname, "..", "public", "sw.js"), "utf8");

function published(): RegExp {
  const line = source.match(/const PUBLISHED = (\/.*\/);/);
  expect(line, "sw.js no longer declares PUBLISHED").toBeTruthy();
  return new Function("return " + line![1])() as RegExp;
}

describe("the service worker", () => {
  it("caches the published content", () => {
    for (const path of [
      "/catalog.json",
      "/exercise/tp1-ex1.json",
      "/quiz/cours1-ex1.json",
      "/statement/tp1-ex1/dark-1.svg",
    ]) {
      expect(published().test(path), path).toBe(true);
    }
  });

  it("caches nothing that belongs to one account", () => {
    for (const path of [
      "/states",
      "/practice",
      "/draft",
      "/preferences",
      "/forum",
      "/forum/activity",
      "/team/context",
      "/r/0123456789abcdef",
      "/submit",
      "/live",
      "/staff/quiz/cours1-ex1.json",
      "/staff/exercise/tp1-ex1.json",
    ]) {
      expect(published().test(path), path).toBe(false);
    }
  });

  it("refuses anything carrying a token, whatever its path", () => {
    expect(source, "an authenticated request must never be held").toContain(
      'request.headers.has("authorization")',
    );
  });

  it("does not serve a document older than the asset hashes it names", () => {
    expect(source, "navigations must go to the network first").toMatch(
      /request\.mode === "navigate"\)\s*\{\s*event\.respondWith\(ahead\(request\)\)/,
    );
  });
});
