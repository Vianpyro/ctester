import { authRequest } from "../auth/session.svelte";
import { getPublic, request } from "./client";
import type {
  Deployment,
  ExerciseDetail,
  PublishedRelease,
  QuizPayload,
} from "./types";

export const fetchCatalog = (): Promise<PublishedRelease | null> =>
  getPublic<PublishedRelease>("catalog.json");

type Wire = {
  statement?: unknown;
  statement_format?: unknown;
  statement_pages?: unknown;
  statement_html?: unknown;
  files?: unknown;
};

export async function fetchDetail(id: string, staff = false): Promise<ExerciseDetail> {
  const path = "exercise/" + encodeURIComponent(id) + ".json";
  const answer = staff ? await authRequest<Wire>(path) : await request<Wire>(path);
  if (!answer.ok || !answer.body) {
    return { statement: "", files: [], offline: true };
  }
  const d = answer.body;
  const detail: ExerciseDetail = {
    statement: typeof d.statement === "string" ? d.statement : "",
    files: Array.isArray(d.files) ? (d.files as ExerciseDetail["files"]) : [],
  };
  if (
    d.statement_format === "typst" &&
    typeof d.statement_pages === "number" &&
    Number.isInteger(d.statement_pages) &&
    d.statement_pages > 0
  ) {
    detail.statement_format = "typst";
    detail.statement_pages = d.statement_pages;
    if (d.statement_html === true) detail.statement_html = true;
  }
  return detail;
}

export async function fetchQuiz(id: string, staff = false): Promise<QuizPayload | null> {
  const path = "quiz/" + encodeURIComponent(id) + ".json";
  if (!staff) return getPublic<QuizPayload>(path);
  const answer = await authRequest<QuizPayload>(path);
  return answer.ok ? answer.body : null;
}

export const fetchDeployment = (): Promise<Deployment | null> =>
  getPublic<Deployment>("oidc.json");

export const fetchPresence = (id: string): Promise<{ n?: number } | null> =>
  getPublic<{ n?: number }>("live?id=" + encodeURIComponent(id));
