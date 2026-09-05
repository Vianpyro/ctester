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

async function syncDraft(exerciseId, files) {
  const ok = await putJson("brouillon", { exercise_id: exerciseId, files });
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
  // Le fil part avec la session pour la même raison : il n'est lisible que
  // connecté, et le laisser à l'écran montrerait des messages à quelqu'un que
  // le serveur ne reconnaît plus.
  if (ctester.forum) ctester.forum.oublier();
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

// L'EXPORT D'UN TP, DEPUIS LA LISTE. Le même bouton que dans la barre
// d'actions, mais offert par laboratoire : c'est ici qu'on est quand on pense
// « remise » plutôt que « exercice courant ». `exporter.js` ne descend qu'au
// clic, comme partout, et la règle de qui a droit à un bouton reste au noyau.
//
// SON PROPRE ÉTAT, À CÔTÉ DE LUI. `#brouillon`, où le bouton de la barre écrit,
// n'est pas à l'écran depuis cette vue : y annoncer « main.c exporté » ne
// dirait rien à personne.
function ligneExport(groupe) {
  const bloc = document.createElement("div");
  bloc.className = "exportligne";
  const bouton = document.createElement("button");
  bouton.type = "button";
  bouton.className = "nav";
  bouton.textContent = "Exporter le " + groupe + " en main.c";
  const etat = document.createElement("span");
  etat.className = "exportetat";
  etat.setAttribute("aria-live", "polite");
  const annoncer = (texte, rate) => {
    etat.textContent = texte;
    etat.className = rate ? "exportetat rate" : "exportetat";
  };
  bouton.addEventListener("click", async () => {
    // `activerModule` dit déjà ce qui n'est pas arrivé -- mais il le dit dans
    // `#out`, qui appartient à la vue exercice et n'est pas affiché ici. On le
    // redit sur place, sinon le bouton reste inerte sans un mot.
    if (!await ctester.activerModule("exporter", "l'export du TP")) {
      annoncer("l'export n'a pas pu être chargé — réessaie", true);
      return;
    }
    await ctester.exporter.exporter(groupe, annoncer);
  });
  bloc.append(bouton, etat);
  return bloc;
}

function buildList() {
  const box = $("liste");
  box.innerHTML = "";
  box.append(progression());
  const tps = ctester.catalogue();
  for (let rang = 0; rang < tps.length; rang++) {
    const tp = tps[rang];
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
      ctester.fillExercises(tp.id);
      showListView(false);
    });
    box.append(row);
    // LE BOUTON FERME LE GROUPE, il ne l'ouvre pas : il arrive après la
    // dernière ligne du TP, quand on vient de lire ce qui y reste à faire.
    const suivant = tps[rang + 1];
    if ((!suivant || suivant.group !== tp.group)
        && ctester.groupeExportable(tp.group)) {
      box.append(ligneExport(tp.group));
    }
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
  chargerTheme: chargerTheme,
  enregistrerTheme: enregistrerTheme,
  oublier: oublier,
  basculerListe: () => showListView($("liste").hidden),
};
})(window.ctester);
