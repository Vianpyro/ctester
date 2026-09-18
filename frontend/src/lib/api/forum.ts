import { authGet, authRequest } from "../auth/session.svelte";
import type {
  ActivityPayload,
  ForumProfile,
  ForumProfileIn,
  HelpPayload,
  ModerationPayload,
  SearchResult,
  ThreadPayload,
  TopPayload,
  Visibility,
} from "./types";

export const CHAT_PREFIX = "@chat:";
export const CHAT_GENERAL = CHAT_PREFIX + "general";

export const bareExercise = (key: string): string =>
  key.startsWith(CHAT_PREFIX) ? key.slice(CHAT_PREFIX.length) : key;

export const fetchThread = (key: string) =>
  authGet<ThreadPayload>("forum?ex=" + encodeURIComponent(key));

export const fetchActivity = () => authGet<ActivityPayload>("forum/activity");

export interface PostExtra {
  reply_to?: string;
  exercise_id?: string;
  step?: string;
  blocked_kind?: string;
  visibility?: Visibility;
}

export const post = (key: string, text: string, extra: PostExtra = {}) =>
  authRequest<{ ok: boolean }>("forum", {
    method: "POST",
    json: { exercise_id: key, text, ...extra },
  });

export const remove = (id: string) =>
  authRequest<{ ok: boolean }>("forum?id=" + encodeURIComponent(id), { method: "DELETE" });

export const report = (id: string, kind?: "name") =>
  authRequest<{ ok: boolean }>("forum/report", {
    method: "POST",
    json: kind ? { id, kind } : { id },
  });

export const openToGroup = (id: string) =>
  authRequest<{ ok: boolean }>("forum/visibility", { method: "POST", json: { id } });

export const vote = (id: string, value: -1 | 0 | 1) =>
  authRequest<{ ok: boolean }>("forum/helpful", { method: "POST", json: { id, value } });

export const moderate = (id: string, action: "hide" | "restore" | "retain" | "unretain" | "clear-name") =>
  authRequest<{ ok: boolean }>("forum/moderation", { method: "POST", json: { id, action } });

export const fetchModeration = () => authGet<ModerationPayload>("forum/moderation");

export const fetchHelp = () => authGet<HelpPayload>("forum/help");

export const fetchTop = () => authGet<TopPayload>("forum/top");

export const fetchProfile = () => authGet<ForumProfile>("forum/profile");

export const saveProfile = (payload: ForumProfileIn) =>
  authRequest<{ ok: boolean }>("forum/profile", { method: "POST", json: payload });

export async function search(terms: string): Promise<SearchResult[]> {
  if (!String(terms || "").trim()) return [];
  const answer = await authGet<{ results?: SearchResult[] }>(
    "forum/search?q=" + encodeURIComponent(terms),
  );
  return answer && Array.isArray(answer.results) ? answer.results : [];
}

export const fetchConversation = (id: string) =>
  authGet<ThreadPayload>("forum/message?id=" + encodeURIComponent(id));

export const redrawAlias = () =>
  authRequest<{ ok: boolean }>("leaderboard/alias", { method: "POST", json: {} });
