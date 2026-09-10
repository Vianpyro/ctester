// OPENING AN EXERCISE, AND THE ORDER IS THE WHOLE FILE.
//
// This is the one transaction that touches several owners at once -- the catalog's
// selection, the editor's files, the draft store, the submission state, the team
// room and the chat dock -- so it lives in one place with the sequence written
// down, rather than spread across the components that trigger it.
//
// A LOAD TOKEN GUARDS EVERY STEP. The statement and the templates arrive over the
// network; without the token, switching exercises twice quickly would let the
// FIRST answer land last and fill the editor with the wrong exercise.

import { catalog } from "./catalog.svelte";
import { drafts } from "./drafts.svelte";
import { editor, type EditorFile } from "./editor.svelte";
import { quiz } from "./quiz.svelte";
import { submission } from "./submission.svelte";
import { session } from "../auth/session.svelte";
import type { Exercise } from "../domain/catalog";

/** The statement's three states -- and they are three, not two. */
export type StatementState =
  | { kind: "loading" }
  | { kind: "text"; text: string }
  /** "No statement online" is a property of the exercise... */
  | { kind: "none" }
  /** ...and this is a failure to fetch one. The student used to see them the
   *  same way, so they never retried -- when a reload would have been enough. */
  | { kind: "failed" };

// --- The two optional features an open exercise can reach ---------------------
// Both are lazy chunks. The module reference is kept once imported, so LEAVING a
// room never has to download the room's code -- which would be absurd, and would
// also mean the anonymous path could pull in Yjs by switching exercises.

type RoomModule = typeof import("../collab/room.svelte");

let roomModule: RoomModule | null = null;

/**
 * WHAT THE CHAT ASKS TO BE TOLD, and only once its chunk exists.
 *
 * The channel follows the editor -- that is what let the second exercise menu be removed
 * from the screen -- but opening an exercise must NEVER fetch the chat's chunk on its own:
 * that is the promise that the anonymous path downloads nothing. So the core holds a
 * nullable callback and the chat registers into it on load, exactly the way a screen
 * registers what a sign-out has to clear. Nothing here imports the chat.
 */
let followChannel: (() => Promise<void>) | null = null;

export function whenChatReady(follow: () => Promise<void>): void {
  followChannel = follow;
}

class ExerciseState {
  statement = $state<StatementState>({ kind: "loading" });
  #load = 0;

  /** The one entry point. `id` is what the menu chose. */
  async open(id: string): Promise<void> {
    // THE OLD ROOM CLOSES BEFORE THE NEW ONE OPENS. Without this, the socket of
    // the exercise being left would still be applying remote changes into an
    // editor that now holds a different exercise.
    roomModule?.room.leave();
    drafts.cancel();
    this.saveNow();
    catalog.selectedId = id;
    submission.reset();
    // `editor.exerciseId` IS WHAT THE EDITOR HOLDS, not what the menu shows.
    // Filling it in goes through the network: setting it here would attribute the
    // previous exercise's code, still displayed, to the new id at the next save.
    editor.exerciseId = null;
    editor.lock(false);
    const ex = catalog.selected;
    const thisLoad = ++this.#load;
    this.statement = { kind: "loading" };
    if (!ex) {
      this.statement = { kind: "none" };
      return;
    }
    if (ex.mode === "quiz") quiz.clear();
    const detail = await catalog.detail(ex.id);
    if (thisLoad !== this.#load) return;
    this.statement = detail.offline
      ? { kind: "failed" }
      : detail.statement
        ? { kind: "text", text: detail.statement }
        : { kind: "none" };
    if (ex.mode === "quiz") {
      await quiz.load(ex.id);
      return;
    }
    // The account's copy first, so work started on another machine is there.
    await drafts.pullFromAccount(ex.id);
    if (thisLoad !== this.#load) return;
    this.#fillEditor(ex, detail.files);
    // AFTER `#fillEditor`, ALWAYS. The workspace replaces what the editor holds
    // with the TEAM's document; running it first would have the individual draft
    // overwrite the shared one a moment later, which is the one bug in this
    // feature that would destroy other people's work.
    await this.#enterWorkspace(ex, thisLoad);
    // THE CHANNEL FOLLOWS THE EDITOR, and only if the chat is already there. See
    // `whenChatReady` above.
    await followChannel?.();
  }

  /** Retry a statement that did not arrive. No reload: unsaved code would go. */
  async retryStatement(): Promise<void> {
    const ex = catalog.selected;
    if (!ex) return;
    this.statement = { kind: "loading" };
    const detail = await catalog.detail(ex.id);
    this.statement = detail.offline
      ? { kind: "failed" }
      : detail.statement
        ? { kind: "text", text: detail.statement }
        : { kind: "none" };
  }

  #fillEditor(ex: Exercise, templateFiles: { name: string; template?: string }[]): void {
    // NAMES are authoritative and come from the catalog -- the allow-list the API
    // checks a submission against. Templates come from the detail and may be
    // missing: a tab with no template opens empty.
    const templates: Record<string, string> = {};
    for (const f of templateFiles ?? []) templates[f.name] = f.template ?? "";
    const declared = ex.files.length ? ex.files : [{ name: "submission.c" }];
    const files: EditorFile[] = declared.map((f) => ({
      name: f.name,
      template: templates[f.name] ?? "",
    }));
    const held = drafts.get(ex.id);
    drafts.opened(ex.id, !!held);
    editor.open(ex.id, files, held);
  }

  /**
   * THE TEAM WORKSPACE IS A LAZY CHUNK, and it only comes down when the exercise
   * being opened says it belongs to an assignment. The anonymous visitor never
   * fetches it; neither does a signed-in student working an ordinary lab.
   */
  async #enterWorkspace(ex: Exercise, thisLoad: number): Promise<void> {
    if (!ex.assignment || !session.signedIn) {
      // LEAVING IS NOT CONDITIONAL ON HAVING ENTERED: switching from an assignment
      // exercise to an ordinary one must close the socket, and only the room knows
      // whether one is open.
      roomModule?.room.leave();
      return;
    }
    if (!roomModule) roomModule = await import("../collab/room.svelte");
    if (thisLoad !== this.#load) return;
    await roomModule.room.enter(ex);
  }

  /** Write the editor's current text into the draft store, now. */
  saveNow(): void {
    const id = editor.exerciseId;
    if (id === null || editor.activeFile === null) return;
    drafts.put(id, editor.sources, editor.sharedFor(id));
  }

  /** Typing: repaint is the component's, the debounce is the store's. */
  typed(): void {
    drafts.schedule(() => this.saveNow());
  }

  /** True while a team room holds the exercise the editor is on. */
  get shared(): boolean {
    return editor.sharedFor(editor.exerciseId);
  }
}

export const exercise = new ExerciseState();
