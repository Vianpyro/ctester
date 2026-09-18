import { catalog } from "./catalog.svelte";
import { drafts } from "./drafts.svelte";
import { editor, type EditorFile } from "./editor.svelte";
import { quiz } from "./quiz.svelte";
import { submission } from "./submission.svelte";
import { session } from "../auth/session.svelte";
import { localGet, localSet } from "../storage";
import type { Exercise } from "../domain/catalog";
import type { ExerciseDetail } from "../api/types";

const LAST_EXERCISE = "ctester.exercise";

export function dernierExercice(): string {
  return localGet(LAST_EXERCISE);
}

export type StatementState =
  | { kind: "loading" }
  | { kind: "text"; text: string }
  | { kind: "typst"; id: string; pages: number; staff: boolean; title: string; html: boolean }
  | { kind: "none" }
  | { kind: "failed" };

function statementOf(ex: Exercise, detail: ExerciseDetail): StatementState {
  if (detail.offline) return { kind: "failed" };
  if (detail.statement_format === "typst" && detail.statement_pages) {
    return {
      kind: "typst",
      id: ex.id,
      pages: detail.statement_pages,
      staff: ex.access !== "available",
      title: ex.label,
      html: detail.statement_html === true,
    };
  }
  return detail.statement ? { kind: "text", text: detail.statement } : { kind: "none" };
}

type RoomModule = typeof import("../collab/room.svelte");

let roomModule: RoomModule | null = null;

let followChannel: (() => Promise<void>) | null = null;

export function whenChatReady(follow: () => Promise<void>): void {
  followChannel = follow;
}

class ExerciseState {
  statement = $state<StatementState>({ kind: "loading" });
  #load = 0;

  async open(id: string): Promise<void> {
    roomModule?.room.leave();
    drafts.cancel();
    this.saveNow();
    catalog.selectedId = id;
    submission.reset();
    editor.exerciseId = null;
    editor.lock(false);
    const ex = catalog.selected;
    const thisLoad = ++this.#load;
    this.statement = { kind: "loading" };
    if (!ex) {
      this.statement = { kind: "none" };
      return;
    }
    localSet(LAST_EXERCISE, ex.id);
    if (ex.mode === "quiz") quiz.clear();
    const detail = await catalog.detail(ex.id);
    if (thisLoad !== this.#load) return;
    this.statement = statementOf(ex, detail);
    if (ex.mode === "quiz") {
      await quiz.load(ex.id);
      return;
    }
    await drafts.pullFromAccount(ex.id);
    if (thisLoad !== this.#load) return;
    this.#fillEditor(ex, detail.files);
    await this.#enterWorkspace(ex, thisLoad);
    await followChannel?.();
  }

  async retryStatement(): Promise<void> {
    const ex = catalog.selected;
    if (!ex) return;
    this.statement = { kind: "loading" };
    this.statement = statementOf(ex, await catalog.detail(ex.id));
  }

  #fillEditor(ex: Exercise, templateFiles: { name: string; template?: string }[]): void {
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

  async #enterWorkspace(ex: Exercise, thisLoad: number): Promise<void> {
    if (!ex.assignment || !session.signedIn) {
      roomModule?.room.leave();
      return;
    }
    if (!roomModule) roomModule = await import("../collab/room.svelte");
    if (thisLoad !== this.#load) return;
    await roomModule.room.enter(ex);
  }

  saveNow(): void {
    const id = editor.exerciseId;
    if (id === null || editor.activeFile === null) return;
    drafts.put(id, editor.sources, editor.sharedFor(id));
  }

  typed(): void {
    drafts.schedule(() => this.saveNow());
  }

  get shared(): boolean {
    return editor.sharedFor(editor.exerciseId);
  }
}

export const exercise = new ExerciseState();
