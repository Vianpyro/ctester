import { localDrop, localGet, localSet } from "../storage";
import { clockNow } from "../domain/labels";
import { fetchDraft, saveDraft } from "../api/account";
import { session } from "../auth/session.svelte";

const DRAFTS_KEY = "ctester.drafts";
const SAVE_DELAY = 1500;

type DraftMap = Record<string, Record<string, string>>;

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

  status = $state(this.#initialStatus());
  statusFailed = $state(false);
  exportNote = $state("");
  exportFailed = $state(false);
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

  sayExport(text: string, failed = false): void {
    this.exportNote = text;
    this.exportFailed = failed;
  }

  #persist(): boolean {
    if (!localSet(DRAFTS_KEY, JSON.stringify(this.#store))) {
      this.say("NON enregistré — garde une copie de ton code", true);
      return false;
    }
    this.say("enregistré sur cet appareil · " + clockNow());
    this.hasAny = true;
    return true;
  }

  put(exerciseId: string, files: Record<string, string>, shared: boolean): void {
    this.#store[exerciseId] = { ...files };
    if (!this.#persist()) return;
    if (shared || !session.signedIn) return;
    void this.#syncToAccount(exerciseId, files);
  }

  putLocal(exerciseId: string, values: Record<string, string>): void {
    if (!exerciseId) return;
    this.#store[exerciseId] = { ...values };
    this.#persist();
  }

  async #syncToAccount(exerciseId: string, files: Record<string, string>): Promise<void> {
    const answer = await saveDraft(exerciseId, files);
    if (this.#current !== exerciseId) return;
    this.say(
      answer.ok
        ? "enregistré sur ton compte · " + clockNow()
        : "enregistré sur cet appareil seulement — pas sur ton compte",
    );
  }

  #current = "";

  opened(exerciseId: string, found: boolean): void {
    this.#current = exerciseId;
    this.say(found ? "brouillon retrouvé" : "enregistrement automatique");
  }

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

  async pullFromAccount(exerciseId: string): Promise<void> {
    if (!session.signedIn) return;
    const answer = await fetchDraft(exerciseId);
    const clean = sanitizeDrafts({ [exerciseId]: answer?.sources });
    const held = clean[exerciseId];
    if (held && Object.keys(held).length) this.#store[exerciseId] = held;
  }
}

export const drafts = new DraftStore();
