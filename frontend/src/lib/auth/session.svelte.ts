// THE SESSION, AND IT IS THE CORE'S HALF ONLY.
//
// What lives here: the ACCESS token, what this deployment offers, and the one
// passage point for an authenticated call. What does NOT live here: discovery,
// PKCE, the code exchange and the renewal -- those are `./oidc.ts`, reached by
// dynamic import, so the anonymous visitor (the default path) downloads not one
// line of them.
//
// THE ACCESS TOKEN IS NOT A SESSION. Rauthy hands out minutes, not hours; a tab
// left open through a lecture used to come back signed out, losing the draft
// indicator, the thread and the team room for no reason the student could see.
// `ensureValid()` renews a minute BEFORE expiry rather than after a 401 -- on a
// WebSocket a 401 costs a whole reconnection.
//
// AND THE SESSION IS NOT THE TAB EITHER, which is the half that was missing:
// the labs are a week apart, so the browser is closed between them. The
// credentials therefore live in `localStorage`, bounded by a deadline instead
// of by the tab -- `keys.ts` carries that decision and its price.
//
// THE REFRESH TOKEN NEVER LEAVES `./oidc.ts`. It goes to exactly one place, the
// issuer's token endpoint. It is not in `token()`, not in a header to our API,
// not in a WebSocket frame. `token()` means the ACCESS token and nothing else.

import { decode, fetchApi, type ApiResult, type RequestOptions } from "../api/client";
import { localGet, localSet, localDrop } from "../storage";
import { DEADLINE_KEY, EXPIRY_KEY, REFRESH_KEY, TOKEN_KEY } from "./keys";
import type { Deployment } from "../api/types";

const seconds = () => Math.floor(Date.now() / 1000);

/**
 * When this session stops being renewable, or 0 for "no deadline recorded".
 *
 * READ IN THE CORE, WRITTEN IN `oidc.ts`. It is a bare timestamp comparison and
 * it has to happen at boot, before anything knows whether OIDC is even on this
 * deployment -- so the reading half cannot live behind a dynamic import.
 */
const deadline = (): number => Number(localGet(DEADLINE_KEY)) || 0;

/**
 * Every trace of a session, gone. `signOut` calls it, and so does the boot
 * check below: a credential past its deadline must not survive being read.
 */
export function dropCredentials(): void {
  localDrop(TOKEN_KEY);
  localDrop(REFRESH_KEY);
  localDrop(EXPIRY_KEY);
  localDrop(DEADLINE_KEY);
}

/**
 * The stored access token, unless this session has sat unused past its
 * deadline -- in which case nothing is returned AND nothing is left behind.
 *
 * THIS IS WHAT REPLACES THE TAB. The credentials live in `localStorage` now
 * (see `keys.ts`), so closing the browser no longer ends the session; the
 * deadline does, and it is the only thing that does.
 */
function storedToken(): string | null {
  const until = deadline();
  if (until > 0 && seconds() >= until) {
    dropCredentials();
    return null;
  }
  return localGet(TOKEN_KEY) || null;
}

class Session {
  /** The access token, or null. Reactive: the bar redraws from it. */
  token = $state<string | null>(storedToken());
  /** What `/oidc.json` said. `null` until it answers -- and it may never. */
  deployment = $state<Deployment | null>(null);

  /** Bumped by `signOut`, so a renewal already in flight can be dropped. */
  generation = 0;

  get signedIn(): boolean {
    return !!this.token;
  }

  /** True when this deployment has a usable issuer, whatever the token says. */
  get oidcOffered(): boolean {
    const d = this.deployment;
    return !!(d && d.issuer && d.client_id);
  }

  get forumOffered(): boolean {
    return !!(this.deployment && this.deployment.forum);
  }

  get scratchOffered(): boolean {
    return !!(this.deployment && this.deployment.scratch);
  }

  get discordUrl(): string {
    return (this.deployment && this.deployment.discord) || "";
  }

  setToken(value: string | null): void {
    this.token = value || null;
    if (this.token) localSet(TOKEN_KEY, this.token);
    else localDrop(TOKEN_KEY);
  }
}

export const session = new Session();

// --- What a sign-out has to reach --------------------------------------------
// THE PRIVATE SCREENS LEAVE WITH THE SESSION. A projection, a thread, a ranking
// or a collection left on screen after a sign-out shows one account's standing
// to whoever sits down next. Each screen registers what it has to drop, rather
// than this module knowing every screen -- which would make the core depend on
// the lazy modules and undo the split.
const onSignOut = new Set<() => void>();

export function whenSignedOut(forget: () => void): () => void {
  onSignOut.add(forget);
  return () => onSignOut.delete(forget);
}

/**
 * End the session here and now. Synchronous on purpose: everything it clears
 * must be gone before any awaited work can put it back.
 */
export function signOut(): void {
  // FIRST, AND BEFORE ANYTHING ASYNCHRONOUS. A renewal in flight is answered
  // for a generation that no longer exists, so its grant is dropped instead of
  // writing a fresh session over the one just closed.
  session.generation++;
  session.setToken(null);
  // THE DEADLINE AND THE RENEWAL MATERIAL GO WITH IT, from the core rather than
  // from `oidc.ts`: a session restored from `localStorage` on a page that never
  // loaded the OIDC half still has both of them on disk, and a sign-out that
  // left them there would be a sign-out that only hid the session.
  dropCredentials();
  for (const forget of onSignOut) {
    try {
      forget();
    } catch {
      // A screen that fails to clear itself must not stop the others.
    }
  }
}

// --- The renewal, and it is loaded on demand ---------------------------------
// NO ACCOUNT MODULE MEANS NO OIDC AT ALL on this deployment: the token is
// whatever it is, and there is nothing to renew. All three sockets and every
// authenticated request call `ensureValid()` before leaving, so the guard lives
// once here instead of being copied into each of them -- where it would end up
// missing from one.

async function oidc() {
  return await import("./oidc");
}

/**
 * True when the access token can be used. False means "send it anyway and let
 * the 401 decide", which is the honest answer when there is nothing to renew.
 */
export async function ensureValid(): Promise<boolean> {
  if (!session.token) return false;
  if (!session.oidcOffered) return true;
  return await (await oidc()).ensureValidAccessToken();
}

/** One renewal, and the caller decides what a refusal means. */
export async function renew(): Promise<boolean> {
  if (!session.oidcOffered) return false;
  return await (await oidc()).refreshAccessToken();
}

// --- The authenticated call --------------------------------------------------

function authorized(options: RequestOptions): RequestOptions {
  return {
    ...options,
    headers: { ...(options.headers ?? {}), Authorization: "Bearer " + session.token },
  };
}

/**
 * ONE REFRESH, ONE RETRY, THEN OUT. A second 401 on a token minted seconds
 * earlier is not a timing problem; retrying again would only produce a page
 * that spins instead of one that says to sign in again.
 *
 * Returns the raw `Response` -- `authRequest` decodes it, and the hand-in ZIP
 * needs the body untouched.
 */
export async function authFetch(path: string, options: RequestOptions = {}): Promise<Response> {
  await ensureValid();
  // THE SESSION CLOSED WHILE WE WERE RENEWING IT. Sending `Bearer null` would
  // only be asking the API to say 401 on our behalf.
  if (!session.token) return new Response(null, { status: 401 });
  const answer = await fetchApi(path, authorized(options));
  if (answer.status !== 401) return answer;
  if (!(await renew())) {
    signOut(); // nothing to renew with, or it was refused
    return answer;
  }
  const second = await fetchApi(path, authorized(options));
  if (second.status === 401) signOut();
  return second;
}

/**
 * An authenticated call, typed, that never throws. A 401 that survives the
 * single retry ends the session -- there is nothing else it can mean.
 */
export async function authRequest<T>(
  path: string,
  options: RequestOptions = {},
): Promise<ApiResult<T>> {
  if (!session.token) return { ok: false, status: 401, body: null };
  let answer: Response;
  try {
    answer = await authFetch(path, options);
  } catch {
    return { ok: false, status: 0, body: null };
  }
  if (answer.status === 401) signOut();
  return await decode<T>(answer);
}

/** The read half: the payload, or `null` for "we do not know". */
export async function authGet<T>(path: string): Promise<T | null> {
  const answer = await authRequest<T>(path);
  return answer.ok ? answer.body : null;
}
