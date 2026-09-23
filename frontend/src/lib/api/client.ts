import { api } from "../config";
import { t, tOr, type Params } from "../i18n.svelte";

export interface ApiResult<T> {
  ok: boolean;
  status: number;
  body: T | null;
}

export interface RequestOptions {
  method?: string;
  json?: unknown;
  headers?: Record<string, string>;
  raw?: boolean;
}

const OFFLINE = 0;

function buildInit(options: RequestOptions): RequestInit {
  const headers: Record<string, string> = { ...(options.headers ?? {}) };
  let body: string | undefined;
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.json);
  }
  return { method: options.method ?? "GET", headers, body };
}

export function fetchApi(path: string, options: RequestOptions = {}): Promise<Response> {
  return fetch(api(path), buildInit(options));
}

/** Never throws: network failures and non-JSON answers come back with `body: null`. */
export async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<ApiResult<T>> {
  let answer: Response;
  try {
    answer = await fetchApi(path, options);
  } catch {
    return { ok: false, status: OFFLINE, body: null };
  }
  return decode<T>(answer);
}

export async function decode<T>(answer: Response): Promise<ApiResult<T>> {
  let body: T | null = null;
  try {
    body = (await answer.json()) as T;
  } catch {
    body = null;
  }
  return { ok: answer.ok, status: answer.status, body };
}

export async function getPublic<T>(path: string): Promise<T | null> {
  const answer = await request<T>(path);
  return answer.ok ? answer.body : null;
}

// The server answers {"error": "<key>", "params": {...}}; the page words it. A key this
// page does not know (an API newer than the page) still shows, rather than nothing.
export function serverMessage(body: unknown): string {
  const b = body as { error?: unknown; params?: Params } | null;
  if (!b || typeof b.error !== "string" || !b.error) return "";
  return tOr("error." + b.error, b.error, b.params);
}

export function refusal(answer: ApiResult<unknown> | null, fallback: string): string {
  if (!answer || answer.status === OFFLINE) return t("api.unreachable");
  return (
    serverMessage(answer.body) || t("api.status", { message: fallback, status: answer.status })
  );
}
