const $ = (id) => document.getElementById(id);

// L'ÉTAT PARTAGÉ EST NOMMÉ, PAS IMPLICITE. Le quiz et le compte sont chargés à
// la demande ; ils lisent ce contexte et y déposent leurs entrées. Le sens est
// unique -- le noyau ne dépend d'aucun des deux, chacun dépend du noyau -- et
// c'est ce qui interdit le cycle. Un module ES ferait la même chose en liant
// en zone morte temporelle sur un import circulaire, la panne exacte que cette
// page a déjà connue en production.
const ctester = window.ctester = {};

const charges = {};
// Cloudflare caches static assets independently from index.html.  Keep this
// token in sync with index.html whenever app.js or a lazy module changes, so a
// deployed page cannot combine a new core with an old compte.js/quiz.js.
const ASSET_REVISION = "20260903-forum";

// ponytail: injection de <script>, pas import(). Voir ci-dessus. Passer aux
// modules ES le jour où l'état partagé est vraiment séparé.
function charger(nom) {
  if (!charges[nom]) {
    charges[nom] = new Promise((ok, ko) => {
      const balise = document.createElement("script");
      balise.onload = () => ok();
      balise.onerror = () => ko(new Error(nom));
      balise.src = nom + "?v=" + ASSET_REVISION;
      document.body.append(balise);
    }).catch((e) => {
      // ON OUBLIE L'ÉCHEC. Sans ça, une coupure réseau d'une seconde condamne
      // la fonction pour toute la visite : le second clic retomberait sur la
      // promesse rejetée sans jamais retenter.
      delete charges[nom];
      throw e;
    });
  }
  return charges[nom];
}

// `activerModule` et PAS `activer` : ce fichier a deja une fonction `activer`,
// celle qui change d'onglet dans l'editeur. Deux declarations de fonction du
// meme nom ne se signalent pas, la derniere gagne, et l'appelant recoit
// silencieusement l'autre.
async function activerModule(nom, quoi) {
  if (ctester[nom]) return true;
  try {
    await charger(nom + ".js");
  } catch (e) {
    show("bad", "Impossible de charger " + quoi + ". Vérifie ta connexion, "
              + "puis recharge la page.");
    return false;
  }
  if (!ctester[nom]) {
    // Le fichier est arrivé mais ne s'est pas déclaré : version en cache d'un
    // ancien déploiement, coupure en plein transfert. Se taire ici rendrait le
    // bouton inerte sans un mot.
    show("bad", "Impossible d'utiliser " + quoi
              + " : le fichier est arrivé incomplet. Recharge la page.");
    return false;
  }
  return true;
}

const callbackParams = new URLSearchParams(location.search);
const authCode = callbackParams.get("code");
const authState = callbackParams.get("state");
if (authCode) {
  let previousSearch = "";
  try {
    previousSearch = sessionStorage.getItem("ctester.retour") || "";
  } catch (e) {
    previousSearch = "";
  }
  history.replaceState({}, "", location.pathname + previousSearch);
}

const key = new URLSearchParams(location.search).get("k") || "";
const out = $("out");

const THEME_KEY = "ctester.theme";

function appliquerTheme(nom) {
  document.documentElement.dataset.theme = nom;
  const clair = nom === "light";
  $("theme").textContent = clair ? "☾" : "☀";
  $("theme").title = clair ? "Passer au thème sombre" : "Passer au thème clair";
  $("theme").setAttribute("aria-label", $("theme").title);
}

appliquerTheme(document.documentElement.dataset.theme === "light"
               ? "light" : "dark");

$("theme").addEventListener("click", () => {
  const suivant =
    document.documentElement.dataset.theme === "light" ? "dark" : "light";
  appliquerTheme(suivant);
  try { localStorage.setItem(THEME_KEY, suivant); } catch (e) {}
});

function show(cls, title, extra, bar) {
  out.className = cls;
  out.innerHTML = "";
  const h = document.createElement("div");
  h.className = "verdict " + cls;
  h.textContent = title;
  out.append(h);
  if (cls === "wait") out.append(indeterminee());
  if (bar) out.append(bar);
  if (extra) out.append(extra);
  if (cls === "idle") {
    out.append(aide("Choisis ton TP, puis colle ton fichier .c ou saisis tes "
                  + "réponses selon l'exercice. Les résultats ne sont pas une "
                  + "note."));
  }
  if (cls !== "wait") {
    out.append(aide("Un exercice à la fois. Les tests utilisés ici sont un "
                  + "sous-ensemble : ils t'aident à trouver tes erreurs, ils ne "
                  + "remplacent pas la correction."));
  }
}

function aide(texte) {
  const p = document.createElement("p");
  p.className = "aide";
  p.textContent = texte;
  return p;
}

function indeterminee() {
  const b = document.createElement("div");
  b.className = "barre";
  b.append(document.createElement("i"));
  return b;
}

function ticks(passed, total) {
  const bar = document.createElement("div");
  bar.className = "ticks";
  for (let n = 0; n < total; n++) {
    const t = document.createElement("i");
    if (n < passed) t.className = "on";
    t.setAttribute("style", "--i:" + Math.min(n, 12));
    bar.append(t);
  }
  return bar;
}

function list(items) {
  const ul = document.createElement("ul");
  for (const it of items) {
    const li = document.createElement("li");
    li.textContent = it.text === undefined ? it : it.text;
    if (it.cls) li.className = it.cls;
    ul.append(li);
  }
  return ul;
}

function block(text) {
  const pre = document.createElement("pre");
  pre.textContent = text;
  return pre;
}

let catalogue = [];
let oidc = null;
let token = null;

const TOKEN_KEY = "ctester.token";

function sessionGet(name) {
  try { return sessionStorage.getItem(name) || ""; } catch (e) { return ""; }
}
function sessionSet(name, value) {
  try { sessionStorage.setItem(name, value); } catch (e) {}
}
function sessionDrop(name) {
  try { sessionStorage.removeItem(name); } catch (e) {}
}

// LE JETON EST AU NOYAU parce que la soumission en a besoin, et qu'une
// soumission part bien avant que « Mes exercices » n'existe.
function setToken(value) {
  token = value || null;
  if (token) sessionSet(TOKEN_KEY, token);
  else sessionDrop(TOKEN_KEY);
  refreshAccount();
}

// Le bandeau doit savoir se dessiner AVANT que compte.js soit là : sinon le
// bouton « Se connecter » n'apparaîtrait qu'après le fichier censé n'être
// chargé que si on clique dessus.
function refreshAccount() {
  const on = !!token;
  $("connexion").hidden = !oidc || on;
  $("deconnexion").hidden = !on;
  $("oublier").hidden = !on;
  $("mesexos").hidden = !on;
  $("mesprogres").hidden = !on;
  // DEUX CONDITIONS, ET LES DEUX VIENNENT DU SERVEUR : être connecté, et un
  // déploiement qui a au moins un modérateur configuré (`oidc.forum`). Sans
  // l'une des deux le bouton n'existe pas, donc `forum.js` n'est jamais
  // demandé -- l'anonyme n'en télécharge rien, et un déploiement sans équipe
  // de modération n'ouvre pas un canal que personne ne relit.
  $("discussions").hidden = !on || !(oidc && oidc.forum);
  $("moi").hidden = !on;
  $("moi").textContent = on ? "connecté" : "";
}

// UNE SEULE VUE À LA FOIS, ET L'ARBITRAGE EST ICI. « Mes exercices » et
// « Mes progrès » vivent dans deux modules chargés séparément : si chacun
// masquait l'autre de son côté, ouvrir le second par-dessus le premier
// laisserait les deux moitiés à l'écran, ou aucune.
let vueCourante = "";

function afficherVue(nom) {   // "" (l'exercice) | "liste" | "progres" | "forum"
  vueCourante = nom;
  $("liste").hidden = nom !== "liste";
  $("vueprogres").hidden = nom !== "progres";
  $("vueforum").hidden = nom !== "forum";
  $("travail").hidden = nom !== "";
  $("mesexos").textContent =
    nom === "liste" ? "Retour à l'exercice" : "Mes exercices";
  $("mesprogres").textContent =
    nom === "progres" ? "Retour à l'exercice" : "Mes progrès";
  $("discussions").textContent =
    nom === "forum" ? "Retour à l'exercice" : "Discussions";
}

const current = () => catalogue.find(t => t.id === $("ex").value) || null;

const SKILL_LABELS = {
  "number-systems": "systèmes de nombres", "binary-hexadecimal": "binaire et hexadécimal",
  "compilation": "compilation", "main": "main()", "libraries": "bibliothèques",
  "printf": "printf", "scanf": "scanf", "variables": "variables", "types": "types",
  "arithmetic-operators": "opérateurs", "boolean-logic": "logique booléenne",
  "bitwise-operations": "opérations binaires", "conditions": "conditions",
  "switch": "switch", "while": "boucles while", "do-while": "boucles do/while", "for": "boucles for",
  "functions": "fonctions", "parameters": "paramètres", "return-values": "retours",
  "pointers": "pointeurs", "arrays-1d": "tableaux", "arrays-2d": "tableaux 2D",
  "strings": "chaînes", "algorithm-design": "algorithmes", "complexity": "complexité",
};
const CONTEXT_LABELS = {
  mechanical: "mécanique", electrical: "électrique",
  "automated-production": "production automatisée", aerospace: "aérospatial",
  logistics: "logistique", computing: "informatique", "general-engineering": "ingénierie",
};
const DIFFICULTY_LABELS = {
  intro: "découverte", foundation: "fondations", intermediate: "intermédiaire",
  advanced: "avancé",
};

function addOption(sel, value, text) {
  const o = document.createElement("option");
  o.value = value;
  o.textContent = text;
  sel.append(o);
}

fetch("tps.json").then(r => r.json()).then(tps => {
  catalogue = tps;
  if (!tps.length) { show("bad", "Aucun TP n'est publié pour l'instant."); return; }
  for (const g of [...new Set(tps.map(t => t.group))]) addOption($("tp"), g, g);
  const wanted = catalogue.find(
    t => t.id === new URLSearchParams(location.search).get("tp"));
  if (wanted) $("tp").value = wanted.group;
  fillExercises(wanted && wanted.id);
});

$("tp").addEventListener("change", () => fillExercises());
$("ex").addEventListener("change", switchMode);

function aller(pas) {
  const i = catalogue.findIndex(t => t.id === $("ex").value);
  const cible = catalogue[i + pas];
  if (!cible) return;
  $("tp").value = cible.group;
  fillExercises(cible.id);
}
$("prev").addEventListener("click", () => aller(-1));
$("next").addEventListener("click", () => aller(1));

function fillExercises(preselect) {
  const items = catalogue.filter(t => t.group === $("tp").value);
  $("ex").innerHTML = "";
  for (const t of items) addOption($("ex"), t.id, t.short);
  if (preselect) $("ex").value = preselect;
  $("exwrap").hidden = items.length <= 1;
  switchMode();
}

const DRAFTS_KEY = "ctester.drafts";

function sanitizeDrafts(raw) {
  const clean = {};
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return clean;
  for (const [exercise, files] of Object.entries(raw)) {
    if (!files || typeof files !== "object" || Array.isArray(files)) continue;
    const kept = {};
    for (const [name, text] of Object.entries(files)) {
      if (typeof text === "string") kept[name] = text;
    }
    clean[exercise] = kept;
  }
  return clean;
}

function loadDrafts() {
  try {
    return sanitizeDrafts(JSON.parse(localStorage.getItem(DRAFTS_KEY)));
  } catch (e) {
    return {};
  }
}

const drafts = loadDrafts();
let currentId = null;
let saveTimer = null;
let loadToken = 0;

function showDraftStatus(text, failed) {
  $("brouillon").textContent = text;
  $("brouillon").className = failed ? "rate" : "";
}

const twoDigits = (n) => String(n).padStart(2, "0");

function saveDraft() {
  if (currentId === null || actif === null) return;
  sources[actif] = $("code").value;
  drafts[currentId] = sources;
  try {
    localStorage.setItem(DRAFTS_KEY, JSON.stringify(drafts));
  } catch (e) {
    showDraftStatus("brouillon NON enregistré — garde une copie de ton code", true);
    return;
  }
  const t = new Date();
  showDraftStatus("brouillon enregistré à "
                + twoDigits(t.getHours()) + ":" + twoDigits(t.getMinutes()));
  $("purger").hidden = false;
  if (ctester.compte) ctester.compte.syncDraft(currentId, sources);
}
$("purger").hidden = !Object.keys(drafts).length;

$("purger").addEventListener("click", () => {
  clearTimeout(saveTimer);
  for (const exercise of Object.keys(drafts)) delete drafts[exercise];
  try { localStorage.removeItem(DRAFTS_KEY); } catch (e) {}
  showDraftStatus("brouillons effacés");
  $("purger").hidden = true;
});

function switchMode() {
  clearTimeout(saveTimer);
  saveDraft();
  const tp = current();
  // `currentId` EST CE QUE L'EDITEUR TIENT, pas ce que le menu montre. Le
  // remplissage passe par le reseau depuis que le detail est charge a la
  // demande : le poser ici ferait attribuer le code de l'exercice precedent,
  // toujours affiche, a l'identifiant du nouveau des le prochain saveDraft().
  // C'est setupFiles qui le pose, une fois l'editeur vraiment rempli.
  currentId = null;
  const quiz = tp && tp.mode === "quiz";
  const i = catalogue.findIndex(t => t.id === $("ex").value);
  $("prev").disabled = i <= 0;
  $("next").disabled = i < 0 || i >= catalogue.length - 1;
  $("editor").hidden = quiz;
  $("filewrap").hidden = quiz;
  $("quizwrap").hidden = !quiz;
  // Hors quiz il n'y a qu'un bouton et il est primaire. En quiz, l'action
  // courante est l'exercice affiche : tester les 40 questions reste possible,
  // mais cesse d'etre ce sur quoi on tombe par defaut.
  $("goex").hidden = !quiz;
  $("go").className = quiz ? "secondaire" : "";
  $("go").textContent = quiz ? "Tester tout le quiz" : "Tester";

  $("now").innerHTML = "";
  if (tp) {
    const titre = document.createElement("b");
    titre.textContent = tp.label;
    const pastille = document.createElement("span");
    pastille.className = "badge";
    pastille.textContent = ATTENDU[tp.mode] || "";
    $("now").append(titre, pastille);
    const learning = tp.learning || {};
    const details = [];
    if (Array.isArray(learning.skills) && learning.skills.length) {
      details.push("objectif : " + learning.skills.map(
        s => SKILL_LABELS[s] || s).join(", "));
    }
    if (CONTEXT_LABELS[learning.context]) details.push(CONTEXT_LABELS[learning.context]);
    if (DIFFICULTY_LABELS[learning.difficulty]) details.push(DIFFICULTY_LABELS[learning.difficulty]);
    if (details.length) {
      const objective = document.createElement("span");
      objective.className = "learning";
      objective.textContent = details.join(" — ");
      $("now").append(objective);
    }
  }

  afficherConsigne(null);
  show("idle", "En attente d'une soumission.");
  preparer(tp, quiz, ++loadToken);
}

function afficherConsigne(texte) {
  if (texte === null) {
    $("consignetexte").textContent = "Chargement…";
    $("consignetexte").className = "vide";
    return;
  }
  $("consignetexte").textContent = texte
    || "Cet exercice n'a pas de consigne en ligne. Reporte-toi à l'énoncé du TP "
     + "sur Moodle : les noms de fichiers et de fonctions attendus y sont.";
  $("consignetexte").className = texte ? "" : "vide";
}

const details = {};

// LE DÉTAIL D'UN EXERCICE, chargé quand on l'ouvre. La consigne et les gabarits
// font les trois quarts du catalogue pour 72 exercices dont un seul est
// affiché ; `tps.json` ne porte plus qu'un menu. Gardé en mémoire : revenir sur
// un exercice déjà vu ne redemande rien.
async function chargerDetail(id) {
  if (details[id]) return details[id];
  try {
    const r = await fetch("tp/" + id + ".json");
    if (!r.ok) throw new Error("HTTP " + r.status);
    const d = await r.json();
    details[id] = {
      statement: typeof d.statement === "string" ? d.statement : "",
      files: Array.isArray(d.files) ? d.files : [],
    };
    return details[id];
  } catch (e) {
    // Réseau coupé, détail manquant : on ne bloque pas la page. La consigne
    // retombe sur son message de repli, l'éditeur sur des gabarits vides -- les
    // NOMS de fichiers viennent du catalogue et sont donc toujours là, donc on
    // peut coller son code et soumettre. Le repli n'est PAS mis en cache : un
    // réseau qui revient doit pouvoir réessayer.
    return { statement: "", files: [] };
  }
}

async function preparer(tp, quiz, thisLoad) {
  if (!tp) { afficherConsigne(""); return; }
  const detail = await chargerDetail(tp.id);
  if (thisLoad !== loadToken) return;
  afficherConsigne(detail.statement);
  if (quiz) {
    if (await activerModule("quiz", "le quiz")) ctester.quiz.load(tp.id);
    return;
  }
  if (ctester.compte) {
    const answer = await ctester.compte.getJson(
      "brouillon?ex=" + encodeURIComponent(tp.id));
    if (thisLoad !== loadToken) return;
    const clean = sanitizeDrafts({ [tp.id]: answer && answer.sources });
    if (Object.keys(clean[tp.id] || {}).length) drafts[tp.id] = clean[tp.id];
  }
  setupFiles(tp, detail.files);
}


const ESC = {"&": "&amp;", "<": "&lt;", ">": "&gt;"};
const esc = (s) => s.replace(/[&<>]/g, (c) => ESC[c]);

const KEYWORDS = "auto|break|case|char|const|continue|default|do|double|else|" +
  "enum|extern|float|for|goto|if|inline|int|long|register|restrict|return|" +
  "short|signed|sizeof|static|struct|switch|typedef|union|unsigned|void|" +
  "volatile|while|bool|true|false|NULL";

const C_RE = new RegExp([
  "(\\/\\/[^\\n]*|\\/\\*[\\s\\S]*?\\*\\/)",
  "(\"(?:\\\\.|[^\"\\\\\\n])*\"|'(?:\\\\.|[^'\\\\\\n])*')",
  "(^[ \\t]*#[ \\t]*\\w+)",
  "\\b(" + KEYWORDS + ")\\b",
  "\\b(\\d[\\w.]*)",
  "([A-Za-z_]\\w*)(?=\\s*\\()",
  "\\b([A-Z][A-Z0-9_]{2,})\\b"
].join("|"), "gm");

const CLASS = ["tc", "ts", "tp", "tk", "tn", "tf", "tu"];

function highlight(src) {
  let out = "", last = 0;
  for (const m of src.matchAll(C_RE)) {
    out += esc(src.slice(last, m.index));
    const which = m.slice(1, CLASS.length + 1).findIndex(g => g !== undefined);
    out += '<span class="' + CLASS[which] + '">' + esc(m[0]) + "</span>";
    last = m.index + m[0].length;
  }
  return out + esc(src.slice(last)) + "\n";
}

let lignesAffichees = -1;

function gouttiere(n) {
  if (n === lignesAffichees) return;
  lignesAffichees = n;
  let s = "";
  for (let i = 1; i <= n; i++) s += i + "\n";
  $("gutter").textContent = s;
}

function paint() {
  $("hlcode").innerHTML = highlight($("code").value);
  gouttiere($("code").value.split("\n").length);
  $("hl").scrollTop = $("code").scrollTop;
  $("gutter").scrollTop = $("code").scrollTop;
  $("hl").scrollLeft = $("code").scrollLeft;
}

$("code").addEventListener("input", () => {
  paint();
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveDraft, 1500);
});
$("code").addEventListener("scroll", paint);

$("connexion").addEventListener("click", () => { $("consentement").hidden = false; });
$("consentnon").addEventListener("click", () => { $("consentement").hidden = true; });
$("consentok").addEventListener("click", async () => {
  $("consentement").hidden = true;
  if (!await activerModule("compte", "la partie « compte »")) return;
  // ATTENDU, ET PAS LANCÉ DANS LE VIDE. `startSignIn` fait une découverte
  // réseau puis un défi PKCE : sans ce `await`, un échec devient une promesse
  // rejetée que personne ne lit, et le bouton ne fait RIEN — ni redirection,
  // ni message. C'est précisément la panne qu'on a vue.
  try {
    await ctester.compte.startSignIn();
  } catch (e) {
    show("bad", "La connexion n'a pas pu démarrer : " + e.message
              + ". Tu peux continuer sans compte.");
  }
});
$("mesexos").addEventListener("click", () => {
  if (ctester.compte) ctester.compte.basculerListe();
});
// LE BOUTON N'EXISTE QUE CONNECTÉ (refreshAccount), et le fichier n'arrive
// qu'au clic : même contrat que compte.js. Un étudiant connecté qui n'ouvre
// jamais ses progrès n'en télécharge rien non plus.
$("mesprogres").addEventListener("click", async () => {
  if (!await activerModule("progres", "« Mes progrès »")) return;
  await ctester.progres.basculer();
});
// MÊME CONTRAT QUE « Mes progrès » : le bouton n'existe que connecté ET que si
// le déploiement a des modérateurs, et le fichier ne descend qu'au clic.
$("discussions").addEventListener("click", async () => {
  if (!await activerModule("forum", "les discussions")) return;
  await ctester.forum.basculer();
});
$("deconnexion").addEventListener("click", () => {
  if (ctester.compte) ctester.compte.signOut();
});
$("oublier").addEventListener("click", () => {
  if (ctester.compte) ctester.compte.oublier();
});

// LE PARCOURS ANONYME NE TÉLÉCHARGE RIEN DU COMPTE. On ne va chercher compte.js
// que s'il y a une session en cours, un retour de connexion, ou un clic sur
// « Se connecter » : c'est-à-dire jamais pour l'étudiant qui passe sans compte,
// et c'est lui le parcours par défaut.
fetch("oidc.json").then(r => r.json()).then(async (config) => {
  if (!config || !config.issuer || !config.client_id) return;
  oidc = config;
  const jeton = sessionGet(TOKEN_KEY);
  token = jeton || null;
  refreshAccount();
  if (!jeton && !authCode) return;
  if (await activerModule("compte", "la partie « compte »")) await ctester.compte.demarrer();
}).catch(() => {});

Object.assign(ctester, {
  $: $,
  show: show,
  sessionGet: sessionGet,
  sessionSet: sessionSet,
  sessionDrop: sessionDrop,
  authCode: authCode,
  authState: authState,
  // DES FONCTIONS, PAS DES `get`. `catalogue`, `token` et `oidc` sont
  // réaffectés après le chargement, donc une copie mentirait -- et
  // `Object.assign` copie justement la VALEUR d'un getter, pas le getter :
  // `ctester.token` serait resté figé à null pour toute la visite, et tout ce
  // qui suit un compte (états, pratique, synchronisation des brouillons)
  // serait tombé en silence. C'est arrivé.
  // Le chargeur de scripts, exposé pour les DEUX bibliothèques du rendu du
  // forum (`app/vendor/`). Même mécanique que les modules, mêmes garanties :
  // une promesse par fichier, un échec jamais gardé, et l'appelant décide quoi
  // faire quand ça n'arrive pas -- pour le forum, retomber sur du texte brut.
  charger: charger,
  catalogue: () => catalogue,
  token: () => token,
  oidc: () => oidc,
  setToken: setToken,
  refreshAccount: refreshAccount,
  switchMode: switchMode,
  fillExercises: fillExercises,
  showDraftStatus: showDraftStatus,
  exerciceOuvert: () => currentId,
  afficherVue: afficherVue,
  vue: () => vueCourante,
  // Les libellés de compétence sont déjà ici pour la barre de contexte : les
  // recopier dans progres.js ferait deux tables à tenir à jour, dont une se
  // périmerait en silence.
  skillLabel: (id) => SKILL_LABELS[id] || id,
});

let sortieClavier = false;
$("code").addEventListener("keydown", (e) => {
  if (e.key === "Escape") { sortieClavier = true; return; }
  if (e.key !== "Tab" || e.ctrlKey || e.metaKey || e.altKey) {
    sortieClavier = false;
    return;
  }
  if (sortieClavier) { sortieClavier = false; return; }
  e.preventDefault();
  const zone = $("code");
  const debut = zone.selectionStart, fin = zone.selectionEnd;
  zone.value = zone.value.slice(0, debut) + "    " + zone.value.slice(fin);
  zone.selectionStart = zone.selectionEnd = debut + 4;
  paint();
});

let sources = {};
let actif = null;

function setupFiles(tp, gabarits) {
  // Les NOMS font foi et viennent du catalogue -- c'est la liste blanche que
  // l'API oppose à la soumission. Les gabarits, eux, viennent du détail et
  // peuvent manquer : un onglet sans gabarit s'ouvre vide.
  const modeles = Object.fromEntries(
    (gabarits || []).map(f => [f.name, f.template || ""]));
  const files = ((tp && tp.files && tp.files.length)
    ? tp.files : [{ name: "submission.c" }])
    .map(f => ({ name: f.name, template: modeles[f.name] || "" }));
  sources = (tp && drafts[tp.id]) || null;
  if (!sources) {
    sources = {};
    for (const f of files) sources[f.name] = f.template || "";
  }
  actif = null;
  currentId = tp ? tp.id : null;
  $("tabs").innerHTML = "";
  for (const f of files) {
    const onglet = document.createElement("button");
    onglet.type = "button";
    onglet.className = "tab";
    onglet.textContent = f.name;
    onglet.dataset.name = f.name;
    onglet.setAttribute("role", "tab");
    onglet.addEventListener("click", () => activer(f.name));
    $("tabs").append(onglet);
  }
  $("tabs").hidden = files.length <= 1;
  $("edtitle").hidden = files.length > 1;
  activer(files[0].name);
}

function activer(nom) {
  if (actif !== null) sources[actif] = $("code").value;
  actif = nom;
  $("edtitle").textContent = nom;
  $("code").value = sources[nom] || "";
  for (const onglet of $("tabs").children) {
    const courant = onglet.dataset.name === nom;
    onglet.className = courant ? "tab on" : "tab";
    onglet.setAttribute("aria-selected", courant ? "true" : "false");
    onglet.tabIndex = courant ? 0 : -1;
  }
  paint();
}

$("tabs").addEventListener("keydown", (e) => {
  const pas = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
  if (!pas) return;
  const noms = [...$("tabs").children].map(o => o.dataset.name);
  const i = noms.indexOf(actif);
  if (i >= 0) activer(noms[(i + pas + noms.length) % noms.length]);
});

$("file").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  $("code").value = await f.text();
  paint();
});

function cases(items) {
  const box = document.createElement("div");
  for (const c of items) {
    const wrap = document.createElement("details");
    wrap.className = "case";
    wrap.open = !box.children.length;
    const why = document.createElement("summary");
    why.textContent = `Cas ${c.case} : ${c.reason}`;
    const corps = document.createElement("div");
    corps.className = "corps";
    let texte = "entrées :\n" + c.stdin + "\nta sortie :\n" + (c.stdout || "(rien)");
    if (c.stderr) texte += "\nta sortie d'erreur :\n" + c.stderr;
    const io = document.createElement("pre");
    io.textContent = texte;
    corps.append(io);
    wrap.append(why, corps);
    if (c.nombres) {
      const vu = document.createElement("div");
      vu.className = "vu";
      vu.textContent = c.nombres.length
        ? "nombres lus dans ta sortie : " + c.nombres.join(", ")
        : "aucun nombre lu dans ta sortie";
      corps.append(vu);
    }
    box.append(wrap);
  }
  return box;
}

function avertissements(texte) {
  const bloc = document.createElement("div");
  bloc.className = "avert";
  const titre = document.createElement("div");
  titre.className = "titre";
  titre.textContent = "Avertissements du compilateur";
  const quoi = document.createElement("div");
  quoi.className = "quoi";
  quoi.textContent = "Ce n'est pas une erreur : ton programme compile. "
                   + "Mais gcc a remarqué ceci, et ça vaut le coup d'œil.";
  const corps = document.createElement("pre");
  corps.textContent = texte;
  bloc.append(titre, quoi, corps);
  return bloc;
}

const UNITS = {quiz: "réponses justes", io: "cas réussis", unity: "tests réussis"};

// CE QU'ON ATTEND COMME SOUMISSION, par mode. Les TROIS modes, et pas
// « quiz ou le reste » : un exercice unity attend un module SANS main(), et
// promettre l'inverse envoie 42 des 72 exercices droit dans une erreur
// d'édition de liens que l'étudiant n'a aucun moyen de rattacher à la
// pastille qui la lui a demandée.
const ATTENDU = {
  quiz: "réponses à saisir",
  io: "programme complet, avec son main()",
  unity: "module seul, sans main()",
};

// « Tester l'exercice » ne change RIEN a la correction : le juge garde le
// corrige et note le quiz entier, et c'est de ce verdict complet que l'API
// derive « valide ». Seule la LECTURE est restreinte -- les questions des
// autres exercices sortent du decompte et de la liste. Un exercice juste ne
// peut donc pas valider un TP a moitie rempli.
function restreindre(r, portee) {
  const wrong = (r.wrong || []).filter(w => portee.ids.indexOf(w.id) >= 0);
  return Object.assign({}, r, {
    total: portee.ids.length,
    passed: portee.ids.length - wrong.length,
    wrong: wrong,
  });
}

function render(r, portee) {
  if (r.status !== "ok") {
    show("bad", r.message, r.status === "compile_error" ? block(r.gcc || "") : null);
  } else {
    const cadre = portee && r.kind === "quiz" ? " — " + portee.titre : "";
    if (portee && r.kind === "quiz") r = restreindre(r, portee);
    const all = r.passed === r.total;
    const title = `${r.passed} / ${r.total} ${UNITS[r.kind] || "réussis"}${cadre}`;
    const bar = r.total > 0 ? ticks(r.passed, r.total) : null;
    if (all) {
      show("ok", title, null, bar);
    } else if (r.kind === "quiz") {
      show("bad", title, list(r.wrong.map(w => {
        const groupe = ctester.quiz ? ctester.quiz.groupeDe(w.id) : "";
        const ex = groupe.match(/Exercice\s*\d+/i);
        const vide = !(w.given && w.given.trim());
        const saisi = vide ? "" : ` (tu as répondu « ${w.given} »)`;
        // Pas repondu n'est pas faux : le rouge est reserve aux erreurs.
        return {
          text: (ex ? ex[0] + " — " : "") + w.label + saisi
              + (w.hint ? " — " + w.hint : ""),
          cls: vide ? "rien" : "",
        };
      })), bar);
    } else if (r.kind === "io") {
      show("bad", title, cases(r.cases), bar);
    } else {
      show("bad", title, r.failed.length ? list(r.failed) : null, bar);
    }
  }
  if (r.warnings) out.append(avertissements(r.warnings));
}

// Les DEUX boutons se bloquent ensemble : ils envoient la meme soumission.
function occupe(oui) {
  $("go").disabled = oui;
  $("goex").disabled = oui;
}

async function poll(id, tries, portee) {
  const r = await fetch("r/" + id);
  const body = await r.json().catch(() => ({state: "error"}));
  if (body.state === "done") {
    render(body, portee);
    // The API has just derived the exercise state from this verdict. Refresh
    // the private projections so « Mes exercices » reflects it immediately;
    // this is display state, not a client-side declaration of success.
    // LE VERDICT EST DÉJÀ À L'ÉCRAN, et rien de ce qui suit ne doit pouvoir le
    // gâter : d'où le `finally`. Sans lui, une projection privée qui lèverait
    // laisserait les deux boutons « Tester » bloqués sur un résultat correct.
    try {
      if (ctester.compte) {
        await Promise.all([ctester.compte.loadStates(),
                           ctester.compte.loadPractice()]);
      }
      // L'API vient peut-être d'accorder l'XP d'une première réussite. On
      // REDEMANDE la projection au serveur -- la page n'en calcule aucune part.
      // Rien à rafraîchir tant que le module n'a jamais été ouvert : il ira
      // chercher l'état frais à son premier affichage.
      if (ctester.progres) await ctester.progres.rafraichir();
    } finally {
      occupe(false);
    }
    return;
  }
  if (r.status === 404 || tries <= 0) {
    show("bad", "Résultat perdu. Relance les tests.");
    occupe(false);
    return;
  }
  show("wait", body.state === "running"
       ? "Compilation en cours…"
       : `En file d'attente — ${body.position}${body.position === 1 ? "er" : "e"}`);
  setTimeout(() => poll(id, tries - 1, portee), 2000);
}

// `portee` : les identifiants de l'exercice affiche, ou null pour tout le TP.
async function soumettre(portee) {
  const tp = current();
  if (!tp) { show("bad", "Choisis un TP."); return; }
  const body = {key, tp: tp.id};
  if (tp.mode === "quiz") {
    if (!ctester.quiz) { show("bad", "Le quiz n'est pas chargé."); return; }
    body.answers = ctester.quiz.answers();
    if (!Object.values(body.answers).some(v => v.trim())) {
      show("bad", "Aucune réponse saisie."); return;
    }
  } else {
    sources[actif] = $("code").value;
    body.files = sources;
    if (!Object.values(sources).some(v => v.trim())) {
      show("bad", "Il n'y a rien à tester."); return;
    }
  }
  occupe(true);
  show("wait", "Envoi…");
  try {
    const r = await fetch("submit", {
      method: "POST",
      // La connexion est facultative : sans jeton, la soumission reste
      // anonyme. Avec lui, l'API peut rattacher le job au compte et enregistrer
      // la pratique/le statut à partir de son propre verdict.
      headers: Object.assign({"Content-Type": "application/json"},
                             token ? {Authorization: "Bearer " + token} : {}),
      body: JSON.stringify(body)
    });
    let out = null;
    try { out = await r.json(); } catch (parseError) { out = null; }
    if (!r.ok || !out) {
      show("bad", (out && out.error) ||
                  `Le serveur a répondu ${r.status} sans JSON exploitable.`);
      occupe(false);
      return;
    }
    poll(out.id, 150, portee);
  } catch (e) {
    show("bad", "Le serveur est injoignable : " + e.message);
    occupe(false);
  }
}

$("go").addEventListener("click", () => soumettre(null));
$("goex").addEventListener("click", () => soumettre(
  ctester.quiz ? ctester.quiz.page() : null));
