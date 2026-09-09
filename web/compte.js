// The account: OIDC, states, practice, theme. Only loaded if a session is
// in progress or the student asks to sign in -- the anonymous visitor, who
// remains the default path, downloads none of it.
//
// ONE WAY, NEVER A CYCLE: `window.ctester` carries the shared state (the
// token, the catalog, the drafts) and the core's functions; this file is
// never imported by app.js, it registers itself into it.
(function (ctester) {
const $ = ctester.$;
const systeme = ctester.systeme;
const sessionGet = ctester.sessionGet;
const sessionSet = ctester.sessionSet;
const sessionDrop = ctester.sessionDrop;
const authCode = ctester.authCode;
const authState = ctester.authState;

// `oidc` and `token` stay in the core: it is the one that reads oidc.json
// before knowing whether this file is even needed, and it is the one that
// sets a submission's Authorization header. Here we only read them and set
// them through the shared context.
//
// READ ON EVERY CALL, NEVER AT LOAD TIME. `const oidc = ctester.oidc()` at
// the top of the file used to be a snapshot: this module can be evaluated
// before `oidc.json` has come back -- or never comes back at all, an ad
// blocker is enough -- and the config would stay `null` for the whole visit.
// The sign-in button would then throw "reading 'issuer' of null", inside a
// promise nobody read.
function config() {
  const c = ctester.oidc();
  if (!c || !c.issuer || !c.client_id) {
    throw new Error("la configuration de connexion n'est pas disponible");
  }
  return c;
}
let states = {};
let practice = {};

// --- THE OIDC LIFECYCLE, AND IT LIVES ONLY HERE --------------------------
//
// THE ACCESS TOKEN IS NOT A SESSION. It is short-lived (Rauthy hands out
// minutes, not hours), and a tab left open through a lecture used to come
// back signed out -- the student lost their thread, their draft indicator and
// their team room for no reason they could see. The refresh token is what
// keeps the session alive without sending anyone back to Rauthy.
//
// THREE THINGS ARE STORED, ALL IN `sessionStorage` LIKE THE ACCESS TOKEN
// ALREADY WAS: they die with the tab, which is the whole point on a shared
// lab machine. `localStorage` would hand the next student a working session.
//
// THE REFRESH TOKEN NEVER LEAVES THIS MODULE. It goes to exactly one place,
// the issuer's token endpoint; it is not in `ctester.token()`, not in a
// header to our API, not in a WebSocket frame. `ctester.token()` means the
// ACCESS token, and nothing else.
const REFRESH_KEY = "ctester.refresh";
const EXPIRY_KEY = "ctester.expire";
// Refreshed a minute BEFORE it dies, rather than after a request has already
// failed: a 401 costs a round trip and, on a WebSocket, a whole reconnection.
const REFRESH_MARGIN = 60;

// The single in-flight refresh. Five calls discovering the expiry at the same
// moment must produce ONE request to Rauthy: with rotation on, the other four
// would each burn the refresh token the first one is using, and whichever
// lost the race would sign the student out.
let refreshing = null;
// BUMPED BY `signOut`. A refresh started before the sign-out lands after it,
// and storing its grant would silently sign the account back in -- on a lab
// machine, for whoever sits down next. The generation is what makes that
// result droppable.
let generation = 0;

const refreshTokenStored = () => sessionGet(REFRESH_KEY);
const expiresAt = () => Number(sessionGet(EXPIRY_KEY)) || 0;
const seconds = () => Math.floor(Date.now() / 1000);

// AN UNKNOWN LIFETIME IS NOT AN EXPIRED ONE. A provider that omits
// `expires_in` leaves us with 0, and refreshing on every single request would
// turn one student's page into a load generator aimed at the issuer. We then
// wait for the 401, which is exactly the old behaviour.
const nearlyExpired = () => {
  const at = expiresAt();
  return at > 0 && seconds() >= at - REFRESH_MARGIN;
};

// WHAT THE TOKEN ENDPOINT GAVE US, WRITTEN DOWN. Both grant types come
// through here, so rotation and expiry can only be handled one way.
function storeGrant(granted) {
  // ROTATION: Rauthy may hand back a NEW refresh token and kill the old one
  // on the spot. Keeping the old one would work exactly once and then sign
  // the student out an hour later, with nothing on screen to explain it.
  // Absent means "keep using the one you have" -- not "forget it".
  if (typeof granted.refresh_token === "string" && granted.refresh_token) {
    sessionSet(REFRESH_KEY, granted.refresh_token);
  }
  const life = Number(granted.expires_in);
  sessionSet(EXPIRY_KEY,
             String(Number.isFinite(life) && life > 0 ? seconds() + life : 0));
  // LAST, AND ON PURPOSE: `setToken` redraws the banner, and it must never
  // announce a session whose refresh material is only half written down.
  setToken(granted.access_token);
}

async function askForRefresh(carried) {
  let granted = null;
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
    granted = answer.ok ? await answer.json() : null;
  } catch (e) {
    granted = null;                 // network, CSP, provider down: all the same
  }
  return granted && typeof granted.access_token === "string" ? granted : null;
}

// ONE REFRESH AT A TIME, AND ONE ONLY. Returns true when the access token
// that follows is usable.
function refreshAccessToken() {
  if (refreshing) return refreshing;
  // NOTHING TO RENEW WITH IS NOT A REFUSAL, and it must not sign anyone out:
  // an issuer that declined `offline_access`, or a session opened before this
  // existed. The page then behaves exactly as it did before -- the access
  // token lives out its life, and the 401 that follows ends the session, as
  // it always has.
  const carried = refreshTokenStored();
  if (!carried) return Promise.resolve(false);
  const started = generation;
  refreshing = askForRefresh(carried).then((granted) => {
    refreshing = null;
    // A STALE RESULT MUST NOT RESURRECT A CLOSED SESSION. Someone signed out
    // while this was in flight; the answer is now about an account that is no
    // longer here.
    if (started !== generation) return false;
    if (!granted) {
      // Revoked, expired, rotated out from under us, or simply absent: there
      // is nothing left to try, and pretending otherwise is how a page ends
      // up refreshing forever.
      signOut();
      return false;
    }
    storeGrant(granted);
    return true;
  }, () => {
    refreshing = null;
    return false;
  });
  return refreshing;
}

// CALLED BEFORE ANYTHING THAT CARRIES THE TOKEN -- a request, a WebSocket.
// True when the access token can be used; false means "send it anyway and let
// the 401 decide", which is the honest answer when we have no way to renew.
async function ensureValidAccessToken() {
  if (!ctester.token()) return false;
  if (!nearlyExpired()) return true;
  return await refreshAccessToken();
}

const withToken = (url, options) => fetch(API(url), Object.assign({}, options, {
  headers: Object.assign({}, (options && options.headers) || {},
                         { Authorization: "Bearer " + ctester.token() }),
}));

// THE ONLY PASSAGE POINT for authenticated calls, so the only place `API()`
// needs to be set: states, practice, draft, preferences, progress and forum
// all go through here. This file's THREE OTHER `fetch` calls -- OIDC
// discovery, the code exchange and the refresh -- carry absolute URLs coming
// from the issuer: prefixing them would send them to the API instead.
//
// ONE REFRESH, ONE RETRY, THEN OUT. A second 401 on a token minted seconds
// earlier is not a timing problem, and retrying it again would only produce a
// page that spins instead of one that says to sign in again.
async function authFetch(url, options) {
  await ensureValidAccessToken();
  // THE SESSION CLOSED WHILE WE WERE RENEWING IT. Sending `Bearer null` would
  // only be asking the API to say 401 on our behalf.
  if (!ctester.token()) return new Response(null, { status: 401 });
  const answer = await withToken(url, options);
  if (answer.status !== 401) return answer;
  if (!await refreshAccessToken()) {
    signOut();                      // no refresh material, or it was refused
    return answer;
  }
  const second = await withToken(url, options);
  if (second.status === 401) signOut();
  return second;
}

async function getJson(path) {
  if (!ctester.token()) return null;
  try {
    const answer = await authFetch(path);
    if (answer.status === 401) { signOut(); return null; }
    return answer.ok ? await answer.json() : null;
  } catch (e) {
    return null;
  }
}

// AN AUTHENTICATED WRITE, AND ITS ERROR BODY. The forum needs the message
// the API returns -- "message trop long", "trop de messages d'un coup" --
// not just a boolean: showing "that didn't work" over a rule one can
// actually follow is the surest way to make someone try the exact same
// thing again.
//
// Returns null when there is no session or the network dropped, otherwise
// {ok, status, corps}. `corps` can be null: a Cloudflare block page or an
// nginx error in HTML is not JSON.
async function sendJson(path, method, payload) {
  if (!ctester.token()) return null;
  try {
    const answer = await authFetch(path, {
      method: method,
      headers: payload === undefined ? {} : { "Content-Type": "application/json" },
      body: payload === undefined ? undefined : JSON.stringify(payload),
    });
    if (answer.status === 401) { signOut(); return null; }
    let corps = null;
    try { corps = await answer.json(); } catch (e) { corps = null; }
    return { ok: answer.ok, status: answer.status, corps: corps };
  } catch (e) {
    return null;
  }
}

async function putJson(path, payload) {
  const response = await sendJson(path, "PUT", payload);
  return !!(response && response.ok);
}

// --- THE THEME FOLLOWS THE ACCOUNT, NOT THE DEVICE --------------------------
// Local storage keeps THIS browser's theme; the server keeps the account's.
// At the start of a session, the account has the last word: a student
// moving from the lab to their laptop must find their own screen again, not
// the default of the machine they just sat down at.
//
// ONLY IF ONE WAS ALREADY CHOSEN. An empty theme means "no choice recorded"
// (and a failed read returns `null`): in both cases we keep what the device
// already shows, and send that choice back so the account has one. Falling
// back to a default at the first outage would flash someone's page every
// time Postgres coughs.
async function chargerTheme() {
  const prefs = await getJson("preferences");
  if (!prefs) return;                       // mute database: the device decides
  if (!prefs.theme) {                       // fresh account, no choice yet
    await enregistrerTheme(ctester.themeCourant());
    return;
  }
  ctester.appliquerTheme(prefs.theme);
  // Copied locally so the NEXT visit starts from the right theme before the
  // first paint: the server itself always answers after the paint.
  ctester.retenirTheme(prefs.theme);
}

// Called by the core's button, without being awaited. Deliberately silent:
// the theme is already on screen and kept on this device, and announcing a
// sync failure over a compile verdict would cost more than it is worth.
async function enregistrerTheme(name) {
  await putJson("preferences", { theme: name });
}

// SUCCESS IS ALSO SAID, NOT ONLY FAILURE. "On your account" is the only
// thing that answers "will I find my code again at home?", and that is the
// question a lab student asks on their way out. Before, only failure spoke:
// the case that works stayed silent about what it had just guaranteed.
async function syncDraft(exerciseId, files) {
  const ok = await putJson("brouillon", { exercise_id: exerciseId, files });
  // THE EXERCISE MAY HAVE CHANGED DURING THE ROUND TRIP: only announce for
  // the one still on screen, or the indicator would talk about another file.
  if (exerciseId !== ctester.exerciceOuvert()) return;
  ctester.showDraftStatus(
    ok ? "enregistré sur ton compte · " + ctester.maintenant()
       : "enregistré sur cet appareil seulement — pas sur ton compte");
}

const base64url = (bytes) => btoa(String.fromCharCode(...bytes))
  .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

const randomToken = () => base64url(crypto.getRandomValues(new Uint8Array(32)));

async function challengeFor(verifier) {
  const digest = await crypto.subtle.digest(
    "SHA-256", new TextEncoder().encode(verifier));
  return base64url(new Uint8Array(digest));
}

let discovered = null;
async function discovery() {
  if (!discovered) {
    discovered = await (await fetch(
      config().issuer + "/.well-known/openid-configuration")).json();
  }
  return discovered;
}

const redirectUri = () => location.origin + location.pathname;

async function startSignIn() {
  const doc = await discovery();
  const verifier = randomToken();
  const state = randomToken();
  sessionSet("ctester.pkce", JSON.stringify({ verifier: verifier, state: state }));
  sessionSet("ctester.retour", location.search);
  const params = new URLSearchParams({
    response_type: "code",
    client_id: config().client_id,
    redirect_uri: redirectUri(),
    // `offline_access` IS WHAT ASKS FOR A REFRESH TOKEN, and it is the whole
    // fix: without it Rauthy issues an access token and nothing to renew it
    // with, so an open tab signs itself out when that token dies. PKCE is
    // untouched -- this adds a scope, it replaces no part of the flow.
    scope: "openid profile offline_access",
    state: state,
    code_challenge: await challengeFor(verifier),
    code_challenge_method: "S256",
  });
  location.assign(doc.authorization_endpoint + "?" + params.toString());
}

async function finishSignIn() {
  const saved = sessionGet("ctester.pkce");
  sessionDrop("ctester.pkce");
  sessionDrop("ctester.retour");
  let pkce = null;
  try { pkce = JSON.parse(saved); } catch (e) { pkce = null; }
  if (!pkce || !pkce.state || pkce.state !== authState) return;
  const doc = await discovery();
  const form = new URLSearchParams({
    grant_type: "authorization_code",
    code: authCode,
    client_id: config().client_id,
    redirect_uri: redirectUri(),
    code_verifier: pkce.verifier,
  });
  const answer = await fetch(doc.token_endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form.toString(),
  });
  let granted = null;
  try { granted = await answer.json(); } catch (e) { granted = null; }
  if (!answer.ok || !granted || !granted.access_token) {
    systeme("La connexion a échoué. Tu peux continuer sans compte : la page "
          + "fonctionne exactement pareil.", true);
    return;
  }
  // THE THREE PIECES AT ONCE: the access token to call with, the refresh
  // token to renew it, and when it dies. An issuer that grants no refresh
  // token still signs in perfectly -- the session then lasts exactly as long
  // as it did before.
  storeGrant(granted);
}

function setToken(value) {
  ctester.setToken(value);
}

function signOut() {
  // FIRST, AND BEFORE ANYTHING ASYNCHRONOUS. A refresh in flight is answered
  // for a generation that no longer exists, so its grant is dropped instead
  // of writing a fresh session over the one just closed.
  generation++;
  refreshing = null;
  sessionDrop(REFRESH_KEY);
  sessionDrop(EXPIRY_KEY);
  states = {};
  practice = {};
  // MARKS LEAVE WITH THE SESSION: leaving "validated" check marks in the
  // menu and the strip would show the progress of someone who just left.
  ctester.poserStatuts({});
  ctester.setToken(null);
  // The private projection leaves with the session: leaving it on screen
  // would show the progress of someone who just signed out.
  if (ctester.progres) ctester.progres.oublier();
  // The thread leaves with the session for the same reason: it is only
  // readable signed in, and leaving it on screen would show messages to
  // someone the server no longer recognizes.
  if (ctester.forum) ctester.forum.oublier();
  // AND SO DO THE TWO OTHER PRIVATE SCREENS. A ranking or a collection left
  // on screen after a sign-out shows one account's standing to whoever sits
  // down next -- the same reason the projection leaves.
  if (ctester.leaderboard) ctester.leaderboard.oublier();
  if (ctester.collection) ctester.collection.oublier();
}

async function loadStates() {
  const answer = await getJson("etats");
  states = {};
  if (answer && Array.isArray(answer.states)) {
    for (const row of answer.states) {
      if (row && typeof row.exercise_id === "string") {
        states[row.exercise_id] = row.status;
      }
    }
  }
  // PUSHED TO THE CORE, never pulled by it: the catalog menu and the lab
  // strip show the status, and they live in app.js. A read failure produces
  // an EMPTY map, not a false status -- "to do" on a solved exercise beats
  // the opposite.
  ctester.poserStatuts(states);
}

async function loadPractice() {
  const answer = await getJson("pratique");
  practice = {};
  if (!answer || !Array.isArray(answer.practice)) return;
  for (const row of answer.practice) {
    if (row && typeof row.exercise_id === "string"
        && Number.isInteger(row.attempts) && Number.isInteger(row.successes)) {
      practice[row.exercise_id] = row;
    }
  }
}

async function oublier() {
  if (!ctester.token()) return;
  let ok = false;
  try {
    ok = (await authFetch("moi", { method: "DELETE" })).ok;
  } catch (e) {
    ok = false;
  }
  // SIGN OUT FIRST, ANNOUNCE AFTER. `signOut` goes back through the exercise
  // view, which rewrites `#out` with its waiting message: announced before,
  // the deletion confirmation used to get erased within a millisecond and the
  // student never saw that their request had gone through.
  if (ok) signOut();
  systeme(ok ? "Tes données ont été supprimées du serveur."
             : "Suppression impossible pour l'instant : réessaie plus tard.", !ok);
}

// The core has already read oidc.json and spotted a session (or a sign-in
// return): it only loads this file in that case, and hands off to it.
async function demarrer() {
  if (authCode) await finishSignIn();
  ctester.refreshAccount();
  if (!ctester.token()) return;
  // A TAB REOPENED AFTER A BREAK carries a token that died in the meantime.
  // Renewing it here, once, is what keeps the four reads below from all
  // failing at the same moment and signing the student out on arrival.
  await ensureValidAccessToken();
  if (!ctester.token()) return;     // the refresh was refused: already out
  // BEFORE the projections: this is the screen being fixed, and it must
  // happen as early as possible in the session.
  await chargerTheme();
  await loadStates();
  await loadPractice();
  ctester.switchMode();
}

ctester.compte = {
  demarrer: demarrer,
  startSignIn: startSignIn,
  signOut: signOut,
  getJson: getJson,
  sendJson: sendJson,
  // THE REQUEST ITSELF, for the one caller whose answer is not JSON: the
  // hand-in ZIP. It gets the renewal, the single retry and the sign-out for
  // free -- rebuilding an `Authorization` header outside this file would be a
  // second place where an expired token is handled, or is not.
  authFetch: authFetch,
  syncDraft: syncDraft,
  loadStates: loadStates,
  loadPractice: loadPractice,
  // THE DATA, NOT ITS RENDERING: the list is drawn by `progres.js`.
  etats: () => states,
  pratique: () => practice,
  chargerTheme: chargerTheme,
  enregistrerTheme: enregistrerTheme,
  oublier: oublier,
  // THE TWO DOORS THE SOCKETS NEED, and the only ones. A WebSocket cannot
  // carry an `Authorization` header, so each module sends the token in its
  // first frame -- which means each has to know the token is still good
  // BEFORE opening, and what to do when the server says it is not. Neither
  // of these ever hands out the refresh token.
  jetonValide: ensureValidAccessToken,
  rafraichirJeton: refreshAccessToken,
};
})(window.ctester);
