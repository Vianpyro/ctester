// THE DRAFTS, AND WHERE THEY LIVE. `localStorage` is this device's memory; the
// account carries them between machines. Both are written, and the status line
// SAYS WHICH -- "saved at 14:32" does not answer the real question, which is "will
// I find this again on the other machine?".
//
// THE STATUS LINE IS PERMANENT. It used to stay EMPTY until the student had typed
// for a second and a half: somebody who just opened an exercise, or pasted their
// code without touching it again, had no way to know whether their work was safe.

import { localDrop, localGet, localSet } from "../storage";
import { clockNow } from "../domain/labels";
import { fetchDraft, saveDraft } from "../api/account";
import { session } from "../auth/session.svelte";

const DRAFTS_KEY = "ctester.drafts";
/** The draft can wait a second and a half; a teammate watching cannot. */
const SAVE_DELAY = 1500;

type DraftMap = Record<string, Record<string, string>>;

/**
 * WHAT COMES OUT OF STORAGE IS NOT TRUSTED DATA. A hand-edited or half-written
 * entry must not reach the editor: only well-formed `{exercise: {file: string}}`
 * survives, entry by entry, so one poisoned exercise does not lose the others.
 */
export function sanitizeDrafts(raw: unknown): DraftMap {
  const clean: DraftMap = {};
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return clean;
  for (const [exercise, files] of Object.entries(raw as Record<string, unknown>)) {
    if (!files || typeof files !== "object" || Array.isArray(files)) continue;
    const kept: Record<string, string> = {};
    for (const [name, text] of Object.entries(files as Record<string, unknown>)) {
      if (typeof text === "string") kept[name] = text;
    }
    clean[exercise] = kept;
  }
  return clean;
}

function readStore(): DraftMap {
  try {
    return sanitizeDrafts(JSON.parse(localGet(DRAFTS_KEY) || "null"));
  } catch {
    return {};
  }
}

class DraftStore {
  #store: DraftMap = readStore();

  /** What the indicator above the code says right now. */
  status = $state(this.#initialStatus());
  statusFailed = $state(false);
  /** The export's own slot, next to its button. See below. */
  exportNote = $state("");
  exportFailed = $state(false);
  /** Whether there is anything to clear. */
  hasAny = $state(Object.keys(readStore()).length > 0);

  #timer: ReturnType<typeof setTimeout> | null = null;

  #initialStatus(): string {
    return "enregistrement automatique";
  }

  get(exerciseId: string): Record<string, string> | null {
    return this.#store[exerciseId] ?? null;
  }

  say(text: string, failed = false): void {
    this.status = text;
    this.statusFailed = failed;
  }

  /**
   * THE EXPORT KEEPS ITS OWN SPOT. The two messages used to share a slot and erase
   * each other: "main.c exported" would replace "draft NOT saved", which was the
   * page's only data-loss warning.
   */
  sayExport(text: string, failed = false): void {
    this.exportNote = text;
    this.exportFailed = failed;
  }

  /** The write alone, shared with the quiz -- it has a draft of the same shape. */
  #persist(): boolean {
    if (!localSet(DRAFTS_KEY, JSON.stringify(this.#store))) {
      this.say("NON enregistré — garde une copie de ton code", true);
      return false;
    }
    // "ON THIS DEVICE" IS THE HALF THAT WAS MISSING. Without an account, work does
    // not follow from one machine to another, and that is exactly what a lab
    // student must know BEFORE going home. `syncToAccount` replaces this text with
    // "on your account" if the copy succeeds.
    this.say("enregistré sur cet appareil · " + clockNow());
    this.hasAny = true;
    return true;
  }

  /** Store one exercise's files locally, and on the account when there is one. */
  put(exerciseId: string, files: Record<string, string>, shared: boolean): void {
    this.#store[exerciseId] = { ...files };
    if (!this.#persist()) return;
    // A SHARED DOCUMENT IS NOT AN INDIVIDUAL DRAFT. When a team session owns this
    // exercise it does its own saving, into the TEAM's document; copying the same
    // text into `exercise_draft` on top would write four rows for one piece of
    // work and blur the one distinction the whole feature rests on. The LOCAL copy
    // above stays: it costs nothing and it is a real backup.
    if (shared || !session.signedIn) return;
    void this.#syncToAccount(exerciseId, files);
  }

  /** The quiz's answers: same store, same "Effacer mes brouillons" button. Local
   * only -- `/brouillon` validates the file names an exercise declares, and a
   * question id is not one of them. */
  putLocal(exerciseId: string, values: Record<string, string>): void {
    if (!exerciseId) return;
    this.#store[exerciseId] = { ...values };
    this.#persist();
  }

  async #syncToAccount(exerciseId: string, files: Record<string, string>): Promise<void> {
    const answer = await saveDraft(exerciseId, files);
    // THE EXERCISE MAY HAVE CHANGED DURING THE ROUND TRIP: only announce for the
    // one still on screen, or the indicator would talk about another file.
    if (this.#current !== exerciseId) return;
    // SUCCESS IS ALSO SAID, NOT ONLY FAILURE. "On your account" is the only thing
    // that answers "will I find my code again at home?", and that is the question
    // a lab student asks on their way out.
    this.say(
      answer.ok
        ? "enregistré sur ton compte · " + clockNow()
        : "enregistré sur cet appareil seulement — pas sur ton compte",
    );
  }

  /** Which exercise the indicator is currently talking about. */
  #current = "";

  opened(exerciseId: string, found: boolean): void {
    this.#current = exerciseId;
    // THE STARTING STATE IS SAID TOO: "draft found" answers "am I back where I
    // left off?" before one has to read the code, and on a fresh exercise saying
    // that saving is automatic avoids hunting for a missing "Enregistrer" button.
    this.say(found ? "brouillon retrouvé" : "enregistrement automatique");
  }

  /** Debounced autosave, driven by typing. */
  schedule(save: () => void): void {
    this.cancel();
    this.#timer = setTimeout(save, SAVE_DELAY);
  }

  cancel(): void {
    if (this.#timer) clearTimeout(this.#timer);
    this.#timer = null;
  }

  clearAll(): void {
    this.cancel();
    for (const id of Object.keys(this.#store)) delete this.#store[id];
    localDrop(DRAFTS_KEY);
    this.say("brouillons effacés");
    this.hasAny = false;
  }

  /**
   * The account's copy for one exercise, merged in when it has something. Called
   * when an exercise opens, so work started on another machine is there.
   */
  async pullFromAccount(exerciseId: string): Promise<void> {
    if (!session.signedIn) return;
    const answer = await fetchDraft(exerciseId);
    const clean = sanitizeDrafts({ [exerciseId]: answer?.sources });
    const held = clean[exerciseId];
    if (held && Object.keys(held).length) this.#store[exerciseId] = held;
  }
}

export const drafts = new DraftStore();
