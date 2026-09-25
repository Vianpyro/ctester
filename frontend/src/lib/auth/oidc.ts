import { dropCredentials, loseSession, session, whenSignedOut } from "./session.svelte";
import { t } from "../i18n.svelte";
import { localGet, localSet, sessionGet, sessionSet, sessionDrop } from "../storage";
import {
  DEADLINE_KEY,
  EXPIRY_KEY,
  PKCE_KEY,
  REFRESH_KEY,
  RETURN_KEY,
  SESSION_MAX_DAYS,
} from "./keys";

// Rauthy accepts a refresh token only in the access token's last minute, and using it
// earlier revokes all of the user's sessions. 30 s stays inside that window.
export const REFRESH_MARGIN = 30;

export const ISSUER_NBF_OFFSET = 60;

interface Grant {
  access_token?: string;
  refresh_token?: string;
  expires_in?: number;
}

interface Discovery {
  authorization_endpoint: string;
  token_endpoint: string;
}

function config(): { issuer: string; client_id: string } {
  const c = session.deployment;
  if (!c || !c.issuer || !c.client_id) {
    throw new Error(t("oidc.unconfigured"));
  }
  return { issuer: c.issuer, client_id: c.client_id };
}

let discovered: Discovery | null = null;

async function discovery(): Promise<Discovery> {
  if (!discovered) {
    const answer = await fetch(config().issuer + "/.well-known/openid-configuration");
    discovered = (await answer.json()) as Discovery;
  }
  return discovered;
}

const seconds = () => Math.floor(Date.now() / 1000);
const storedRefreshToken = () => localGet(REFRESH_KEY);
const expiresAt = () => Number(localGet(EXPIRY_KEY)) || 0;
const deadline = () => Number(localGet(DEADLINE_KEY)) || 0;

function pushDeadline(): void {
  localSet(DEADLINE_KEY, String(seconds() + SESSION_MAX_DAYS * 86400));
}

const abandoned = (): boolean => {
  const until = deadline();
  return until > 0 && seconds() >= until;
};

function nearlyExpired(): boolean {
  const at = expiresAt();
  return at > 0 && seconds() >= at - REFRESH_MARGIN;
}

// An unknown lifetime (a session from before it was stored) may be renewed at any time.
export function renewalDue(): boolean {
  return expiresAt() === 0 || nearlyExpired();
}

function storeGrant(granted: Grant): void {
  if (typeof granted.refresh_token === "string" && granted.refresh_token) {
    localSet(REFRESH_KEY, granted.refresh_token);
  }
  const life = Number(granted.expires_in);
  localSet(EXPIRY_KEY, String(Number.isFinite(life) && life > 0 ? seconds() + life : 0));
  pushDeadline();
  session.setToken(granted.access_token ?? null);
}

async function askForRefresh(carried: string): Promise<Grant | null> {
  let granted: Grant | null = null;
  try {
    const doc = await discovery();
    const answer = await fetch(doc.token_endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "refresh_token",
        client_id: config().client_id,
        refresh_token: carried,
      }).toString(),
    });
    granted = answer.ok ? ((await answer.json()) as Grant) : null;
  } catch {
    granted = null;
  }
  return granted && typeof granted.access_token === "string" ? granted : null;
}

// One refresh in flight: with token rotation, concurrent refreshes invalidate each other.
let refreshing: Promise<boolean> | null = null;

export function refreshAccessToken(): Promise<boolean> {
  if (refreshing) return refreshing;
  if (abandoned()) {
    dropCredentials();
    loseSession();
    return Promise.resolve(false);
  }
  const carried = storedRefreshToken();
  if (!carried) return Promise.resolve(false);
  const started = session.generation;
  refreshing = askForRefresh(carried).then(
    (granted) => {
      refreshing = null;
      // Signed out meanwhile: a late answer must not reopen the session.
      if (started !== session.generation) return false;
      if (!granted) {
        forgetRenewal();
        loseSession();
        return false;
      }
      storeGrant(granted);
      return true;
    },
    () => {
      refreshing = null;
      return false;
    },
  );
  return refreshing;
}

export async function ensureValidAccessToken(): Promise<boolean> {
  if (!session.token) return false;
  if (!nearlyExpired()) return true;
  return await refreshAccessToken();
}

function forgetRenewal(): void {
  refreshing = null;
  dropCredentials();
}

const base64url = (bytes: Uint8Array): string =>
  btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");

const randomToken = () => base64url(crypto.getRandomValues(new Uint8Array(32)));

async function challengeFor(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64url(new Uint8Array(digest));
}

const redirectUri = () => location.origin + location.pathname;

export async function startSignIn(): Promise<void> {
  const doc = await discovery();
  const verifier = randomToken();
  const state = randomToken();
  sessionSet(PKCE_KEY, JSON.stringify({ verifier, state }));
  sessionSet(RETURN_KEY, location.search);
  const params = new URLSearchParams({
    response_type: "code",
    client_id: config().client_id,
    redirect_uri: redirectUri(),
    scope: "openid profile offline_access groups",
    state,
    code_challenge: await challengeFor(verifier),
    code_challenge_method: "S256",
  });
  location.assign(doc.authorization_endpoint + "?" + params.toString());
}

export async function finishSignIn(code: string, state: string): Promise<boolean> {
  const saved = sessionGet(PKCE_KEY);
  sessionDrop(PKCE_KEY);
  sessionDrop(RETURN_KEY);
  let pkce: { verifier?: string; state?: string } | null = null;
  try {
    pkce = JSON.parse(saved) as { verifier?: string; state?: string };
  } catch {
    pkce = null;
  }
  // Without this check, a link carrying someone else's code would sign in as them.
  if (!pkce || !pkce.state || pkce.state !== state) return false;
  const doc = await discovery();
  const answer = await fetch(doc.token_endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      code,
      client_id: config().client_id,
      redirect_uri: redirectUri(),
      code_verifier: pkce.verifier ?? "",
    }).toString(),
  });
  let granted: Grant | null = null;
  try {
    granted = (await answer.json()) as Grant;
  } catch {
    granted = null;
  }
  if (!answer.ok || !granted || !granted.access_token) return false;
  storeGrant(granted);
  return true;
}

whenSignedOut(forgetRenewal);
