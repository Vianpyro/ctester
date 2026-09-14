import { api } from "../config";

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

export function refusal(answer: ApiResult<unknown> | null, fallback: string): string {
  if (!answer || answer.status === OFFLINE) return "le serveur est injoignable";
  const body = answer.body as { error?: string } | null;
  if (body && typeof body.error === "string" && body.error) return body.error;
  return fallback + " (réponse " + answer.status + ")";
}
