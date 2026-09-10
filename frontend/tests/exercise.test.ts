// OPENING AN EXERCISE, AND THE ORDER OF IT. This is the one transaction that touches
// several owners at once, so the sequence is what is checked here -- not each owner again.
//
// THIS SUITE EXISTS BECAUSE A HOOK WAS SILENTLY DEAD. The chat's channel follows the
// editor through a callback the chat registers on load; during the migration the
// registration was written and never called, so opening an exercise stopped moving the
// channel -- with nothing on screen to say so. A structural check ("does the file call
// it?") would have been satisfied by the same broken code, so what is checked is the
// BEHAVIOUR.
//
// EACH SCENARIO USES ITS OWN EXERCISE, and that is not tidiness: the statement cache and
// the draft store are deliberately per-page-load, so reusing an id would have one test
// read what the previous one left -- and hide exactly the caching this relies on.

import { beforeEach, describe, expect, it, vi } from "vitest";
import { catalog } from "../src/lib/state/catalog.svelte";
import { drafts } from "../src/lib/state/drafts.svelte";
import { editor } from "../src/lib/state/editor.svelte";
import { exercise, whenChatReady } from "../src/lib/state/exercise.svelte";
import { session } from "../src/lib/auth/session.svelte";
import { submission } from "../src/lib/state/submission.svelte";

/**
 * Forty exercises in one lab, handed out by `next()` so no two scenarios ever share one.
 * The statement cache lives for the life of a page load, which is right in the application
 * and means a reused id would have one test read what the previous one left.
 */
const IDS = Array.from({ length: 40 }, (_, i) => "tp2-ex" + (i + 1));

let handedOut = 0;
const next = () => IDS[handedOut++]!;

const RELEASE = {
  collections: [{ id: "tp2", title: "TP 2", items: IDS, access: "available" }],
  exercises: IDS.map((id) => ({
    id,
    title: "ex." + id.slice("tp2-ex".length),
    mode: "io",
    files: [{ name: "submission.c" }],
    access: "available",
  })),
  assignments: [],
};

/** `tp/<id>.json`, and how long each one takes to answer. */
let delays: Record<string, number> = {};
/** Ids whose statement is empty -- "no statement online", not a failure. */
let silent = new Set<string>();

function fakeFetch(input: RequestInfo | URL): Promise<Response> {
  const url = String(input);
  if (url === "catalog.json") {
    return Promise.resolve(new Response(JSON.stringify(RELEASE), { status: 200 }));
  }
  const id = url.slice("tp/".length, -".json".length);
  const body = JSON.stringify({
    statement: silent.has(id) ? "" : "Consigne de " + id,
    files: [{ name: "submission.c", template: "// gabarit " + id }],
  });
  const delay = delays[id] ?? 0;
  if (!delay) return Promise.resolve(new Response(body, { status: 200 }));
  return new Promise((resolve) => {
    setTimeout(() => resolve(new Response(body, { status: 200 })), delay);
  });
}

beforeEach(async () => {
  delays = {};
  silent = new Set();
  vi.stubGlobal("fetch", fakeFetch);
  session.setToken(null);
  session.deployment = {};
  whenChatReady(async () => {});
  // The public "Effacer mes brouillons": the store is a per-page-load singleton, so this
  // is what a fresh page load looks like from the outside.
  drafts.clearAll();
  await catalog.load("");
});

describe("open", () => {
  it("fills the editor from the templates and says which exercise it holds", async () => {
    const id = next();
    await exercise.open(id);
    expect(catalog.selectedId).toBe(id);
    expect(editor.exerciseId).toBe(id);
    expect(editor.text).toBe("// gabarit " + id);
    expect(exercise.statement).toEqual({ kind: "text", text: "Consigne de " + id });
  });

  it("prefers the draft over the template when there is one", async () => {
    const id = next();
    drafts.put(id, { "submission.c": "// mon travail" }, false);
    await exercise.open(id);
    expect(editor.text).toBe("// mon travail");
    expect(drafts.status).toBe("brouillon retrouvé");
  });

  it("TELLS THE CHAT to follow, once its chunk has registered", async () => {
    // The channel follows the editor; that is what let the second exercise menu be removed
    // from the screen.
    let followed = 0;
    whenChatReady(async () => {
      followed++;
    });
    await exercise.open(next());
    await exercise.open(next());
    expect(followed).toBe(2);
  });

  it("does not ask the chat anything when its chunk was never loaded", async () => {
    // Opening an exercise must NEVER fetch the chat's chunk on its own: that is the promise
    // that the anonymous path downloads nothing. A null callback is the whole mechanism, so
    // it must not throw.
    whenChatReady(undefined as unknown as () => Promise<void>);
    await expect(exercise.open(next())).resolves.toBeUndefined();
  });

  it("leaves `editor.exerciseId` NULL until the fill-in has come back", async () => {
    // Setting it earlier would attribute the previous exercise's code, still displayed, to
    // the new id at the next save.
    await exercise.open(next());
    const later = next();
    delays[later] = 20;
    const opening = exercise.open(later);
    expect(editor.exerciseId).toBeNull();
    await opening;
    expect(editor.exerciseId).toBe(later);
  });

  it("lets the LAST open win when two are started quickly", async () => {
    // Without the load token, the FIRST answer would land last and fill the editor with the
    // wrong exercise.
    const first = next();
    const second = next();
    delays[first] = 30;
    const slow = exercise.open(first);
    const fast = exercise.open(second);
    await Promise.all([slow, fast]);
    expect(editor.exerciseId).toBe(second);
    expect(editor.text).toBe("// gabarit " + second);
    expect(exercise.statement).toEqual({ kind: "text", text: "Consigne de " + second });
  });

  it("resets the submission, so the buttons do not stay busy on the new exercise", async () => {
    submission.startCooldown(9);
    expect(submission.busy).toBe(true);
    await exercise.open(next());
    expect(submission.busy).toBe(false);
  });

  it("unlocks the editor, so a previous team room does not leave it read-only", async () => {
    editor.lock(true);
    await exercise.open(next());
    expect(editor.readOnly).toBe(false);
  });

  it("saves the exercise being LEFT before switching", async () => {
    const left = next();
    await exercise.open(left);
    editor.typed("// écrit puis quitté");
    await exercise.open(next());
    expect(drafts.get(left)).toEqual({ "submission.c": "// écrit puis quitté" });
  });

  it("tells `failed` from `none` on the statement, which are not the same thing", async () => {
    // "No statement online" is a property of the exercise; a failure to fetch one is not,
    // and displaying them the same way is why nobody ever retried.
    const empty = next();
    silent.add(empty);
    await exercise.open(empty);
    expect(exercise.statement).toEqual({ kind: "none" });

    const offline = next();
    vi.stubGlobal("fetch", () => Promise.reject(new Error("hors ligne")));
    await exercise.open(offline);
    expect(exercise.statement).toEqual({ kind: "failed" });
    // AND THE EDITOR STILL WORKS: file names come from the catalog, so one can paste code
    // and submit.
    expect(editor.files.map((f) => f.name)).toEqual(["submission.c"]);
    expect(editor.exerciseId).toBe(offline);
  });

  it("does not cache a failed statement, so a network that comes back can retry", async () => {
    const id = next();
    vi.stubGlobal("fetch", () => Promise.reject(new Error("hors ligne")));
    await exercise.open(id);
    expect(exercise.statement.kind).toBe("failed");
    vi.stubGlobal("fetch", fakeFetch);
    await exercise.retryStatement();
    expect(exercise.statement).toEqual({ kind: "text", text: "Consigne de " + id });
  });
});
