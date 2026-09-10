// THE FORUM AND THE CHAT, WHICH ARE THE SAME ROUTES. A chat key is `@chat:<id>`
// or `@chat:general`; a forum key is a bare exercise id. `@` cannot appear in any
// catalog identifier, so a chat key resolves for nobody and never becomes a path.
//
// THIS FILE DECIDES NOTHING about permissions. Who is a moderator, which messages
// are visible, who may delete or hide: all of it is settled by the API from the
// authenticated `sub`, and every route recomputes it. The `moderator` flag that
// comes back only ever decides what to DRAW.

import { authGet, authRequest } from "../auth/session.svelte";
import type {
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

/** Strip the chat prefix: the exercise a thread key is about, or the key itself. */
export const bareExercise = (key: string): string =>
  key.startsWith(CHAT_PREFIX) ? key.slice(CHAT_PREFIX.length) : key;

export const fetchThread = (key: string) =>
  authGet<ThreadPayload>("forum?ex=" + encodeURIComponent(key));

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
  authRequest<{ ok: boolean }>("forum/signalement", {
    method: "POST",
    json: kind ? { id, kind } : { id },
  });

/**
 * THE ONE TRANSITION: private -> group, and only on one's own message. The server
 * holds the rule in its `WHERE` (`account = %s AND visibility = 'private'`), so
 * the reverse is not expressible -- one cannot hide what others have already read.
 */
export const openToGroup = (id: string) =>
  authRequest<{ ok: boolean }>("forum/visibility", { method: "POST", json: { id } });

/**
 * `value` is +1, -1 or 0 (withdraw). The server refuses one's own message AND a
 * -1 on a QUESTION -- the button is not drawn, but that is not what holds the
 * rule: it is the `WHERE` of the statement, so it holds against a hand-made call
 * too. A question therefore cannot be buried by a vote, which is the promise of a
 * place built for people afraid to ask. IT GRANTS NOTHING: no XP, no achievement,
 * no card.
 */
export const vote = (id: string, value: -1 | 0 | 1) =>
  authRequest<{ ok: boolean }>("forum/helpful", { method: "POST", json: { id, value } });

export const moderate = (id: string, action: "hide" | "restore" | "retain" | "unretain" | "clear-name") =>
  authRequest<{ ok: boolean }>("forum/moderation", { method: "POST", json: { id, action } });

export const fetchModeration = () => authGet<ModerationPayload>("forum/moderation");

export const fetchHelp = () => authGet<HelpPayload>("forum/help");

export const fetchTop = () => authGet<TopPayload>("forum/top");

export const fetchProfile = () => authGet<ForumProfile>("forum/profil");

/**
 * WRITING A PROFILE REWRITES IT IN FULL. `forum_profile` is append-only and the
 * last row IS the profile: a partial write would reset the fields it omits, and
 * the one it would reset most often is a visibility checkbox.
 */
export const saveProfile = (payload: ForumProfileIn) =>
  authRequest<{ ok: boolean }>("forum/profil", { method: "POST", json: payload });

/**
 * THE SEARCH AND THE DUPLICATE DETECTION ARE THE SAME ROUTE. Privacy is the
 * `WHERE` (`visibility = 'thread' OR account = me`): a private forum question
 * never comes back as "somebody already asked this". A moderator gets no
 * exception -- they read threads, and one branch fewer is one branch fewer to get
 * wrong.
 */
export async function search(terms: string): Promise<SearchResult[]> {
  if (!String(terms || "").trim()) return [];
  const answer = await authGet<{ results?: SearchResult[] }>(
    "forum/search?q=" + encodeURIComponent(terms),
  );
  return answer && Array.isArray(answer.results) ? answer.results : [];
}

/**
 * THE PERMALINK, and it exists because a search result three thousand messages old
 * is in the window of no thread: without it, the search shows excerpts one cannot
 * open.
 */
export const fetchConversation = (id: string) =>
  authGet<ThreadPayload>("forum/message?id=" + encodeURIComponent(id));

/** Redraw the masked name. The URL keeps its `leaderboard/` past: see CLAUDE.md. */
export const redrawAlias = () =>
  authRequest<{ ok: boolean }>("leaderboard/alias", { method: "POST", json: {} });
