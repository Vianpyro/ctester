import { authGet, authRequest } from "../auth/session.svelte";
import type {
  CollectionPayload,
  DraftPayload,
  PracticePayload,
  PreferencesPayload,
  ProgressPayload,
  StatesPayload,
} from "./types";

export const fetchStates = () => authGet<StatesPayload>("states");

export const fetchPractice = () => authGet<PracticePayload>("practice");

export const fetchDraft = (exerciseId: string) =>
  authGet<DraftPayload>("draft?ex=" + encodeURIComponent(exerciseId));

export const saveDraft = (exerciseId: string, files: Record<string, string>) =>
  authRequest<{ ok: boolean }>("draft", {
    method: "PUT",
    json: { exercise_id: exerciseId, files },
  });

export const fetchPreferences = () => authGet<PreferencesPayload>("preferences");

export const savePreferences = (theme: string) =>
  authRequest<{ ok: boolean }>("preferences", { method: "PUT", json: { theme } });

export const forgetMe = () => authRequest<{ ok: boolean }>("account", { method: "DELETE" });

export const fetchProgress = () => authGet<ProgressPayload>("progress");

export const fetchCollection = () => authGet<CollectionPayload>("collection");
