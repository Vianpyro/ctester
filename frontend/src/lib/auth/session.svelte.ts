import { decode, fetchApi, type ApiResult, type RequestOptions } from "../api/client";
import { localGet, localSet, localDrop } from "../storage";
import { DEADLINE_KEY, EXPIRY_KEY, REFRESH_KEY, TOKEN_KEY } from "./keys";
import type { Deployment } from "../api/types";

const seconds = () => Math.floor(Date.now() / 1000);

const deadline = (): number => Number(localGet(DEADLINE_KEY)) || 0;

export function dropCredentials(): void {
  localDrop(TOKEN_KEY);
  localDrop(REFRESH_KEY);
  localDrop(EXPIRY_KEY);
  localDrop(DEADLINE_KEY);
}

function storedToken(): string | null {
  const until = deadline();
  if (until > 0 && seconds() >= until) {
    dropCredentials();
    return null;
  }
  return localGet(TOKEN_KEY) || null;
}

class Session {
  token = $state<string | null>(storedToken());
  deployment = $state<Deployment | null>(null);

  generation = 0;

  get signedIn(): boolean {
    return !!this.token;
  }

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

const onSignOut = new Set<() => void>();
const onLost = new Set<() => void>();

export function whenSignedOut(forget: () => void): () => void {
  onSignOut.add(forget);
  return () => onSignOut.delete(forget);
}

// Called when the session ends without the student asking, so the page can say so.
export function whenSessionLost(notice: () => void): () => void {
  onLost.add(notice);
  return () => onLost.delete(notice);
}

export function loseSession(): void {
  const had = !!session.token;
  signOut();
  if (!had) return;
  for (const notice of onLost) {
    try {
      notice();
    } catch {
    }
  }
}

export function signOut(): void {
  session.generation++;
  session.setToken(null);
  dropCredentials();
  for (const forget of onSignOut) {
    try {
      forget();
    } catch {
    }
  }
}

async function oidc() {
  return await import("./oidc");
}

export async function ensureValid(): Promise<boolean> {
  if (!session.token) return false;
  if (!session.oidcOffered) return true;
  return await (await oidc()).ensureValidAccessToken();
}

export async function renew(): Promise<boolean> {
  if (!session.oidcOffered) return false;
  return await (await oidc()).refreshAccessToken();
}

// After a refusal, only a token near its expiry is worth renewing: Rauthy refuses an early
// refresh and revokes the session for it, which would burn a refresh token still good for days.
export async function renewAfterRefusal(): Promise<boolean> {
  if (!session.oidcOffered) return false;
  const auth = await oidc();
  if (!auth.renewalDue()) return false;
  return await auth.refreshAccessToken();
}

function authorized(options: RequestOptions): RequestOptions {
  return {
    ...options,
    headers: { ...(options.headers ?? {}), Authorization: "Bearer " + session.token },
  };
}

export async function authFetch(path: string, options: RequestOptions = {}): Promise<Response> {
  await ensureValid();
  if (!session.token) return new Response(null, { status: 401 });
  const answer = await fetchApi(path, authorized(options));
  if (answer.status !== 401) return answer;
  // The deployment has not answered yet (a restart): nothing can be renewed, so nothing is dropped.
  if (!session.deployment) return answer;
  if (!(await renewAfterRefusal())) {
    loseSession();
    return answer;
  }
  const second = await fetchApi(path, authorized(options));
  if (second.status === 401) loseSession();
  return second;
}

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
  return await decode<T>(answer);
}

export async function authGet<T>(path: string): Promise<T | null> {
  const answer = await authRequest<T>(path);
  return answer.ok ? answer.body : null;
}
