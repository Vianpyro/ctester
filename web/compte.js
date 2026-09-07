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

// THE ONLY PASSAGE POINT for authenticated calls, so the only place `API()`
// needs to be set: states, practice, draft, preferences, progress and forum
// all go through here. This file's TWO OTHER `fetch` calls -- OIDC discovery
// and the token endpoint -- carry absolute URLs coming from the issuer:
// prefixing them would send them to the API instead.
const authFetch = (url, options) => fetch(API(url), Object.assign({}, options, {
  headers: Object.assign({}, (options && options.headers) || {},
                         { Authorization: "Bearer " + ctester.token() }),
}));

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
    scope: "openid profile",
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
  setToken(granted.access_token);
}

function setToken(value) {
  ctester.setToken(value);
}

function signOut() {
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
  syncDraft: syncDraft,
  loadStates: loadStates,
  loadPractice: loadPractice,
  // THE DATA, NOT ITS RENDERING: the list is drawn by `progres.js`.
  etats: () => states,
  pratique: () => practice,
  chargerTheme: chargerTheme,
  enregistrerTheme: enregistrerTheme,
  oublier: oublier,
};
})(window.ctester);
