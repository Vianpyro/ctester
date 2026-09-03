// Le compte : OIDC, états, pratique, vue « Mes exercices ». Chargé seulement
// si une session est en cours ou si l'étudiant demande à se connecter --
// l'anonyme, qui reste le parcours par défaut, n'en télécharge rien.
//
// SENS UNIQUE, JAMAIS DE CYCLE : `window.ctester` porte l'état partagé (le
// jeton, le catalogue, les brouillons) et les fonctions du noyau ; ce fichier
// n'est jamais importé par app.js, il s'y déclare.
(function (ctester) {
const $ = ctester.$;
const show = ctester.show;
const sessionGet = ctester.sessionGet;
const sessionSet = ctester.sessionSet;
const sessionDrop = ctester.sessionDrop;
const authCode = ctester.authCode;
const authState = ctester.authState;

// `oidc` et `token` restent au noyau : c'est lui qui lit oidc.json avant de
// savoir s'il faut ce fichier, et c'est lui qui pose l'en-tête Authorization
// d'une soumission. Ici on ne fait que les lire et les poser par le contexte.
//
// LU A CHAQUE APPEL, JAMAIS AU CHARGEMENT. `const oidc = ctester.oidc()` en
// tête de fichier était un instantané : ce module peut être évalué avant que
// `oidc.json` soit revenu -- ou n'être jamais revenu du tout, un bloqueur de
// publicité suffit -- et la config restait `null` pour toute la visite. Le
// bouton de connexion levait alors « reading 'issuer' of null », dans une
// promesse que personne ne lisait.
function config() {
  const c = ctester.oidc();
  if (!c || !c.issuer || !c.client_id) {
    throw new Error("la configuration de connexion n'est pas disponible");
  }
  return c;
}
let states = {};
let practice = {};

const authFetch = (url, options) => fetch(url, Object.assign({}, options, {
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

async function putJson(path, payload) {
  if (!ctester.token()) return false;
  try {
    const answer = await authFetch(path, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (answer.status === 401) { signOut(); return false; }
    return answer.ok;
  } catch (e) {
    return false;
  }
}

async function syncDraft(exerciseId, files) {
  const ok = await putJson("brouillon", { tp: exerciseId, files });
  if (!ok && exerciseId === ctester.exerciceOuvert()) {
    ctester.showDraftStatus("brouillon gardé sur cet ordinateur, pas sur ton compte");
  }
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
    show("bad", "La connexion a échoué. Tu peux continuer sans compte.");
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
  ctester.setToken(null);
  // La projection privée part avec la session : la laisser à l'écran
  // montrerait les progrès de quelqu'un qui vient de se déconnecter.
  if (ctester.progres) ctester.progres.oublier();
  showListView(false);
}

async function loadStates() {
  const answer = await getJson("etats");
  states = {};
  if (!answer || !Array.isArray(answer.etats)) return;
  for (const row of answer.etats) {
    if (row && typeof row.exercice_id === "string") {
      states[row.exercice_id] = row.statut;
    }
  }
}

async function loadPractice() {
  const answer = await getJson("pratique");
  practice = {};
  if (!answer || !Array.isArray(answer.pratique)) return;
  for (const row of answer.pratique) {
    if (row && typeof row.exercice_id === "string"
        && Number.isInteger(row.tentatives) && Number.isInteger(row.reussites)) {
      practice[row.exercice_id] = row;
    }
  }
}

const STATE_LABELS = { valide: "validé", essaye: "essayé" };

function buildList() {
  const box = $("liste");
  box.innerHTML = "";
  box.append(progression());
  for (const tp of ctester.catalogue()) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "ligne";
    const group = document.createElement("span");
    group.className = "tpname";
    group.textContent = tp.group;
    const title = document.createElement("span");
    title.className = "titre";
    title.textContent = tp.short || tp.label;
    const dot = document.createElement("span");
    const stats = practice[tp.id];
    const statut = states[tp.id] || "";
    dot.className = "puce " + (stats && stats.reussites ? "valide" : statut);
    dot.textContent = stats
      ? stats.tentatives + " tentative" + (stats.tentatives > 1 ? "s" : "")
        + (stats.reussites ? " — réussie" + (stats.reussites > 1 ? "s" : "") : "")
      : STATE_LABELS[statut] || "à faire";
    row.append(group, title, dot);
    row.addEventListener("click", () => {
      $("tp").value = tp.group;
      ctester.fillExercises(tp.id);
      showListView(false);
    });
    box.append(row);
  }
}

function progression() {
  const tps = ctester.catalogue();
  const total = tps.length;
  const faits = tps.filter(t => states[t.id] === "valide").length;
  const bloc = document.createElement("div");
  bloc.id = "progres";
  const compte = document.createElement("div");
  compte.className = "compte";
  compte.innerHTML = "";
  const fort = document.createElement("b");
  fort.textContent = faits + " / " + total;
  compte.append(fort, document.createTextNode(" exercices validés"));
  const jauge = document.createElement("div");
  jauge.className = "jauge";
  const rempli = document.createElement("i");
  rempli.setAttribute("style",
    "width:" + (total ? Math.round(faits / total * 100) : 0) + "%");
  jauge.append(rempli);
  bloc.append(compte, jauge);
  return bloc;
}

function showListView(on) {
  if (on) buildList();
  // C'est le noyau qui décide quelle vue est à l'écran : « Mes progrès »
  // occupe la même place, et deux modules qui se masquent l'un l'autre chacun
  // de son côté finissent par en laisser deux moitiés.
  ctester.afficherVue(on ? "liste" : "");
  if (on) $("quizwrap").hidden = true;
  if (!on && ctester.catalogue().length) ctester.switchMode();
}

async function oublier() {
  if (!ctester.token()) return;
  let ok = false;
  try {
    ok = (await authFetch("moi", { method: "DELETE" })).ok;
  } catch (e) {
    ok = false;
  }
  // SE DECONNECTER D'ABORD, ANNONCER ENSUITE. `signOut` repasse par la vue
  // exercice, qui réécrit `#out` avec son message d'attente : annoncée avant,
  // la confirmation de suppression était effacée dans la milliseconde et
  // l'étudiant ne voyait jamais que sa demande avait abouti.
  if (ok) signOut();
  show(ok ? "ok" : "bad",
       ok ? "Tes données ont été supprimées du serveur."
          : "Suppression impossible pour l'instant : réessaie plus tard.");
}

// Le noyau a deja lu oidc.json et repere une session (ou un retour de
// connexion) : il ne charge ce fichier que dans ce cas, et lui passe la main.
async function demarrer() {
  if (authCode) await finishSignIn();
  ctester.refreshAccount();
  if (!ctester.token()) return;
  await loadStates();
  await loadPractice();
  ctester.switchMode();
}

ctester.compte = {
  demarrer: demarrer,
  startSignIn: startSignIn,
  signOut: signOut,
  getJson: getJson,
  syncDraft: syncDraft,
  loadStates: loadStates,
  loadPractice: loadPractice,
  oublier: oublier,
  basculerListe: () => showListView($("liste").hidden),
};
})(window.ctester);
