// THE OIDC LIFECYCLE, AND IT LIVES ONLY HERE. Discovery, PKCE, the code
// exchange, the refresh. Reached by dynamic import from
// `session.svelte.ts`, so the anonymous visitor downloads none of it.
//
// THE REFRESH TOKEN NEVER LEAVES THIS FILE. It goes to exactly one place, the
// issuer's token endpoint. The three `fetch` calls below carry ABSOLUTE URLs
// that came from the issuer -- they must NOT go through `api()`, which would
// send them to our own API instead.
//
// NO REFRESH TOKEN IS NOT AN OUTAGE. An issuer that declines `offline_access`
// leaves the page behaving exactly as it did before this existed: the access
// token lives out its life and the 401 that follows ends the session. Nothing
// signs itself out for the absence of renewal material.

import { session, signOut, whenSignedOut } from "./session.svelte";
import { sessionGet, sessionSet, sessionDrop } from "../storage";
import { EXPIRY_KEY, PKCE_KEY, REFRESH_KEY, RETURN_KEY } from "./keys";

/** Renewed a minute BEFORE it dies, not after a request has already failed. */
const REFRESH_MARGIN = 60;

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
    throw new Error("la configuration de connexion n'est pas disponible");
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
const storedRefreshToken = () => sessionGet(REFRESH_KEY);
const expiresAt = () => Number(sessionGet(EXPIRY_KEY)) || 0;

/**
 * AN UNKNOWN LIFETIME IS NOT AN EXPIRED ONE. A provider that omits `expires_in`
 * leaves us with 0, and renewing on every request would turn one student's page
 * into a load generator aimed at the issuer. We then wait for the 401, which is
 * exactly the old behaviour.
 */
function nearlyExpired(): boolean {
  const at = expiresAt();
  return at > 0 && seconds() >= at - REFRESH_MARGIN;
}

/**
 * What the token endpoint gave us, written down. Both grant types come through
 * here, so rotation and expiry can only be handled one way.
 */
function storeGrant(granted: Grant): void {
  // ROTATION IS FOLLOWED: Rauthy may hand back a NEW refresh token and kill the
  // old one on the spot. Keeping the old one works exactly once and then signs
  // the student out an hour later with nothing on screen to explain it. Absent
  // means "keep using the one you have", not "forget it".
  if (typeof granted.refresh_token === "string" && granted.refresh_token) {
    sessionSet(REFRESH_KEY, granted.refresh_token);
  }
  const life = Number(granted.expires_in);
  sessionSet(EXPIRY_KEY, String(Number.isFinite(life) && life > 0 ? seconds() + life : 0));
  // LAST, AND ON PURPOSE: setting the token redraws the bar, and it must never
  // announce a session whose renewal material is only half written down.
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
    granted = null; // network, CSP, provider down: all the same answer
  }
  return granted && typeof granted.access_token === "string" ? granted : null;
}

/**
 * ONE REFRESH IN FLIGHT, AND ONE ONLY. Five calls discovering the expiry at the
 * same moment must produce ONE request: with rotation on, the other four would
 * each burn the token the first one is using, and whichever lost would sign the
 * student out.
 */
let refreshing: Promise<boolean> | null = null;

export function refreshAccessToken(): Promise<boolean> {
  if (refreshing) return refreshing;
  const carried = storedRefreshToken();
  if (!carried) return Promise.resolve(false);
  const started = session.generation;
  refreshing = askForRefresh(carried).then(
    (granted) => {
      refreshing = null;
      // A STALE RESULT MUST NOT RESURRECT A CLOSED SESSION: somebody signed out
      // while this was in flight, and the answer is about an account that is no
      // longer here.
      if (started !== session.generation) return false;
      if (!granted) {
        // Revoked, expired, rotated out from under us, or simply absent: there
        // is nothing left to try, and pretending otherwise is how a page ends
        // up renewing forever.
        forgetRenewal();
        signOut();
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

/** Called by `signOut` through the hook below, and by a refused refresh. */
export function forgetRenewal(): void {
  refreshing = null;
  sessionDrop(REFRESH_KEY);
  sessionDrop(EXPIRY_KEY);
}

// --- Signing in ---------------------------------------------------------------

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
    // `offline_access` IS WHAT ASKS FOR A REFRESH TOKEN, and it is the whole
    // fix: without it Rauthy issues an access token and nothing to renew it
    // with, so an open tab signs itself out when that token dies. PKCE is
    // untouched -- this adds a scope, it replaces no part of the flow.
    scope: "openid profile offline_access",
    state,
    code_challenge: await challengeFor(verifier),
    code_challenge_method: "S256",
  });
  location.assign(doc.authorization_endpoint + "?" + params.toString());
}

/**
 * Finish the flow with the code the issuer sent back.
 *
 * THE `state` CHECK IS AN ANTI-CSRF, NOT A DECORATION: without it, a link
 * carrying somebody else's `code` would finish the sign-in under their account.
 */
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
  // THE THREE PIECES AT ONCE: the access token to call with, the refresh token
  // to renew it, and when it dies. An issuer that grants no refresh token still
  // signs in perfectly -- the session then lasts exactly as long as it used to.
  storeGrant(granted);
  return true;
}

// REGISTERED AS SOON AS THIS MODULE EXISTS, so a plain sign-out drops the
// renewal material too. If this file is never loaded there is nothing to drop:
// no discovery ever ran, so no refresh token was ever stored.
whenSignedOut(forgetRenewal);
