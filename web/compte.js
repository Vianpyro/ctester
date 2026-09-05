// Le compte : OIDC, états, pratique, vue « Mes exercices ». Chargé seulement
// si une session est en cours ou si l'étudiant demande à se connecter --
// l'anonyme, qui reste le parcours par défaut, n'en télécharge rien.
//
// SENS UNIQUE, JAMAIS DE CYCLE : `window.ctester` porte l'état partagé (le
// jeton, le catalogue, les brouillons) et les fonctions du noyau ; ce fichier
// n'est jamais importé par app.js, il s'y déclare.
(function (ctester) {
const $ = ctester.$;
const systeme = ctester.systeme;
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

// LE SEUL POINT DE PASSAGE des appels authentifies, donc le seul endroit ou
// `API()` a besoin d'etre pose : etats, pratique, brouillon, preferences,
// progres et forum passent tous par ici. Les DEUX autres `fetch` de ce
// fichier -- la decouverte OIDC et le token endpoint -- portent des URL
// absolues venues de l'emetteur : les prefixer les enverrait sur l'API.
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

// UNE ÉCRITURE AUTHENTIFIÉE, ET SON CORPS D'ERREUR. Le forum a besoin du
// message que l'API renvoie -- « message trop long », « trop de messages d'un
// coup » -- et pas seulement d'un booléen : afficher « ça n'a pas marché » sur
// une règle qu'on peut respecter est la façon la plus sûre de faire recommencer
// quelqu'un à l'identique.
//
// Rend null quand il n'y a pas de session ou que le réseau a lâché, sinon
// {ok, status, corps}. `corps` peut être null : une page de blocage Cloudflare
// ou une erreur nginx en HTML n'est pas du JSON.
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
  const reponse = await sendJson(path, "PUT", payload);
  return !!(reponse && reponse.ok);
}

// --- LE THÈME SUIT LE COMPTE, PAS L'APPAREIL -------------------------------
// Le stockage local garde le thème de CE navigateur ; le serveur garde celui du
// compte. Au démarrage d'une session, c'est le compte qui a le dernier mot : un
// étudiant qui passe du labo à son portable doit retrouver son écran, pas le
// défaut de la machine où il vient de s'asseoir.
//
// SEULEMENT S'IL A DÉJÀ CHOISI. Un thème vide veut dire « aucun choix
// enregistré » (et une lecture ratée rend `null`) : dans les deux cas on garde
// ce que l'appareil affiche déjà, et on lui envoie ce choix pour que le compte
// en ait un. Écraser par un défaut à la première panne ferait clignoter la page
// de quelqu'un chaque fois que Postgres tousse.
async function chargerTheme() {
  const prefs = await getJson("preferences");
  if (!prefs) return;                       // base muette : l'appareil décide
  if (!prefs.theme) {                       // premier compte, aucun choix
    await enregistrerTheme(ctester.themeCourant());
    return;
  }
  ctester.appliquerTheme(prefs.theme);
  // Recopié localement pour que la PROCHAINE visite parte du bon thème avant
  // le premier rendu : le serveur, lui, répond toujours après la peinture.
  ctester.retenirTheme(prefs.theme);
}

// Appelé par le bouton du noyau, sans être attendu. Silencieux à dessein : le
// thème est déjà à l'écran et gardé sur cet appareil, et annoncer une panne de
// synchronisation par-dessus un verdict de compilation coûterait plus qu'elle.
async function enregistrerTheme(nom) {
  await putJson("preferences", { theme: nom });
}

// LE SUCCÈS SE DIT AUSSI, PAS SEULEMENT L'ÉCHEC. « Sur ton compte » est la
// seule chose qui réponde à « est-ce que je retrouve mon code chez moi ? », et
// c'est la question que l'étudiant du labo se pose en partant. Avant, seul
// l'échec parlait : le cas qui marche restait muet sur ce qu'il avait garanti.
async function syncDraft(exerciseId, files) {
  const ok = await putJson("brouillon", { exercise_id: exerciseId, files });
  // L'EXERCICE A PU CHANGER PENDANT L'ALLER-RETOUR : n'annoncer que sur celui
  // qui est encore à l'écran, sinon l'indicateur parle d'un autre fichier.
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
  // LES MARQUES PARTENT AVEC LA SESSION : laisser les coches « validé » dans le
  // menu et la bande montrerait les progrès de quelqu'un qui vient de partir.
  ctester.poserStatuts({});
  ctester.setToken(null);
  // La projection privée part avec la session : la laisser à l'écran
  // montrerait les progrès de quelqu'un qui vient de se déconnecter.
  if (ctester.progres) ctester.progres.oublier();
  // Le fil part avec la session pour la même raison : il n'est lisible que
  // connecté, et le laisser à l'écran montrerait des messages à quelqu'un que
  // le serveur ne reconnaît plus.
  if (ctester.forum) ctester.forum.oublier();
}

async function loadStates() {
  const answer = await getJson("etats");
  states = {};
  if (answer && Array.isArray(answer.etats)) {
    for (const row of answer.etats) {
      if (row && typeof row.exercice_id === "string") {
        states[row.exercice_id] = row.statut;
      }
    }
  }
  // POUSSÉ AU NOYAU, jamais tiré par lui : le menu du catalogue et la bande du
  // laboratoire montrent le statut, et ils vivent dans app.js. Une panne de
  // lecture rend une carte VIDE, pas un statut faux -- « à faire » sur un
  // exercice réussi vaut mieux que l'inverse.
  ctester.poserStatuts(states);
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
  systeme(ok ? "Tes données ont été supprimées du serveur."
             : "Suppression impossible pour l'instant : réessaie plus tard.", !ok);
}

// Le noyau a deja lu oidc.json et repere une session (ou un retour de
// connexion) : il ne charge ce fichier que dans ce cas, et lui passe la main.
async function demarrer() {
  if (authCode) await finishSignIn();
  ctester.refreshAccount();
  if (!ctester.token()) return;
  // AVANT les projections : c'est l'écran qu'on répare, et il doit l'être le
  // plus tôt possible dans la session.
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
  // LES DONNÉES, PAS LEUR RENDU. La liste des exercices vit désormais dans
  // « Mes progrès » : deux destinations répondaient à « où j'en suis », avec
  // deux comptes différents des mêmes exercices.
  etats: () => states,
  pratique: () => practice,
  chargerTheme: chargerTheme,
  enregistrerTheme: enregistrerTheme,
  oublier: oublier,
};
})(window.ctester);
