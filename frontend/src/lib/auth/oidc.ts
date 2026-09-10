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

import { dropCredentials, session, signOut, whenSignedOut } from "./session.svelte";
import { localGet, localSet, sessionGet, sessionSet, sessionDrop } from "../storage";
import {
  DEADLINE_KEY,
  EXPIRY_KEY,
  PKCE_KEY,
  REFRESH_KEY,
  RETURN_KEY,
  SESSION_MAX_DAYS,
} from "./keys";

/**
 * Renewed this many seconds BEFORE the access token dies, not after a request
 * has already failed.
 *
 * THIRTY, AND IT MUST STAY STRICTLY BETWEEN 0 AND 60. This is not a comfort
 * setting, it is a collision that had to be moved off. Rauthy stamps every
 * refresh token with `nbf = access_token_lifetime - 60` (`token_set.rs`), so
 * the window in which a refresh token may be used is exactly the LAST MINUTE
 * of the access token's life. A margin of 60 -- what this was -- fires at the
 * very first instant of that window, on its edge, with nothing to spare.
 *
 * AND BEING EARLY IS NOT A FAILED REQUEST. Rauthy's own words: using a refresh
 * token before its `nbf` "will result in invalidation of not only the token
 * itself, but also all other linked sessions and tokens for this user". One
 * early refresh signs the student out of everything -- which is exactly the
 * symptom this whole file exists to remove.
 *
 * A CONSTANT CLOCK OFFSET CANCELS OUT, which is why this was survivable at 60:
 * the expiry is stamped from the browser's own clock when the grant arrives, so
 * the page measures a DURATION, and it lands one network round trip AFTER
 * `nbf`. What does not cancel is the clock MOVING during those hours -- an NTP
 * correction, a laptop resumed, a machine whose time was simply wrong until it
 * was not. Thirty seconds puts us in the middle of the window instead of on its
 * lip, so a jump has to be larger than that to do any damage.
 *
 * The reactive path (a 401, then one renewal) is never affected: it runs after
 * the access token has already expired, therefore always after `nbf`.
 */
export const REFRESH_MARGIN = 30;

/**
 * The offset Rauthy stamps into a refresh token's `nbf`, in seconds. Not ours
 * to choose -- it is `access_token_lifetime - 60` in `token_set.rs` -- and it
 * is written down here so the test that pins `REFRESH_MARGIN` inside it names
 * the number it is defending against.
 */
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
const storedRefreshToken = () => localGet(REFRESH_KEY);
const expiresAt = () => Number(localGet(EXPIRY_KEY)) || 0;
/** 0 means "no deadline recorded" -- a session from before this existed. */
const deadline = () => Number(localGet(DEADLINE_KEY)) || 0;

/**
 * THE DEADLINE SLIDES, IT IS NOT A COUNTDOWN FROM THE FIRST SIGN-IN. A student
 * who works every week must never be signed out; one who stops must eventually
 * be. So each successful grant pushes it back to `SESSION_MAX_DAYS` from now,
 * which is exactly what Rauthy's rotating refresh token does on its side -- the
 * two clocks agree by construction rather than by being watched.
 */
function pushDeadline(): void {
  localSet(DEADLINE_KEY, String(seconds() + SESSION_MAX_DAYS * 86400));
}

/** Past its deadline: unused for too long, and no longer renewable. */
const abandoned = (): boolean => {
  const until = deadline();
  return until > 0 && seconds() >= until;
};

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
    localSet(REFRESH_KEY, granted.refresh_token);
  }
  const life = Number(granted.expires_in);
  localSet(EXPIRY_KEY, String(Number.isFinite(life) && life > 0 ? seconds() + life : 0));
  // THE SESSION IS ALIVE, SO ITS DEADLINE MOVES. This is the line that makes a
  // weekly lab a session that never asks for a password again.
  pushDeadline();
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
  // ABANDONED FOR TOO LONG: this is the deadline doing what the closing tab
  // used to do. Asking the issuer would be asking it to refuse -- its own
  // refresh token expires on the same schedule -- so we end the session here
  // and say so, rather than turning it into a failed request.
  if (abandoned()) {
    dropCredentials();
    signOut();
    return Promise.resolve(false);
  }
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
  dropCredentials();
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
    // `offline_access` IS THE STANDARD WAY TO ASK FOR A REFRESH TOKEN, AND
    // RAUTHY IGNORES IT. This comment used to claim it was "the whole fix";
    // it is not, and believing that cost a round of debugging. Rauthy has no
    // `offline_access` handling at all -- `Client::allow_refresh_token()` is
    // exactly `is_flow_enabled(GrantType::RefreshToken)` -- so what decides
    // whether a refresh token comes back is the `refresh_token` flow being
    // ticked on the client, in the Admin UI, and nothing here.
    //
    // IT IS KEPT ANYWAY, and not out of superstition: it is what the spec says
    // to send, Rauthy drops unknown scopes silently rather than refusing the
    // request (`sanitize_login_scopes`), and an issuer that is not Rauthy would
    // need it. PKCE is untouched -- this is a scope, it replaces no part of the
    // flow.
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
