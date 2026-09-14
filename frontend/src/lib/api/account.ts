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

export const forgetMe = () => authRequest<{ ok: boolean }>("moi", { method: "DELETE" });

export const fetchProgress = () => authGet<ProgressPayload>("progres");

export const fetchCollection = () => authGet<CollectionPayload>("collection");
