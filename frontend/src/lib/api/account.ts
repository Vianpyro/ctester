// AN ACCOUNT'S OWN STATE. Every route here goes through the session, and NONE of
// them takes an identity from the request: `security.current_user()` is the only
// source of `account` server-side, which is what keeps one student from writing
// into another's state.
//
// A MUTE DATABASE ANSWERS 503, NEVER 200, and the read helpers return `null` for
// it. The page has to say "we do not know" -- showing a zero would tell somebody
// their work is gone.

import { authGet, authRequest } from "../auth/session.svelte";
import type {
  CollectionPayload,
  DraftPayload,
  PracticePayload,
  PreferencesPayload,
  ProgressPayload,
  StatesPayload,
} from "./types";

export const fetchStates = () => authGet<StatesPayload>("etats");

export const fetchPractice = () => authGet<PracticePayload>("pratique");

export const fetchDraft = (exerciseId: string) =>
  authGet<DraftPayload>("brouillon?ex=" + encodeURIComponent(exerciseId));

export const saveDraft = (exerciseId: string, files: Record<string, string>) =>
  authRequest<{ ok: boolean }>("brouillon", {
    method: "PUT",
    json: { exercise_id: exerciseId, files },
  });

export const fetchPreferences = () => authGet<PreferencesPayload>("preferences");

export const savePreferences = (theme: string) =>
  authRequest<{ ok: boolean }>("preferences", { method: "PUT", json: { theme } });

/**
 * Erase EVERYTHING kept for this student. The consent sentence shown before
 * redirecting to Rauthy promises this exists, so it exists.
 */
export const forgetMe = () => authRequest<{ ok: boolean }>("moi", { method: "DELETE" });

export const fetchProgress = () => authGet<ProgressPayload>("progres");

export const fetchCollection = () => authGet<CollectionPayload>("collection");
