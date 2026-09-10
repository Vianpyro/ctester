// THE ONE PLACE A REQUEST IS BUILT. Every call to the API goes through
// `request()`: the prefix, the JSON body, the decoding and the error
// normalisation live here and nowhere else.
//
// IT NEVER THROWS. A dead network, a Cloudflare block page, an nginx error in
// HTML: all of them come back as an `ApiResult` with a status and a null body.
// The caller then decides what to say, which is the whole point -- the API
// writes its refusals FOR THE STUDENT ("message trop long", "trop de
// soumissions"), and a client that collapsed them into a boolean would make
// somebody retry the exact same thing with the rule no longer in front of them.
//
// IT KNOWS NOTHING ABOUT AUTHENTICATION. The token, its renewal and the single
// retry live in `lib/auth/session.svelte.ts`, which builds on this. Keeping the
// two apart is what lets the anonymous path -- the default path -- use this
// module without pulling in a line of OIDC.

import { api } from "../config";

export interface ApiResult<T> {
  ok: boolean;
  /** 0 when the request never reached a server (network, CSP, offline). */
  status: number;
  /** `null` when the response carried no JSON, which is not always an error. */
  body: T | null;
}

export interface RequestOptions {
  method?: string;
  /** Serialised as JSON with the matching content type. */
  json?: unknown;
  headers?: Record<string, string>;
  /** Passed through to `fetch`; used by nothing but the hand-in ZIP today. */
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

/**
 * The raw response, for the one caller whose answer is not JSON: the hand-in
 * ZIP. Everything else wants `request()`.
 */
export function fetchApi(path: string, options: RequestOptions = {}): Promise<Response> {
  return fetch(api(path), buildInit(options));
}

/** A typed call that never throws. See this module's note. */
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

/** Decode a response we already have. Shared with the authenticated path. */
export async function decode<T>(answer: Response): Promise<ApiResult<T>> {
  let body: T | null = null;
  try {
    body = (await answer.json()) as T;
  } catch {
    // Not JSON: a Cloudflare block page, an nginx error, an empty 204. The
    // status still carries the useful half.
    body = null;
  }
  return { ok: answer.ok, status: answer.status, body };
}

/**
 * A public read, or `null`. Used for the three anonymous routes -- the catalog,
 * a statement, a quiz -- where "it did not arrive" is the only distinction the
 * page draws and it has its own message for it.
 */
export async function getPublic<T>(path: string): Promise<T | null> {
  const answer = await request<T>(path);
  return answer.ok ? answer.body : null;
}

/**
 * The message the API wrote, or a sentence saying what we do know instead.
 *
 * REUSED AS-IS WHEN THERE IS ONE, and that is deliberate: replacing "message
 * trop long" with "échec" makes somebody try the same thing again.
 */
export function refusal(answer: ApiResult<unknown> | null, fallback: string): string {
  if (!answer || answer.status === OFFLINE) return "le serveur est injoignable";
  const body = answer.body as { error?: string } | null;
  if (body && typeof body.error === "string" && body.error) return body.error;
  return fallback + " (réponse " + answer.status + ")";
}
