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

/** The page as it stands now, so a slow load cannot overwrite a newer one. */
const still = (): string => quiz.shown.map((one) => one.exerciseId).join(",");

export function lastExercise(): string {
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

/** One consigne on screen. A quiz page showing three exercises shows three. */
export interface StatementView {
  id: string;
  /** Empty when there is only one: a lone consigne needs no exercise name above it. */
  title: string;
  state: StatementState;
}

class ExerciseState {
  statements = $state<StatementView[]>([{ id: "", title: "", state: { kind: "loading" } }]);
  #load = 0;

  /** The consigne of the exercise in focus, for the callers that only ever face one. */
  get statement(): StatementState {
    return this.statements[0]?.state ?? { kind: "loading" };
  }

  set statement(state: StatementState) {
    const id = catalog.selectedId;
    this.statements = [{ id, title: "", state }];
  }

  /**
   * The consignes of every exercise a quiz page holds. One place for them, in the order
   * the questions appear, so nothing is said twice. The panel owns this for a quiz, and
   * `open()` leaves it alone: the two would otherwise race, since the page is filled
   * before the open finishes resolving its detail.
   */
  async showStatements(wanted: { id: string; short: string }[]): Promise<void> {
    const asked = wanted.map((one) => one.id).join(",");
    const found: StatementView[] = [];
    for (const one of wanted) {
      const ex = catalog.catalog.find((e) => e.id === one.id);
      if (!ex) continue;
      const detail = await catalog.detail(ex.id);
      // Named only when there are several: one consigne needs no exercise name above it.
      found.push({
        id: ex.id,
        title: wanted.length > 1 ? one.short : "",
        state: statementOf(ex, detail),
      });
    }
    if (found.length && asked === still()) this.statements = found;
  }

  async open(id: string): Promise<void> {
    // Boot re-opens the exercise once the token arrives, to pick up the account draft and
    // the staff view. Keep the statement that is already on screen until the new one is
    // computed: collapsing it back to "loading" moves the whole page a second time.
    const same = catalog.selectedId === id && this.statement.kind !== "loading";
    roomModule?.room.leave();
    drafts.cancel();
    this.saveNow();
    catalog.selectedId = id;
    // A quiz page decides for itself which legs stay: an exercise still on screen must
    // keep its verdict, and a job that stops being polled is never recorded.
    if (catalog.selected?.mode !== "quiz") submission.reset();
    editor.exerciseId = null;
    editor.lock(false);
    const ex = catalog.selected;
    const thisLoad = ++this.#load;
    if (!same) this.statement = { kind: "loading" };
    if (!ex) {
      this.statement = { kind: "none" };
      return;
    }
    localSet(LAST_EXERCISE, ex.id);
    if (ex.mode === "quiz" && !same) quiz.clear();
    const detail = await catalog.detail(ex.id);
    if (thisLoad !== this.#load) return;
    // A quiz page is filled by the panel: it is the only place that knows how many
    // exercises fit on screen, and it sets the consignes to match.
    if (ex.mode === "quiz") return;
    this.statement = statementOf(ex, detail);
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
