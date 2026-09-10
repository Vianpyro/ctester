// THE ANONYMOUS ROUTES, AND THEY ARE CTESTER'S CORE. A student pastes their
// code, picks their exercise and gets a verdict with no account. Nothing here
// reads a token, and nothing here imports the session -- which is what keeps the
// default path free of a line of OIDC.

import { getPublic, request } from "./client";
import type {
  Deployment,
  ExerciseDetail,
  PublishedRelease,
  QuizPayload,
} from "./types";

/**
 * `/catalog.json` IS THE ONLY SOURCE. The `tps.json` fallback existed for pages
 * left in a student's cache during the v1/v2 switch; that window is closed, and
 * the rollback is once again what it is server-side -- a `current.json` pointer
 * to rewrite. A 404 here is a message, never an empty menu.
 */
export const fetchCatalog = (): Promise<PublishedRelease | null> =>
  getPublic<PublishedRelease>("catalog.json");

/**
 * An exercise's statement and templates, fetched when it is OPENED. They would
 * make up three quarters of the catalog for 73 exercises of which one is
 * displayed.
 *
 * ponytail: the URL keeps its historical `/tp/`. It lives in students' caches and
 * costs nothing; it moves the day deep links become `/exercise/<id>`.
 */
export async function fetchDetail(id: string): Promise<ExerciseDetail> {
  const answer = await request<{ statement?: unknown; files?: unknown }>(
    "tp/" + encodeURIComponent(id) + ".json",
  );
  if (!answer.ok || !answer.body) {
    // Network down, missing detail: the page is NOT blocked. The statement falls
    // back to its default message and the editor to empty templates -- file NAMES
    // come from the catalog and are always there, so one can still paste code and
    // submit. The caller must not cache this: a network that comes back has to be
    // able to retry.
    return { statement: "", files: [], offline: true };
  }
  const d = answer.body;
  return {
    statement: typeof d.statement === "string" ? d.statement : "",
    files: Array.isArray(d.files) ? (d.files as ExerciseDetail["files"]) : [],
  };
}

export const fetchQuiz = (id: string): Promise<QuizPayload | null> =>
  getPublic<QuizPayload>("quiz/" + encodeURIComponent(id) + ".json");

/**
 * What this deployment offers. It must answer an ANONYMOUS visitor, or the page
 * would never know a sign-in button exists.
 */
export const fetchDeployment = (): Promise<Deployment | null> =>
  getPublic<Deployment>("oidc.json");

/**
 * The presence heartbeat -- THE ONLY REQUEST THE ANONYMOUS PATH EVER EMITS, and a
 * deliberate exception: it reaches an in-memory dict server-side, never the
 * database or an account, and carries no token.
 */
export const fetchPresence = (id: string): Promise<{ n?: number } | null> =>
  getPublic<{ n?: number }>("live?id=" + encodeURIComponent(id));
