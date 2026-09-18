// OIDC login for a page without a build: a port of frontend/src/lib/auth/oidc.ts,
// reduced to what the dashboard needs. The constraints commented there apply here too.

const TOKEN_KEY = "ctester-admin-token";
const REFRESH_KEY = "ctester-admin-refresh";
const EXPIRY_KEY = "ctester-admin-expiry";
const PKCE_KEY = "ctester-admin-pkce";

// Rauthy only accepts a refresh token in the access token's last minute, and using
// it earlier revokes every session. 30 s stays inside that window.
const REFRESH_MARGIN = 30;

let token = null;
let settings = null;
let cachedDiscovery = null;
let inProgress = null;        // one refresh at a time: rotation would invalidate the others

const seconds = () => Math.floor(Date.now() / 1000);

function read(key) {
  try {
    return localStorage.getItem(key) || "";
  } catch {
    return "";
  }
}

function write(key, value) {
  try {
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {
    /* private browsing: the session lives as long as the tab */
  }
}

async function config() {
  if (!settings) {
    const response = await fetch("/api/oidc");
    settings = await response.json();
    if (!settings.issuer || !settings.client_id) {
      throw new Error("la connexion n'est pas configuree sur ce deploiement");
    }
  }
  return settings;
}

async function discovery() {
  if (!cachedDiscovery) {
    const { issuer } = await config();
    const response = await fetch(issuer + "/.well-known/openid-configuration");
    cachedDiscovery = await response.json();
  }
  return cachedDiscovery;
}

const base64url = (bytes) =>
  btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");

const random = () => base64url(crypto.getRandomValues(new Uint8Array(32)));

// crypto.subtle only exists in a secure context: without HTTPS, login is impossible,
// not merely degraded.
async function challengeFor(verifier) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64url(new Uint8Array(digest));
}

// The URI registered in Rauthy must be exactly this one.
const redirection = () => location.origin + location.pathname;

function keep(grant) {
  token = grant.access_token || null;
  write(TOKEN_KEY, token || "");
  write(REFRESH_KEY, grant.refresh_token || "");
  write(EXPIRY_KEY, grant.expires_in
    ? String(seconds() + Number(grant.expires_in))
    : "");
}

export function forget() {
  token = null;
  inProgress = null;
  write(TOKEN_KEY, "");
  write(REFRESH_KEY, "");
  write(EXPIRY_KEY, "");
}

function expiresSoon() {
  const end = Number(read(EXPIRY_KEY)) || 0;
  // Without a known expiry the token is kept: a 401 will trigger the renewal,
  // whereas a premature renewal would get the session revoked.
  return end > 0 && seconds() >= end - REFRESH_MARGIN;
}

async function exchange(form) {
  const doc = await discovery();
  const response = await fetch(doc.token_endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(form).toString(),
  });
  if (!response.ok) return null;
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function renewToken() {
  if (inProgress) return inProgress;
  const refreshToken = read(REFRESH_KEY);
  if (!refreshToken) return Promise.resolve(false);
  inProgress = config()
    .then(({ client_id }) => exchange({
      grant_type: "refresh_token",
      refresh_token: refreshToken,
      client_id,
    }))
    .then((grant) => {
      inProgress = null;
      if (!grant || !grant.access_token) {
        forget();
        return false;
      }
      keep(grant);
      return true;
    }, () => {
      inProgress = null;
      return false;
    });
  return inProgress;
}

/** The token to send, renewed if needed; null when a new login is needed. */
export async function validToken() {
  // Reread from storage after a reload: otherwise every page load would renew,
  // well before the window Rauthy allows.
  if (!token) token = read(TOKEN_KEY) || null;
  if (token && !expiresSoon()) return token;
  return (await renewToken()) ? token : null;
}

export async function connect() {
  const doc = await discovery();
  const { client_id } = await config();
  const verifier = random();
  const state = random();
  try {
    sessionStorage.setItem(PKCE_KEY, JSON.stringify({ verifier, state }));
  } catch {
    throw new Error("le stockage de session est indisponible");
  }
  const params = new URLSearchParams({
    response_type: "code",
    client_id,
    redirect_uri: redirection(),
    scope: "openid profile offline_access",
    state: state,
    code_challenge: await challengeFor(verifier),
    code_challenge_method: "S256",
  });
  location.assign(doc.authorization_endpoint + "?" + params.toString());
}

async function finish(code, state) {
  let saved = null;
  try {
    saved = JSON.parse(sessionStorage.getItem(PKCE_KEY) || "null");
    sessionStorage.removeItem(PKCE_KEY);
  } catch {
    saved = null;
  }
  // Without this check, a link carrying someone else's code would log in as them.
  if (!saved || !saved.state || saved.state !== state) return false;
  const { client_id } = await config();
  const grant = await exchange({
    grant_type: "authorization_code",
    code,
    client_id,
    redirect_uri: redirection(),
    code_verifier: saved.verifier || "",
  });
  if (!grant || !grant.access_token) return false;
  keep(grant);
  return true;
}

/**
 * The return from Rauthy if any, then a usable token or null.
 * The code is removed from the URL: a reload must not replay it.
 */
export async function start() {
  const params = new URLSearchParams(location.search);
  const code = params.get("code");
  const state = params.get("state");
  if (code && state) {
    const opened = await finish(code, state);
    history.replaceState(null, "", location.pathname);
    if (opened) return token;
  }
  return validToken();
}
