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
const ASSET_REVISION = "20260904-catalogue-v2";

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
    systeme("Impossible de charger " + quoi + ". Vérifie ta connexion, "
          + "puis recharge la page.", true);
    return false;
  }
  if (!ctester[nom]) {
    // Le fichier est arrivé mais ne s'est pas déclaré : version en cache d'un
    // ancien déploiement, coupure en plein transfert. Se taire ici rendrait le
    // bouton inerte sans un mot.
    systeme("Impossible d'utiliser " + quoi
          + " : le fichier est arrivé incomplet. Recharge la page.", true);
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

// LA CLÉ D'ACCÈS SURVIT À UN RECHARGEMENT SANS SA QUERY. Elle arrive par le
// lien de Moodle (`?k=…`) ; un étudiant qui tape l'adresse de tête, suit un
// lien partagé sans la clé, ou revient par un signet, se retrouvait sans elle
// -- et ne l'apprenait qu'après avoir écrit son code.
//
// `sessionStorage` ET PAS `localStorage`, délibérément : la clé meurt avec
// l'onglet. Sur un poste de labo partagé, la laisser derrière soi la donnerait
// au prochain étudiant qui s'assoit.
const CLE_KEY = "ctester.cle";
const cleDuLien = new URLSearchParams(location.search).get("k") || "";
if (cleDuLien) sessionSet(CLE_KEY, cleDuLien);
const key = cleDuLien || sessionGet(CLE_KEY);

// ON LE DIT AU CHARGEMENT, PAS À LA PREMIÈRE SOUMISSION. Sans ça,
// l'étudiant écrivait son exercice entier avant d'apprendre qu'il ne
// pouvait pas le tester -- et il l'apprenait par « clé de session invalide
// ou expirée », qui ne veut rien dire pour lui et ne dit pas quoi faire.
// Non bloquant : écrire et enregistrer marchent parfaitement sans clé.
if (!key) {
  systeme("Il manque ta clé d'accès. Rouvre le lien de CTester depuis Moodle "
        + "pour pouvoir tester ton code. Tu peux écrire en attendant : "
        + "ton brouillon est enregistré.");
}
const out = $("out");
// FOCALISABLE SANS ÊTRE DANS LA TABULATION : `amenerLeResultat()` y pose le
// focus sur petit écran, où le verdict arrive hors de l'écran.
out.tabIndex = -1;

const THEME_KEY = "ctester.theme";

function appliquerTheme(nom) {
  document.documentElement.dataset.theme = nom;
  const clair = nom === "light";
  $("theme").textContent = clair ? "☾" : "☀";
  $("theme").title = clair ? "Passer au thème sombre" : "Passer au thème clair";
  $("theme").setAttribute("aria-label", $("theme").title);
}

// LE STOCKAGE LOCAL RESTE LA MÉMOIRE DE L'APPAREIL, même quand le compte a le
// dernier mot : c'est lui que le script du <head> lit avant le premier rendu,
// et rien d'autre ne peut arriver assez tôt pour éviter le flash. Ce que le
// serveur dit est donc recopié ici -- pas pour être relu par la page, mais
// pour que la visite SUIVANTE parte déjà du bon thème.
function retenirTheme(nom) {
  try { localStorage.setItem(THEME_KEY, nom); } catch (e) {}
}

appliquerTheme(document.documentElement.dataset.theme === "light"
               ? "light" : "dark");

const themeCourant = () =>
  document.documentElement.dataset.theme === "light" ? "light" : "dark";

$("theme").addEventListener("click", () => {
  const suivant = themeCourant() === "light" ? "dark" : "light";
  appliquerTheme(suivant);
  retenirTheme(suivant);
  // ET SUR LE COMPTE, QUAND IL Y EN A UN. `compte.js` n'est chargé que pour
  // une session en cours : l'anonyme ne déclenche aucune requête ici, et le
  // module lui-même ne fait rien sans jeton. Rien n'est attendu -- le thème
  // est déjà appliqué à l'écran, et un aller-retour raté ne doit pas donner
  // l'impression que le bouton n'a pas marché.
  if (ctester.compte) ctester.compte.enregistrerTheme(suivant);
});

// --- DEUX CANAUX, ET IL NE FAUT PLUS JAMAIS LES CONFONDRE ------------------
//
// LE VERDICT PARLE DU CODE DE L'ÉTUDIANT. LE BANDEAU SYSTÈME PARLE DU SERVICE.
// Un seul `show("bad")` rouge servait aux deux : « ton fichier ne compile pas »
// et « le serveur est injoignable » s'affichaient à l'identique, au même
// endroit, dans la même typographie de titre. Un débutant en conclut qu'il a
// cassé quelque chose -- une attribution d'erreur fausse, dans exactement les
// situations où il n'y est pour rien.
//
// Sur les dix-sept messages rouges d'avant, QUATRE seulement étaient un verdict.
// Ne pas refondre ces deux fonctions en une seule.

function noeud(balise, classe, texte) {
  const n = document.createElement(balise);
  if (classe) n.className = classe;
  if (texte !== undefined) n.textContent = texte;
  return n;
}

// CE QUI EST ANNONCÉ AUX LECTEURS D'ÉCRAN, ET RIEN D'AUTRE : une ligne courte.
// `#out` n'a délibérément PAS d'aria-live -- il porte la sortie du compilateur,
// et l'annoncer en entier serait pire que le silence.
function annoncer(texte) {
  $("annonce").textContent = texte;
}

// --- Le canal du service ---------------------------------------------------
// Réseau, quota, file pleine, clé de session, module manquant, connexion : tout
// ce dont l'étudiant n'est pas responsable. Ton neutre, jamais l'emplacement du
// verdict, et toujours une phrase qui dit ce qui N'EST PAS perdu.
function systeme(texte, panne) {
  const boite = $("systeme");
  boite.textContent = texte || "";
  boite.className = panne ? "panne" : "";
  boite.hidden = !texte;
  if (texte) annoncer(texte);
}

const effacerSysteme = () => systeme("");

// --- Le canal du verdict ---------------------------------------------------

// LES TROIS ÉTAPES QU'UN DÉBUTANT DOIT APPRENDRE À DISTINGUER. Le persona ne
// sépare pas compilation, exécution et logique ; le serveur, lui, sait toujours
// laquelle a cassé, et la page jetait cette information. Nommer l'étape NON
// ATTEINTE est ce qui répond à « est-ce que mon programme a seulement tourné ? ».
// L'ACCORD SUIT L'ÉTAPE. « Tests pas atteinte » est du charabia, et cette page
// s'adresse à des étudiants en français : les deux premières étapes sont
// féminines singulier, la troisième masculin pluriel.
const ETAPES = [["Compilation", "f"], ["Exécution", "f"], ["Tests", "mp"]];
const ETAT_ETAPE = {
  f:  { ok: "réussie",  ko: "échouée",  "": "pas atteinte" },
  mp: { ok: "réussis",  ko: "échoués",  "": "pas atteints" },
};

// LA BANDE S'ARRÊTE OÙ LE COMPTE PREND LE RELAIS. Quand le juge a noté, le
// verdict affiche « 3 / 3 cas réussis » juste en dessous, en gros : une case
// « Tests 3/3 » au-dessus ne fait que le redire. On ne passe donc que DEUX
// étapes dans ce cas. Quand le juge n'a PAS noté, la troisième case porte au
// contraire l'information qui manquait -- « pas atteints » -- et elle reste.
function bandeEtapes(etats) {
  const bande = noeud("div", "etapes");
  etats.forEach((etat, i) => {
    const [nom, genre] = ETAPES[i];
    const pas = noeud("span", "pas " + (etat || "vide"));
    // LE MOT, PAS SEULEMENT LA COULEUR ni seulement une coche : un état qui ne
    // se voit qu'en teinte disparaît en noir et blanc comme sous un daltonisme,
    // et ne se lit pas à voix haute.
    pas.append(noeud("b", "", nom));
    pas.append(noeud("i", "", ETAT_ETAPE[genre][etat]));
    bande.append(pas);
  });
  return bande;
}

// CE QUE CHAQUE ÉTAT VEUT DIRE POUR L'ÉTUDIANT : où ça a cassé, comment le dire
// en une ligne, et quoi faire ensuite. Tout est dérivé de ce que `/r/<id>`
// renvoie DÉJÀ -- aucun changement serveur n'a été nécessaire.
//
//   `etapes` : "ok" réussie, "ko" échouée, "" pas atteinte.
//   `titre`  : COURT. C'est lui qui porte la couleur et lui qui est annoncé.
//   `suite`  : l'action suivante. Toujours exactement une.
//
// L'EXPLICATION N'EST PAS ICI : c'est `message`, écrit par le serveur pour
// l'étudiant. La recopier ferait deux endroits à corriger, dont un se
// périmerait en silence. Quand le titre ci-dessous EST le message du serveur,
// `verdict()` ne le répète pas.
const ETATS = {
  forbidden_include: {
    etapes: ["ko", "", ""],
    titre: "Un #include n'est pas autorisé",
    suite: "Retire cette ligne, puis relance le test.",
  },
  compile_error: {
    etapes: ["ko", "", ""],
    titre: "Ton fichier ne compile pas.",
    suite: "Corrige la PREMIÈRE erreur : les suivantes en découlent souvent.",
  },
  compile_timeout: {
    etapes: ["ko", "", ""],
    titre: "La compilation a été trop longue",
    suite: "Réessaie. Si ça recommence, préviens ton enseignant.",
  },
  // « Compilation échouée » plutôt qu'une quatrième étape « Assemblage » : gcc
  // fait les deux en une seule commande dans le cours, et ajouter un concept
  // pour un seul état coûterait plus qu'il ne rapporte. Le message du serveur
  // dit la nuance, et le titre ci-dessous la dit aussi.
  link_error: {
    etapes: ["ko", "", ""],
    titre: "Ton code ne s'assemble pas avec les tests",
    // L’ACTION AJOUTE, ELLE NE RÉPÈTE PAS. Le message du serveur dit déjà quoi
    // vérifier ; ce qui manque à un débutant, c’est COMMENT s’y prendre.
    suite: "Compare ta signature avec celle de l’énoncé, caractère par caractère.",
  },
  memory_error: {
    etapes: ["ok", "ko", ""],
    titre: "Ton programme sort de la mémoire qu'il a réservée",
    suite: "Revois tes conditions de boucle (< et non <=) et la taille que tu "
         + "réserves.",
  },
  timeout: {
    etapes: ["ok", "ko", ""],
    titre: "Ton programme ne s'est pas arrêté",
    suite: "Vérifie tes conditions de boucle et le nombre de valeurs que tu lis.",
  },
  error: {
    etapes: ["ok", "ko", ""],
    titre: "Ton programme s'est arrêté avant la fin",
    suite: "Plantage probable : indice hors des bornes, pointeur invalide, ou "
         + "chaîne sans son terminateur.",
  },
};

// L'ACTION SUIVANTE, ET IL EN FAUT UNE PARTOUT -- succès compris. Le moment où
// l'étudiant est le plus disponible était précisément celui où la page ne lui
// proposait rien.
function bandeSuite(texte, bouton) {
  const bloc = noeud("div", "suite");
  bloc.append(noeud("span", "", texte));
  if (bouton) {
    const b = noeud("button", "nav", bouton.libelle);
    b.type = "button";
    b.addEventListener("click", bouton.faire);
    bloc.append(b);
  }
  return bloc;
}

// L'AIDE S'OFFRE LÀ OÙ LE BESOIN NAÎT : devant un verdict qui échoue, pas dans
// un bouton de la barre globale. Le fil est DÉJÀ par exercice (`forum.js` le
// scope sur l'exercice courant) ; seul son point d'entrée était global, à
// l'autre bout de l'écran, et ne se remarquait pas au moment utile.
//
// LES MÊMES DEUX CONDITIONS QUE LE BOUTON DE LA BARRE, et elles viennent toutes
// deux du serveur : être connecté, et un déploiement qui a des modérateurs. Un
// forum sans personne pour le lire ne s'ouvre pas « en attendant ».
function boutonAide() {
  if (!token || !(oidc && oidc.forum)) return null;
  const b = noeud("button", "nav aide", "En parler dans les discussions");
  b.type = "button";
  b.addEventListener("click", async () => {
    if (!await activerModule("forum", "les discussions")) return;
    await ctester.forum.basculer();
  });
  return b;
}

// LE DERNIER VERDICT RENDU, pour le rappeler en tête d'un fil de discussion.
// DÉCLARÉ ICI, au-dessus de la fonction qui l'écrit : un `let` posé mille
// lignes plus bas est une zone morte temporelle, et c'est la seule panne que
// cette page ait connue en production.
let dernierVerdict = null;

// `v` : {cls, etapes, compte, titre, texte, bar, detail, suite, bouton}
// Seul `titre` est obligatoire.
function verdict(v) {
  // RETENU POUR LES DISCUSSIONS : ouvrir un fil efface le poste de travail, et
  // ce qu'on venait raconter avec. Seuls les vrais verdicts comptent -- ni
  // l'attente, ni le repos.
  if (v.cls === "ok" || v.cls === "bad") {
    dernierVerdict = { exercice: selection, titre: v.titre };
  }
  out.className = v.cls;
  out.innerHTML = "";
  if (v.etapes) out.append(bandeEtapes(v.etapes));
  // LE COMPTE GARDE LA GRANDE TAILLE, le titre d'un état ne l'a plus. `3 / 4`
  // se lit d'un coup d'oeil et le mérite ; « Ton code ne s'assemble pas avec
  // les tests » en 2,1 rem écrasait la zone entière. Seul le chemin `ok` pose
  // un compte, donc le drapeau sépare exactement les deux cas.
  out.append(noeud("div", "verdict " + v.cls + (v.compte ? " compte" : ""),
                   v.titre));
  if (v.cls === "wait") out.append(indeterminee());
  if (v.bar) out.append(v.bar);
  // EN CORPS DE TEXTE, PLUS JAMAIS EN 2,1 REM. Les messages de `link_error` et
  // de `memory_error` font deux cents caractères : en typographie de titre, ils
  // écrasaient toute la zone de résultat.
  if (v.texte && v.texte !== v.titre) out.append(noeud("p", "explique", v.texte));
  if (v.detail) out.append(v.detail);
  if (v.suite) {
    const bande = bandeSuite(v.suite, v.bouton);
    // SEULEMENT SUR UN ÉCHEC : on ne propose pas d'aller demander de l'aide à
    // quelqu'un dont tout vient de passer.
    const aide = v.cls === "bad" ? boutonAide() : null;
    if (aide) bande.append(aide);
    out.append(bande);
  }
  annoncer(v.titre);
}

// L'ÉTAT DE REPOS. Pas d'étapes -- rien n'a encore tourné, et une bande de
// trois « pas atteinte » avant la première soumission annoncerait un échec.
function repos() {
  verdict({
    cls: "idle",
    titre: "En attente d'une soumission.",
    texte: "Écris ton code, puis clique sur « Tester ». Les résultats ne sont "
         + "pas une note : ces tests t'aident à trouver tes erreurs, ils ne "
         + "remplacent pas la correction.",
  });
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

// LA PREMIÈRE ERREUR, PAS LA DERNIÈRE. En C les erreurs partent en cascade :
// un `;` oublié en produit six, dont cinq n'existent pas. Or la sortie brute
// défile, et ce qu'un débutant lit, c'est le BAS -- donc la plus dérivée, celle
// qui ne correspond à rien dans son code. On isole la première et on replie le
// reste, sans rien cacher.
const DIAGNOSTIC = /(^|\s)(error|erreur|warning|attention|note)\s*:/i;

function premiereErreur(sortie) {
  const lignes = (sortie || "").split("\n");
  const debut = lignes.findIndex(l => /(^|\s)(error|erreur)\s*:/i.test(l));
  if (debut < 0) return null;
  // On garde ce qui SUIT la ligne d'erreur jusqu'au diagnostic suivant : c'est
  // l'extrait de source et le curseur `^`, qui montrent l'endroit exact.
  let fin = debut + 1;
  while (fin < lignes.length && !DIAGNOSTIC.test(lignes[fin])) fin++;
  return lignes.slice(debut, fin).join("\n").replace(/\s+$/, "");
}

function sortieCompilateur(gcc) {
  const bloc = noeud("div", "gcc");
  const premiere = premiereErreur(gcc);
  if (!premiere) return block(gcc || "");
  bloc.append(block(premiere));
  // TOUT EST TOUJOURS LÀ, juste replié : cacher la suite ferait douter de ce
  // qu'on ne montre pas, et certaines erreurs ne se comprennent qu'en chaîne.
  const reste = document.createElement("details");
  reste.className = "case";
  const tete = document.createElement("summary");
  tete.textContent = "Voir toute la sortie du compilateur";
  reste.append(tete, block(gcc || ""));
  bloc.append(reste);
  return bloc;
}

// DEUX LECTURES DU MÊME CONTENU, et c'est voulu.
//   `collections` porte l'ARBRE DU MENU : tous les exercices, ouverts ou non,
//     avec leur cadenas et leur date. Montrer n'est pas donner -- la v1 faisait
//     disparaître ce qui n'était pas ouvert, ce qui ressemblait à une panne la
//     veille du cours.
//   `catalogue` ne porte que les exercices OUVERTS, dans la forme que « Mes
//     exercices », l'export et les progrès lisent déjà. Un exercice verrouillé
//     n'a rien à faire dans un décompte de progression ni dans un main.c de
//     remise, et les garder séparés évite d'ajouter un filtre dans trois
//     modules qui l'oublieraient chacun à leur tour.
let catalogue = [];
let collections = [];
// L'IDENTIFIANT CHOISI DANS LE MENU, et la seule source de cette vérité depuis
// que les deux <select> ont disparu. `currentId` reste autre chose : ce que
// l'ÉDITEUR tient vraiment, posé par setupFiles une fois le remplissage revenu.
let selection = "";
// L'exercice d'un lien profond qu'on n'a pas pu ouvrir : sa collection est
// dépliée quand même, pour qu'on voie le cadenas et la date plutôt que rien.
let vedette = "";
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

// L'IDENTIFIANT DE POSTE, pour que le quota anonyme ne soit pas celui de toute
// la salle : aux premiers labos, 27 postes sortent par une seule IP NATée. Il
// est dans `localStorage` et PAS dans `sessionStorage` comme celui de /live --
// deux onglets sont bien deux fenêtres ouvertes, mais un seul étudiant. Il ne
// prouve rien et ne voyage que vers /submit.
function posteId() {
  try {
    let v = localStorage.getItem("ctester.poste");
    if (!v) {
      v = (typeof crypto !== "undefined" && crypto.randomUUID)
        ? crypto.randomUUID()
        : String(Math.random()).slice(2);
      localStorage.setItem("ctester.poste", v);
    }
    return v;
  } catch (e) { return ""; }
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
  $("mesprogres").hidden = !on;
  // DEUX CONDITIONS, ET LES DEUX VIENNENT DU SERVEUR : être connecté, et un
  // déploiement qui a au moins un modérateur configuré (`oidc.forum`). Sans
  // l'une des deux le bouton n'existe pas, donc `forum.js` n'est jamais
  // demandé -- l'anonyme n'en télécharge rien, et un déploiement sans
  // modérateur configuré n'ouvre pas un canal que personne ne relit.
  $("discussions").hidden = !on || !(oidc && oidc.forum);
  // MÊME CONDITION QUE « Discussions » : le nom et le numéro de groupe ne
  // servent que là, et le formulaire vit dans cette vue.
  $("identite").hidden = !on || !(oidc && oidc.forum);
  $("moi").hidden = !on;
  $("moi").textContent = on ? "connecté" : "";
  // Le menu ne s'ouvre que sur un compte : « Se connecter » reste dehors,
  // parce qu'enterrer l'entrée dans un menu, c'est la faire disparaître.
  $("menucompte").hidden = !on;
}

// UNE SEULE VUE À LA FOIS, ET L'ARBITRAGE EST ICI. « Mes exercices » et
// « Mes progrès » vivent dans deux modules chargés séparément : si chacun
// masquait l'autre de son côté, ouvrir le second par-dessus le premier
// laisserait les deux moitiés à l'écran, ou aucune.
let vueCourante = "";

function afficherVue(nom) {
  // "" (l'exercice) | "progres" | "forum" | "moderation"
  // « Mes exercices » a fusionné dans « Mes progrès » : deux destinations
  // répondaient à « où j'en suis », avec deux comptes des mêmes exercices.
  vueCourante = nom;
  $("vueprogres").hidden = nom !== "progres";
  $("vueforum").hidden = nom !== "forum";
  $("vuemoderation").hidden = nom !== "moderation";
  $("travail").hidden = nom !== "";
  $("mesprogres").textContent =
    nom === "progres" ? "Retour à l'exercice" : "Mes progrès";
  $("discussions").textContent =
    nom === "forum" ? "Retour à l'exercice" : "Discussions";
}

// LE STATUT D'UN EXERCICE, AU NOYAU. Il ne vivait que dans « Mes exercices » :
// ni le menu du catalogue ni le poste de travail ne disaient « déjà validé »,
// alors que la donnée était déjà chargée. Savoir ce qu'on a fait ne devrait pas
// demander de changer d'écran.
//
// POUSSÉ PAR `compte.js`, jamais tiré : le sens reste unique, et l'anonyme --
// qui n'a pas de statuts -- ne déclenche rien.
let statuts = {};

function poserStatuts(carte) {
  statuts = carte || {};
  dessinerMenu();
  dessinerBande();
}

const STATUT_MARQUE = { valide: "✓", essaye: "•" };
const STATUT_MOT = { valide: "validé", essaye: "essayé" };

const current = () => catalogue.find(t => t.id === selection) || null;

// CE QUE LE FORMAT DE REMISE SAIT FAIRE, ET RIEN D'AUTRE. Le `main.c` d'un seul
// tenant repose sur `#define exercice N` pour choisir LEQUEL des `main()` est
// compilé : ça n'a de sens que pour les exercices « io », qui sont des
// programmes complets. Un exercice « unity » est un module SANS `main()`, un
// quiz n'a pas de code du tout, et proposer le bouton là promettrait un fichier
// qui ne compile pas.
//
// DEUX EXERCICES AU MINIMUM, parce qu'un fichier qui cumule un seul exercice ne
// cumule rien : l'étudiant a déjà ce code sous les yeux dans l'éditeur.
//
// LA RÈGLE EST ICI, DANS LE NOYAU, ET PAS DANS `exporter.js` : c'est elle qui
// décide si le bouton existe, et il faut le savoir AVANT d'aller chercher le
// module. Un second exemplaire dans le module dériverait du premier en silence.
const EXPORT_MINIMUM = 2;
const exercicesExportables = (groupe) =>
  catalogue.filter(t => t.group === groupe && t.mode === "io");
const groupeExportable = (groupe) =>
  exercicesExportables(groupe).length >= EXPORT_MINIMUM;

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

// CE QU'UN CADENAS DIT, et il doit dire une date : « pas encore ouvert » sans
// « ouvre le 18 septembre » envoie l'étudiant écrire un courriel.
function verrou(entry) {
  if (!entry || entry.access === "available") return "";
  if (entry.access === "archived") return "archivé";
  const quand = new Date(entry.available_from || "");
  return isNaN(quand.getTime())
    ? "à venir"
    : "ouvre le " + quand.toLocaleDateString(undefined,
                                             { day: "numeric", month: "long" });
}

// LA FORME QUE LE RESTE DE LA PAGE LIT. « Mes exercices », « Mes progrès » et
// l'export ont besoin d'une liste plate {id, mode, label, short, group, files,
// learning} ; le catalogue, lui, est un arbre. Une seule fonction traduit, et
// elle garde en plus l'accès et la date, qui n'existent qu'ici.
function entree(ex, groupe) {
  const learning = {};
  if (Array.isArray(ex.skills) && ex.skills.length) learning.skills = ex.skills;
  if (Array.isArray(ex.contexts) && ex.contexts.length) learning.context = ex.contexts[0];
  if (ex.difficulty) learning.difficulty = ex.difficulty;
  // `label` QUALIFIÉ, `short` NU. « Mes exercices » montre déjà la collection
  // dans sa propre colonne ; « Mes progrès » et l'export, eux, n'ont que cette
  // chaîne -- et « ex.1 » tout seul désigne un exercice dans chacun des dix TP.
  return {
    id: ex.id, mode: ex.mode, short: ex.title, group: groupe,
    label: groupe ? groupe.replace(/\s+/g, "") + " : " + ex.title : ex.title,
    files: (ex.files || []).map(f => ({ name: f.name })),
    learning: learning,
    access: ex.access,
    available_from: (ex.release || {}).available_from || "",
  };
}

function normaliser(catalog) {
  const par = new Map();
  for (const ex of catalog.exercises || []) {
    if (ex && typeof ex.id === "string") par.set(ex.id, ex);
  }
  const arbre = [];
  const classes = new Set();
  for (const col of catalog.collections || []) {
    const items = (col.items || []).filter(id => par.has(id));
    if (!items.length) continue;
    const titre = String(col.title || col.id || "");
    for (const id of items) classes.add(id);
    arbre.push({ titre: titre, access: col.access,
                 available_from: (col.release || {}).available_from || "",
                 items: items.map(id => entree(par.get(id), titre)) });
  }
  // UN EXERCICE PEUT N'ÊTRE DANS AUCUNE COLLECTION (invariant 3 du plan). Le
  // publier doit suffire à le rendre atteignable, sinon l'oubli d'une ligne de
  // collection le ferait disparaître sans que rien ne le signale.
  const orphelins = [...par.keys()].filter(id => !classes.has(id));
  if (orphelins.length) {
    arbre.push({ titre: "Autres", access: "available", available_from: "",
                 items: orphelins.map(id => entree(par.get(id), "Autres")) });
  }
  collections = arbre;
  // UNIQUE, ET DANS L'ORDRE DES COLLECTIONS. Un exercice partagé par deux
  // collections s'affiche deux fois dans le menu -- c'est le but d'un parcours
  // transversal -- mais ne compte qu'une fois dans une progression et ne
  // s'exporte qu'une fois dans un main.c.
  const vus = new Set();
  catalogue = [];
  for (const col of arbre) {
    for (const ex of col.items) {
      if (ex.access !== "available" || vus.has(ex.id)) continue;
      vus.add(ex.id);
      catalogue.push(ex);
    }
  }
}

function ligneMenu(ex) {
  const ligne = document.createElement("button");
  ligne.type = "button";
  ligne.className = ex.id === selection ? "exline on" : "exline";
  ligne.dataset.id = ex.id;
  const nom = document.createElement("span");
  nom.className = "titre";
  nom.textContent = ex.short;
  ligne.append(nom);
  // LE STATUT, LA OU ON CHOISIT. Il ne vivait que dans « Mes exercices » : on
  // ne pouvait pas savoir ce qu'on avait deja valide sans changer d'ecran.
  const fait = statuts[ex.id];
  if (fait) {
    const marque = noeud("span", "etat " + fait,
                         (STATUT_MARQUE[fait] || "") + " " + (STATUT_MOT[fait] || fait));
    ligne.append(marque);
  }
  const note = verrou(ex);
  if (note) {
    // `aria-disabled` ET PAS `disabled`. Un bouton `disabled` sort de l'ordre
    // de tabulation : les dates d'ouverture n'existaient que pour la souris,
    // alors qu'elles sont toute la raison de laisser l'exercice affiché. Il
    // reste donc atteignable, annoncé indisponible, et sans écouteur de clic.
    ligne.setAttribute("aria-disabled", "true");
    ligne.className += " verrouille";
    const marque = document.createElement("span");
    marque.className = "cadenas";
    marque.textContent = "🔒 " + note;
    ligne.append(marque);
  } else {
    ligne.addEventListener("click", () => {
      $("menuex").open = false;
      fillExercises(ex.id);
    });
  }
  return ligne;
}

// UN <details> PAR COLLECTION, DANS LE <details> DU MENU. Le navigateur sait
// replier : pas d'accordéon en JS, pas d'état d'ouverture à tenir ailleurs.
// LA BANDE DU LABORATOIRE : les exercices OUVERTS de la collection affichée,
// avec leur statut. C'est la navigation qu'un étudiant fait vingt fois par
// séance -- passer de l'ex.2 à l'ex.3 -- et elle demandait d'ouvrir un menu
// qui couvre l'écran pour une cible située à un cran.
//
// ELLE NE REMPLACE PAS LE MENU : celui-ci reste la bascule entre collections,
// qui est rare, et il garde les exercices verrouillés avec leur date. Deux
// portées, deux mécanismes -- c'est la répartition global/local habituelle.
//
// MOINS DE DEUX EXERCICES, PAS DE BANDE : une bande d'un seul élément
// n'aiderait à rien et prendrait une ligne à la consigne.
// UNE ÉTIQUETTE COURTE, PARCE QU'IL Y EN A ONZE. `short` n'est pas nu malgré
// son nom : le contenu écrit « TP5 : ex.1 celcius_to_fahrenheit » dans le titre
// lui-même. Onze puces de trente caractères remplissent trois lignes et volent
// à la consigne la place qu'elle réclame -- alors que le nom complet est déjà
// affiché juste au-dessus, dans `#now`.
//
// On garde le numéro, qui est la façon dont l'énoncé du cours les désigne.
function etiquetteBande(ex) {
  const nu = (ex.short || "").replace(/^[^:]*:\s*/, "");
  const numero = nu.match(/^ex\.?\s*(\d+)/i);
  if (numero) return "ex." + numero[1];
  // LES POINTS DE SUSPENSION SONT LOAD-BEARING : « convertir_en_radia »
  // coupé net se lit comme un bug d'affichage, pas comme un raccourci.
  return nu.length > 20 ? nu.slice(0, 19) + "…" : nu;
}

function dessinerBande() {
  const boite = $("bandelabo");
  boite.innerHTML = "";
  const tp = current();
  const voisins = tp ? catalogue.filter(t => t.group === tp.group) : [];
  boite.hidden = voisins.length < 2;
  if (boite.hidden) return;
  for (const ex of voisins) {
    const courant = ex.id === selection;
    const statut = statuts[ex.id] || "";
    const puce = noeud("button", "puce" + (courant ? " on" : "")
                                 + (statut ? " " + statut : ""),
                       etiquetteBande(ex));
    puce.type = "button";
    // LE NOM ENTIER RESTE ATTEIGNABLE : au survol pour la souris, et dans le
    // texte hors écran pour un lecteur -- la puce ne dit que « ex.3 ».
    puce.setAttribute("title", ex.short);
    puce.append(noeud("span", "horsecran", " — " + ex.short));
    // `aria-current` PLUTÔT QU'UNE COULEUR : c'est ce qui dit « vous êtes ici »
    // à un lecteur d'écran, et la classe `on` ne dit rien à personne d'autre.
    if (courant) puce.setAttribute("aria-current", "true");
    if (statut) {
      // LE MOT EN PLUS DU SIGNE. Une coche verte seule disparaît en noir et
      // blanc, sous un daltonisme, et ne se lit pas à voix haute.
      puce.append(noeud("i", "marque", STATUT_MARQUE[statut] || ""));
      puce.setAttribute("title", ex.short + " — " + (STATUT_MOT[statut] || statut));
      puce.append(noeud("span", "horsecran", " — " + (STATUT_MOT[statut] || statut)));
    }
    puce.addEventListener("click", () => {
      if (ex.id !== selection) fillExercises(ex.id);
    });
    boite.append(puce);
  }
}

function dessinerMenu() {
  const boite = $("exliste");
  boite.innerHTML = "";
  for (const col of collections) {
    const bloc = document.createElement("details");
    bloc.className = "col";
    // REPLIÉ SAUF CELLE OÙ L'ON TRAVAILLE : à onze collections et soixante-treize
    // exercices, tout déplier revient à n'avoir rien rangé.
    bloc.open = col.items.some(ex => ex.id === selection || ex.id === vedette);
    const tete = document.createElement("summary");
    const titre = document.createElement("span");
    titre.textContent = col.titre;
    tete.append(titre);
    const note = verrou(col);
    if (note) {
      const marque = document.createElement("span");
      marque.className = "cadenas";
      marque.textContent = "🔒 " + note;
      tete.append(marque);
    }
    bloc.append(tete);
    for (const ex of col.items) bloc.append(ligneMenu(ex));
    boite.append(bloc);
  }
  const ouvert = current();
  $("excourant").textContent = ouvert ? ouvert.short : "Exercices";
}

// `/catalog.json` EST LA SEULE SOURCE depuis la phase 8. Le repli `tps.json`
// existait pour les pages restées dans le cache d'un étudiant pendant la
// bascule ; cette fenêtre est refermée, et le rollback est redevenu ce qu'il
// est côté serveur : un pointeur `current.json` à réécrire.
(async () => {
  let publie = null;
  try {
    const r = await fetch(API("catalog.json"));
    if (r.ok) publie = await r.json();
  } catch (e) { /* réseau, ou rien de publié : le message ci-dessous tranche */ }
  if (!publie || !Array.isArray(publie.exercises)) {
    systeme("La liste des exercices n'a pas pu être chargée. Recharge la "
          + "page ; si ça recommence, préviens ton enseignant.", true);
    return;
  }
  normaliser(publie);
  if (!collections.length) {
    systeme("Aucun exercice n'est publié pour l'instant.");
    return;
  }
  // UN LIEN PROFOND VERS UN EXERCICE VERROUILLÉ N'OUVRE PAS L'EXERCICE : il
  // ouvre le menu sur son cadenas et sa date. Le partager en avance ne
  // contourne donc rien, et ne ressemble pas non plus à un lien mort.
  const vise = new URLSearchParams(location.search).get("tp") || "";
  const ouvrable = catalogue.some(t => t.id === vise);
  if (vise && !ouvrable
      && collections.some(c => c.items.some(e => e.id === vise))) {
    vedette = vise;
    $("menuex").open = true;
  }
  fillExercises(ouvrable ? vise : (catalogue[0] || {}).id || "");
  // TOUT EST PUBLIÉ, RIEN N'EST ENCORE OUVERT : c'est l'état normal d'un début
  // de session, pas une panne, et le menu porte les dates -- autant l'ouvrir.
  if (!catalogue.length) {
    $("menuex").open = true;
    verdict({ cls: "idle", titre: "Aucun exercice n'est encore ouvert.",
              texte: "Le menu « Exercices » donne la date d'ouverture de chacun." });
  }
})();

function aller(pas) {
  const i = catalogue.findIndex(t => t.id === selection);
  const cible = catalogue[i + pas];
  if (!cible) return;
  fillExercises(cible.id);
}
$("prev").addEventListener("click", () => aller(-1));
$("next").addEventListener("click", () => aller(1));

// LE NOM RESTE, le menu a changé : `compte.js` et `progres.js` l'appellent pour
// ouvrir un exercice depuis leur liste, et le renommer ferait trois modules à
// éditer pour zéro comportement de plus.
function fillExercises(preselect) {
  if (preselect) selection = preselect;
  dessinerMenu();
  dessinerBande();
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

// L'ÉTAT DE SAUVEGARDE, ET IL EST PERMANENT. Il restait VIDE tant que
// l'étudiant n'avait pas tapé pendant une seconde et demie : celui qui vient
// d'ouvrir un exercice, ou qui vient de coller son code sans le retoucher,
// n'avait aucun moyen de savoir si son travail était à l'abri.
//
// ET IL DIT OÙ, pas seulement quand. « enregistré à 14:32 » ne répond pas à la
// vraie question, qui est « est-ce que je retrouve ça sur l'autre poste ? ».
function showDraftStatus(text, failed) {
  $("sauvegarde").textContent = text;
  $("sauvegarde").className = failed ? "rate" : "";
}

// L'EXPORT GARDE SON PROPRE EMPLACEMENT, dans la barre d'actions, à côté de son
// bouton. Les deux messages partageaient un slot et s'effaçaient l'un l'autre :
// « main.c exporté » remplaçait « brouillon NON enregistré », qui était le seul
// avertissement de perte de données de toute la page.
function annoncerExport(texte, rate) {
  $("brouillon").textContent = texte;
  $("brouillon").className = rate ? "rate" : "";
}

const twoDigits = (n) => String(n).padStart(2, "0");
const maintenant = () => {
  const t = new Date();
  return twoDigits(t.getHours()) + ":" + twoDigits(t.getMinutes());
};

// L'ÉCRITURE SEULE, partagée avec le quiz : lui aussi a un brouillon, de la
// même forme `{clé: texte}`, et il n'a ni onglet ni gabarit à traverser.
function persistDrafts() {
  try {
    localStorage.setItem(DRAFTS_KEY, JSON.stringify(drafts));
  } catch (e) {
    showDraftStatus("NON enregistré — garde une copie de ton code", true);
    return false;
  }
  // « SUR CET APPAREIL » EST LA MOITIÉ QUI MANQUAIT. Sans compte, le travail ne
  // suit pas d'un poste à l'autre, et c'est exactement ce qu'un étudiant du
  // labo doit savoir AVANT de rentrer chez lui -- pas en le découvrant.
  // `syncDraft` remplacera ce texte par « sur ton compte » si la copie passe.
  showDraftStatus("enregistré sur cet appareil · " + maintenant());
  $("purger").hidden = false;
  return true;
}

function saveDraft() {
  if (currentId === null || actif === null) return;
  sources[actif] = $("code").value;
  drafts[currentId] = sources;
  if (!persistDrafts()) return;
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
  const i = catalogue.findIndex(t => t.id === selection);
  $("prev").disabled = i <= 0;
  $("next").disabled = i < 0 || i >= catalogue.length - 1;
  $("editor").hidden = quiz;
  $("filewrap").hidden = quiz;
  $("quizwrap").hidden = !quiz;
  // L'EXPORT SUIT LE TP AFFICHÉ, PAS L'EXERCICE : le fichier de remise couvre
  // tout le laboratoire. Le bouton n'existe donc que sur un TP dont le format
  // sait faire quelque chose, et le module ne descend qu'au clic.
  $("exporttp").hidden = !groupeExportable(tp && tp.group);
  // Hors quiz il n'y a qu'un bouton et il est primaire. En quiz, l'action
  // courante est l'exercice affiche : tester les 40 questions reste possible,
  // mais cesse d'etre ce sur quoi on tombe par defaut.
  $("goex").hidden = !quiz;
  // LE LIBELLÉ DE REPOS PASSE PAR `occupe()`, qui est aussi celui qui le
  // remplace par « Test en cours… ». Deux endroits qui écrivent le même bouton
  // finiraient par se contredire -- typiquement, changer d'exercice pendant un
  // test remettrait « Tester » sur un bouton encore occupé.
  goSecondaire = quiz;
  libelleGo = quiz ? "Tester tout le quiz" : "Tester";
  occupe(occupation);

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
  repos();
  preparer(tp, quiz, ++loadToken);
}

// TROIS ÉTATS, ET PAS DEUX. « Pas de consigne en ligne » et « la consigne n'est
// pas arrivée » s'affichaient à l'identique : l'étudiant croyait à une
// propriété de l'exercice, donc il ne réessayait jamais -- alors qu'un
// rechargement aurait suffi. `chargerDetail` ne met d'ailleurs pas ce repli en
// cache, exprès, pour que réessayer marche.
function afficherConsigne(texte, panne) {
  const boite = $("consignetexte");
  if (texte === null) {
    boite.textContent = "Chargement…";
    boite.className = "vide";
    return;
  }
  boite.textContent = panne
    ? "La consigne n'a pas pu être chargée. Tu peux quand même écrire et "
      + "tester : les noms de fichiers attendus, eux, sont déjà là."
    : texte
      || "Cet exercice n'a pas de consigne en ligne. Reporte-toi à l'énoncé du "
       + "TP sur Moodle : les noms de fichiers et de fonctions attendus y sont.";
  boite.className = texte && !panne ? "" : "vide";
  if (!panne) return;
  // UN BOUTON, PAS UNE INVITATION À RECHARGER LA PAGE : recharger fait perdre
  // le code non encore enregistré de celui qui vient de coller son fichier.
  const reessayer = noeud("button", "nav", "Réessayer");
  reessayer.type = "button";
  reessayer.addEventListener("click", () => {
    const tp = current();
    if (!tp) return;
    afficherConsigne(null);
    preparer(tp, tp.mode === "quiz", ++loadToken);
  });
  boite.append(reessayer);
}

const details = {};

// LE DÉTAIL D'UN EXERCICE, chargé quand on l'ouvre. La consigne et les gabarits
// feraient les trois quarts du catalogue pour 73 exercices dont un seul est
// affiché ; `/catalog.json` ne porte qu'un menu. Gardé en mémoire : revenir sur
// un exercice déjà vu ne redemande rien.
async function chargerDetail(id) {
  if (details[id]) return details[id];
  try {
    const r = await fetch(API("tp/" + id + ".json"));
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
    return { statement: "", files: [], panne: true };
  }
}

async function preparer(tp, quiz, thisLoad) {
  if (!tp) { afficherConsigne(""); return; }
  const detail = await chargerDetail(tp.id);
  if (thisLoad !== loadToken) return;
  afficherConsigne(detail.statement, detail.panne);
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
    systeme("La connexion n'a pas pu démarrer : " + e.message
          + ". Tu peux continuer sans compte : tout fonctionne pareil.", true);
  }
});
// Un <details> ne se referme pas tout seul quand on clique dedans.
$("menucompte").addEventListener("click", (e) => {
  if (e.target && e.target.tagName === "BUTTON") $("menucompte").open = false;
});
// L'EXPORT MARCHE SANS COMPTE, et c'est voulu : les brouillons de cet appareil
// suffisent à assembler le fichier. Le compte n'ajoute qu'une chose -- aller
// chercher les exercices travaillés sur un AUTRE poste -- et `exporter.js` s'en
// occupe tout seul s'il y a un jeton. Le message part sur la ligne du
// brouillon : c'est celle qui est juste à côté du bouton.
$("exporttp").addEventListener("click", async () => {
  if (!await activerModule("exporter", "l'export du TP")) return;
  const tp = current();
  if (tp) await ctester.exporter.exporter(tp.group, annoncerExport);
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
// Un raccourci vers le formulaire de la vue Discussions, pas un second
// formulaire : c'est là qu'on cherche son nom quand on ne pense pas au forum.
$("identite").addEventListener("click", async () => {
  if (!await activerModule("forum", "les discussions")) return;
  await ctester.forum.ouvrirIdentite();
});
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
fetch(API("oidc.json")).then(r => r.json()).then(async (config) => {
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
  // `systeme` ET PAS `show` : le canal du service. Les deux seuls appels des
  // modules -- une connexion qui échoue, une suppression de compte confirmée --
  // parlent du service, jamais du code de l'étudiant. Le verdict, lui, n'a
  // aucune raison d'être écrit depuis un module.
  systeme: systeme,
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
  // Le chargeur de MODULES, celui qui dit à l'étudiant ce qui n'est pas
  // arrivé. Exposé parce que « Mes exercices » (compte.js) offre lui aussi
  // l'export : sans lui, compte.js réécrirait `charger()` plus ses deux
  // messages d'erreur, et la moitié qui manquerait serait toujours ceux-là.
  activerModule: activerModule,
  // Le thème : le noyau le pose (le bouton est dans la barre, et il
  // existe pour l'anonyme), `compte.js` le synchronise avec le compte.
  appliquerTheme: appliquerTheme,
  retenirTheme: retenirTheme,
  themeCourant: themeCourant,
  catalogue: () => catalogue,
  token: () => token,
  oidc: () => oidc,
  setToken: setToken,
  refreshAccount: refreshAccount,
  switchMode: switchMode,
  fillExercises: fillExercises,
  showDraftStatus: showDraftStatus,
  maintenant: maintenant,
  poserStatuts: poserStatuts,
  dernierVerdict: () => dernierVerdict,
  // LE BROUILLON DU QUIZ, local seulement : `/brouillon` valide les noms de
  // fichiers déclarés par l'exercice, et un identifiant de question n'en est
  // pas un. Même magasin, même bouton « Effacer mes brouillons ».
  brouillon: (id) => drafts[id] || null,
  enregistrerBrouillon: (id, valeurs) => {
    if (!id) return;
    drafts[id] = valeurs;
    persistDrafts();
  },
  exerciceOuvert: () => currentId,
  // CE QUE LE MENU MONTRE, quand `currentId` n'est pas encore posé : le
  // remplissage de l'éditeur passe par le réseau, et le forum sait s'ouvrir
  // avant qu'il ne soit revenu.
  exerciceChoisi: () => selection,
  // L'EXPORT, VU DU NOYAU : qui a le droit à un bouton (`groupeExportable`) et
  // ce qu'il faut assembler (`exercicesExportables`). `exporter.js` et
  // `compte.js` lisent tous les deux ici -- une seule règle, un seul endroit.
  exercicesExportables: exercicesExportables,
  groupeExportable: groupeExportable,
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
  // L'ÉTAT DE DÉPART SE DIT, LUI AUSSI. « Brouillon retrouvé » répond à la
  // tâche « je reviens après une pause » AVANT qu'on ait à chercher si le code
  // est bien celui qu'on avait laissé ; et sur un exercice neuf, annoncer que
  // l'enregistrement est automatique évite de se demander où est le bouton
  // « Enregistrer » qui n'existe pas.
  showDraftStatus(sources ? "brouillon retrouvé" : "enregistrement automatique");
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
    onglet.setAttribute("aria-controls", "edwrap");
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
  // LE CHAMP N'AVAIT AUCUN NOM ACCESSIBLE : `#edtitle` est un <span>, pas un
  // <label>. Un lecteur d'écran annonçait « zone de texte », sans dire lequel
  // des deux fichiers du module on était en train d'éditer.
  $("code").setAttribute("aria-label", "Code de " + nom);
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

// L'IMPORT PERDAIT LE FICHIER IMPORTÉ. `saveDraft` n'était appelé que sur
// l'événement `input`, et `input` NE SE DÉCLENCHE PAS quand un script écrit
// dans un `<textarea>` : le fichier n'existait que dans le DOM, et un
// rechargement -- ou un onglet fermé par erreur -- l'emportait sans un mot.
// C'est la perte de code la plus facile à provoquer de toute la page.
$("file").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  const texte = await f.text();
  // LE FICHIER VA DANS L'ONGLET QUI PORTE SON NOM, quand il y en a un. Importer
  // `calendrier.c` par-dessus `calendrier.h` parce que c'est l'onglet ouvert
  // est un écrasement silencieux, au moment précis où l'étudiant regarde
  // ailleurs -- il vient de choisir un fichier dans une boîte système.
  const cible = Object.prototype.hasOwnProperty.call(sources, f.name)
    ? f.name : actif;
  if (cible !== actif) activer(cible);
  // ON DEMANDE AVANT D'ÉCRASER DU TRAVAIL : il n'y a pas d'annulation dans cet
  // éditeur, le code remplacé est parti pour de bon. Un onglet vide, ou resté
  // au gabarit, ne vaut pas une question.
  const remplace = ($("code").value || "").trim();
  if (remplace && typeof confirm === "function"
      && !confirm("Remplacer le contenu de « " + cible + " » par « " + f.name
                  + " » ? Ce qui est écrit dans cet onglet sera perdu.")) {
    e.target.value = "";
    return;
  }
  $("code").value = texte;
  paint();
  clearTimeout(saveTimer);
  saveDraft();
  // REMETTRE LE CHAMP À ZÉRO : sans ça, réimporter le MÊME fichier après l'avoir
  // corrigé sur son disque ne déclenche pas `change`, et le bouton semble mort.
  e.target.value = "";
});

// LA CLASSE D'ERREUR, tirée de la raison écrite par le serveur. Un résumé qui
// reprenait la phrase entière (« Cas 1 : ta sortie contient inf ou nan :
// division par zéro, ou une variable utilisée alors que… ») ne se survolait
// pas : avec trois cas repliés, on ne pouvait pas voir d'un coup d'oeil si le
// programme avait planté ou simplement mal calculé.
function classeDuCas(raison) {
  const r = raison || "";
  if (/n'a pas terminé|interrompu/.test(r)) return "n'a pas fini";
  if (/débordé de la mémoire/.test(r)) return "débordement mémoire";
  if (/terminé anormalement/.test(r)) return "a planté";
  return "mauvaise sortie";
}

// LE CONTRAT DE CORRECTION, ÉCRIT. Le juge est BEAUCOUP plus permissif que ce
// que l'étudiant croit -- `match_subsequence` accepte n'importe quel texte
// autour des valeurs attendues -- et personne ne le lui disait. Il passait donc
// du temps à deviner un format de sortie qui n'a jamais été imposé.
//
// Ça ne révèle aucune réponse : ça dit COMMENT on compare, pas À QUOI.
// L'EXEMPLE EST TOUJOURS LE MÊME, sur tous les exercices, et il porte une
// valeur qui n'est celle d'aucun d'eux : un exemple qui varierait avec
// l'exercice se lirait comme un indice sur la réponse attendue.
const CONTRAT = "On lit les NOMBRES de ta sortie, dans l'ordre ; le texte autour "
              + "est libre. Par exemple, « Aire = 42 cm2 » et « 42 » sont lus de "
              + "la même façon.";

// Les ENTRÉES telles que le programme les reçoit, une par ligne. « stdin » ne
// veut rien dire pour un débutant ; « ton programme reçoit 12 puis 7 » décrit
// exactement ce que font ses deux scanf.
function entreesDuCas(stdin) {
  return (stdin || "").split("\n").map(v => v.trim()).filter(v => v !== "");
}

function ligneCas(etiquette, valeur, classe) {
  const bloc = noeud("div", "champ" + (classe ? " " + classe : ""));
  bloc.append(noeud("span", "quoi", etiquette));
  bloc.append(noeud("pre", "valeur", valeur));
  return bloc;
}

function cases(items) {
  const box = document.createElement("div");
  for (const c of items) {
    const wrap = document.createElement("details");
    wrap.className = "case";
    wrap.open = !box.children.length;
    const classe = classeDuCas(c.reason);
    const why = document.createElement("summary");
    why.textContent = `Cas ${c.case} — ${classe}`;
    const corps = noeud("div", "corps");

    const recues = entreesDuCas(c.stdin);
    corps.append(ligneCas(
      recues.length === 1 ? "Ton programme reçoit :"
                          : "Ton programme reçoit, dans cet ordre :",
      recues.length ? recues.join("   puis   ")
                    : "rien — ce cas ne lui fournit aucune entrée"));

    corps.append(ligneCas("Ce qu'il a affiché :", c.stdout || "(rien)"));

    // LES NOMBRES QUE LE JUGE A LUS, REMONTÉS AU MÊME RANG que la sortie. C'est
    // l'information la plus actionnable du bloc -- elle démonte la boîte noire
    // de l'appariement -- et elle vivait en gris de 12 px sous le reste.
    if (c.nombres) {
      corps.append(ligneCas(
        "Les nombres que le juge y a lus :",
        c.nombres.length ? c.nombres.join(", ") : "aucun"));
    }

    if (c.stderr) corps.append(ligneCas("Sa sortie d'erreur :", c.stderr));

    // La raison du serveur, en toutes lettres : c'est elle qui porte les
    // diagnostics vraiment utiles (« inf ou nan », « aucun nombre »).
    corps.append(noeud("p", "pourquoi", c.reason));
    // Le contrat n'a de sens que pour une comparaison de VALEURS : un programme
    // qui a planté, ou un cas qui cherche un mot, ne se corrige pas en
    // reformatant sa sortie.
    if (classe === "mauvaise sortie" && !/mot attendu|mentionne/.test(c.reason || "")) {
      corps.append(noeud("p", "contrat", CONTRAT));
    }
    wrap.append(why, corps);
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

// L'EXERCICE OUVERT SUIVANT, pour l'action qui suit une réussite. `catalogue`
// ne porte que les exercices ouverts : il n'y a donc pas de cadenas à éviter.
function suivantOuvrable() {
  const i = catalogue.findIndex(t => t.id === selection);
  return i >= 0 ? catalogue[i + 1] || null : null;
}

// CE QU'ON PROPOSE APRÈS UNE RÉUSSITE COMPLÈTE. Un bouton, pas une phrase :
// c'est le seul moment de la boucle où l'étudiant n'a plus rien à corriger, et
// la page ne lui offrait rien.
function apresReussite() {
  const apres = suivantOuvrable();
  if (!apres) {
    return { suite: "C'est le dernier exercice ouvert pour l'instant." };
  }
  return {
    suite: "Tu peux passer à la suite.",
    bouton: { libelle: "Ouvrir « " + apres.short + " »",
              faire: () => fillExercises(apres.id) },
  };
}

// CE QU'ON DIT APRÈS UN ÉCHEC DE TESTS, par mode. Le juge a exécuté le
// programme : ce qui reste à faire n'est plus de le faire tourner, c'est de
// lire ce qu'il a produit.
const APRES_ECHEC = {
  io: "Ouvre le cas qui échoue : il montre ce que ton programme a reçu et ce "
    + "qu'il a affiché.",
  unity: "Le nom de chaque vérification décrit le cas qu'elle teste.",
  quiz: "Corrige les réponses ci-dessus, puis relance le test.",
};

// LES NOMS DE TESTS SONT ÉCRITS POUR L'ÉTUDIANT -- encore faut-il le lui dire.
// Une liste d'identifiants nus (`test_pop_pile_vide`) ne s'annonce pas comme du
// français ; et le silence sur ce qu'on ne montre pas se lit comme un manque
// d'information plutôt que comme une décision.
function testsRates(noms) {
  const bloc = noeud("div", "rates");
  bloc.append(noeud("p", "quoi", noms.length === 1
    ? "Cette vérification a échoué. Son nom décrit le cas qu'elle teste :"
    : "Ces vérifications ont échoué. Leur nom décrit le cas qu'elles testent :"));
  bloc.append(list(noms));
  bloc.append(noeud("p", "contrat",
    "Les valeurs attendues ne sont pas montrées : les trouver EST l'exercice."));
  return bloc;
}

function render(r, portee) {
  // UN VERDICT EFFACE LE BANDEAU SYSTÈME. Laisser « le serveur est injoignable »
  // au-dessus d'un résultat qui vient d'arriver dirait deux choses opposées.
  effacerSysteme();
  if (r.status !== "ok") {
    // UNE PANNE DU JUGE N'EST PAS UN VERDICT. `error` couvre deux choses très
    // différentes côté serveur : un programme étudiant qui plante (des étapes à
    // montrer) et une erreur interne (« Erreur interne du juge », « Le juge a
    // été interrompu »), qui ne parle pas du code et n'a rien à faire ici.
    if (r.status === "error" && /juge/.test(r.message || "")) {
      systeme(r.message + " Ton code est enregistré.", true);
      // ET ON REPART DU REPOS : sans ça, le verdict restait figé sur « Envoi… »
      // pendant que le bandeau annonçait une panne -- deux écrans qui disent
      // deux choses différentes au même moment.
      repos();
      return;
    }
    const etat = ETATS[r.status] || ETATS.error;
    verdict({
      cls: "bad",
      etapes: etat.etapes,
      titre: etat.titre,
      texte: r.message || "",
      detail: r.status === "compile_error" ? sortieCompilateur(r.gcc) : null,
      suite: etat.suite,
    });
  } else {
    const cadre = portee && r.kind === "quiz" ? " — " + portee.titre : "";
    if (portee && r.kind === "quiz") r = restreindre(r, portee);
    const all = r.passed === r.total;
    const title = `${r.passed} / ${r.total} ${UNITS[r.kind] || "réussis"}${cadre}`;
    const bar = r.total > 0 ? ticks(r.passed, r.total) : null;
    // LE PROGRAMME A COMPILÉ ET IL A TOURNÉ : les deux premières étapes sont
    // réussies par construction, on n'est ici que parce que le juge a pu noter.
    // DEUX ETAPES SEULEMENT quand le juge a note : le compte affiche juste
    // en dessous EST le resultat des tests, une troisieme case le redirait.
    const etapes = ["ok", "ok"];
    if (all) {
      const apres = apresReussite();
      verdict({ cls: "ok", etapes: etapes, compte: true, titre: title, bar: bar,
                suite: apres.suite, bouton: apres.bouton });
    } else if (r.kind === "quiz") {
      verdict({ cls: "bad", etapes: etapes, compte: true, titre: title, bar: bar,
                suite: APRES_ECHEC.quiz,
                detail: list(r.wrong.map(w => {
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
      })) });
    } else if (r.kind === "io") {
      verdict({ cls: "bad", etapes: etapes, compte: true, titre: title, bar: bar,
                detail: cases(r.cases), suite: APRES_ECHEC.io });
    } else {
      verdict({ cls: "bad", etapes: etapes, compte: true, titre: title, bar: bar,
                detail: r.failed.length ? testsRates(r.failed) : null,
                suite: APRES_ECHEC.unity });
    }
  }
  if (r.warnings) out.append(avertissements(r.warnings));
  amenerLeResultat();
}

// SUR PETIT ÉCRAN, LE RÉSULTAT EST SOUS L'ÉDITEUR ET HORS DE L'ÉCRAN : cliquer
// « Tester » n'y produisait visiblement RIEN. On l'y amène et on y pose le
// focus. Sur grand écran il est déjà dans la grille, à côté de l'éditeur, et
// voler le focus en pleine correction serait pire que le mal.
function amenerLeResultat() {
  const etroit = typeof matchMedia === "function"
              && matchMedia("(max-width: 900px)").matches;
  if (!etroit) return;
  if (out.scrollIntoView) out.scrollIntoView({ block: "start", behavior: "smooth" });
  if (out.focus) out.focus();
}

// PAS `disabled`, ET C'EST DÉLIBÉRÉ. Désactiver le bouton qui a le focus le
// fait tomber sur <body> : au clavier, il fallait re-tabuler toute la page
// après CHAQUE soumission. Et un bouton grisé sans un mot se lit « cassé »
// plutôt que « en cours ». Il reste donc focalisable, et il DIT ce qu'il fait.
//
// IL RESTE AUSSI CLIQUABLE, et ce n'est pas un oubli : un sondage qui n'aboutit
// jamais -- file bloquée, réseau qui tombe entre deux battements -- laissait
// l'étudiant devant un bouton mort, sans un mot et sans issue. Recliquer est
// une intention sans ambiguïté : le nouveau test REMPLACE l'ancien, dont le
// verdict ne l'intéresse plus. Le vrai garde-fou contre le martèlement est le
// quota du serveur (8 s connecté, 15 s sinon), et il est déjà là.
let occupation = false;
let libelleGo = "Tester";
let goSecondaire = false;

function occupe(oui, texte) {
  occupation = oui;
  const dire = texte || "Test en cours…";
  $("go").textContent = oui ? dire : libelleGo;
  $("goex").textContent = oui ? dire : "Tester l'exercice";
  for (const id of ["go", "goex"]) {
    // `aria-busy` seulement quand ça TRAVAILLE : pendant un compte à rebours de
    // quota, rien ne tourne, et l'annoncer occupé serait faux.
    $(id).setAttribute("aria-busy", oui && !texte ? "true" : "false");
  }
  $("go").className = (goSecondaire ? "secondaire" : "") + (oui ? " occupe" : "");
  $("goex").className = oui ? "occupe" : "";
}

// LE SONDAGE PÉRIMÉ SE TAIT. Sans ce jeton, le verdict d'un test abandonné
// écraserait celui du test qu'on vient de lancer -- et il arriverait EN
// DERNIER, donc c'est lui qu'on lirait. Même mécanique que `loadToken` pour le
// chargement d'un exercice, et pour la même raison.
let soumissionCourante = 0;

// --- Ne pas redemander ce qu'on vient de demander -------------------------
// Renvoyer un code identique coûte une place de file, un cooldown et une
// attente, pour un verdict qu'on tient déjà à l'écran. La page ne l'envoie donc
// pas : elle réaffiche.
//
// ELLE N'AFFIRME RIEN AU SERVEUR, et c'est la seule raison pour laquelle ce
// raccourci est permis ici. Un hachage envoyé dans la requête, lui, CHOISIRAIT
// quel verdict stocké on reçoit -- du code cassé plus le hachage d'une
// soumission réussie donnerait `passed == total`, que l'API transforme en
// « validé » et en XP. Décider de ne pas déranger le serveur ne demande aucune
// confiance ; lui dicter sa réponse en demanderait toute.
//
// `rejouer` VIENT DU SERVEUR : le worker le pose sur tout verdict qu'il refuse
// de mettre en cache lui-même -- timeout, panne du juge, et les exercices dont
// le programme est aléatoire, que la page n'a aucun moyen de reconnaître seule.
// La règle vit donc à un seul endroit.
//
// EN MÉMOIRE SEULEMENT : un rechargement de page refait juger, ce qui est le
// bon défaut. C'est un raccourci de session, pas un cache.
const dejaSoumis = {};    // exercice -> {cle, verdict}
let renvoiForce = null;   // la clé qu'un second clic doit renvoyer quand même
let enVol = null;         // {jeton, exercice, cle} de la soumission en cours

// L'ETA VIENT DU SERVEUR (`eta`, en secondes) : lui seul sait ce que chaque
// exercice coûte et ce qu'il y a devant. La page ne fait que le mettre en
// français. Une API plus ancienne, ou un `eta` à 0, ne rend rien plutôt que
// d'inventer un chiffre -- le rang seul reste affiché.
function attenteEstimee(secondes) {
  if (!(secondes > 0)) return "";
  if (secondes < 60) return ` (environ ${Math.ceil(secondes / 5) * 5} s)`;
  return ` (environ ${Math.ceil(secondes / 60)} min)`;
}

async function poll(id, tries, portee, jeton) {
  if (jeton !== soumissionCourante) return;
  const r = await fetch(API("r/" + id));
  if (jeton !== soumissionCourante) return;
  const body = await r.json().catch(() => ({state: "error"}));
  if (body.state === "done") {
    render(body, portee);
    // ON NE GARDE QUE CE QUE LE SERVEUR ACCEPTE DE GARDER LUI-MÊME.
    if (enVol && enVol.jeton === jeton && !body.rejouer
        && body.status !== "error") {
      dejaSoumis[enVol.exercice] = { cle: enVol.cle, verdict: body };
    }
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
    // PERDRE UN VERDICT EST UNE PANNE DE SERVICE, pas un jugement sur le code.
    systeme("Le résultat de ce test s'est perdu. Ton code est enregistré — "
          + "relance simplement le test.", true);
    occupe(false);
    return;
  }
  // « COMPILATION EN COURS » ÉTAIT FAUX LA MOITIÉ DU TEMPS : `running` couvre
  // la compilation, l'exécution ET les tests -- le worker ne rapporte pas de
  // sous-état. Annoncer une étape qu'on ne connaît pas forme précisément le
  // modèle mental erroné chez celui qui en a le moins.
  verdict({
    cls: "wait",
    titre: body.state === "running"
      ? "Test en cours…"
      : `En file d'attente — ${body.position}${body.position === 1 ? "er" : "e"}`
        + attenteEstimee(body.eta),
  });
  setTimeout(() => poll(id, tries - 1, portee, jeton), 2000);
}

// LE QUOTA N'EST PAS UN REFUS DU CODE. L'API renvoie déjà `retry_after` ; la
// page l'ignorait et affichait le message brut en rouge, à l'emplacement du
// verdict -- « mon code a été refusé ». On le met dans le canal du service, on
// décompte sur le bouton, et on rouvre tout seul : recliquer ne servait qu'à
// s'agacer.
let rebours = null;

function attendreQuota(secondes) {
  clearTimeout(rebours);
  let reste = Math.max(1, Math.round(secondes));
  (function tic() {
    if (reste <= 0) {
      occupe(false);
      effacerSysteme();
      return;
    }
    occupe(true, "Nouveau test dans " + reste + " s");
    systeme("Tu as lancé plusieurs tests coup sur coup. Le prochain part dans "
          + reste + " s — ton code est enregistré, tu peux continuer à l'écrire.");
    reste--;
    rebours = setTimeout(tic, 1000);
  })();
}

// `portee` : les identifiants de l'exercice affiche, ou null pour tout le TP.
async function soumettre(portee) {
  const tp = current();
  if (!tp) { systeme("Choisis un exercice dans le menu pour commencer."); return; }
  // ON N'ENVOIE PAS UNE SOUMISSION QU'ON SAIT REFUSÉE : le 403 du serveur dit
  // « clé de session invalide ou expirée », ce qui n'aide personne.
  if (!key) {
    systeme("Il manque ta clé d'accès. Rouvre le lien de CTester depuis Moodle "
        + "pour pouvoir tester ton code. Tu peux écrire en attendant : "
        + "ton brouillon est enregistré.");
    return;
  }
  const body = {key, exercise_id: tp.id};
  if (tp.mode === "quiz") {
    if (!ctester.quiz) {
      systeme("Le quiz n'a pas pu être chargé. Recharge la page.", true);
      return;
    }
    body.answers = ctester.quiz.answers();
    // RIEN À TESTER N'EST PAS UN ÉCHEC. En rouge, en 2,1 rem, à l'emplacement
    // du verdict, ça grondait quelqu'un qui venait juste d'ouvrir l'exercice et
    // cliquait pour voir ce que fait le bouton.
    if (!Object.values(body.answers).some(v => v.trim())) {
      systeme("Saisis au moins une réponse avant de tester."); return;
    }
  } else {
    sources[actif] = $("code").value;
    body.files = sources;
    if (!Object.values(sources).some(v => v.trim())) {
      systeme("Il n'y a encore rien à tester : écris ou colle ton code d'abord.");
      return;
    }
  }
  // LE MÊME CODE QUE LA DERNIÈRE FOIS N'A RIEN À REDEMANDER. Aucune requête
  // ne part, donc ni cooldown, ni place de file, ni attente.
  const cle = JSON.stringify(body.answers || body.files);
  const connu = dejaSoumis[tp.id];
  if (connu && connu.cle === cle && renvoiForce !== cle) {
    // LE SECOND CLIC RENVOIE, et cette échappatoire n'est pas optionnelle : un
    // cas de test corrigé par le tick de cinq minutes rendrait le verdict gardé
    // faux, et la page n'a aucun moyen de l'apprendre. Sans elle, c'est le
    // bouton qui aurait l'air cassé.
    renvoiForce = cle;
    render(connu.verdict, portee);
    systeme("Même code que ta dernière soumission — voici son verdict, sans "
          + "reprendre de place dans la file. Clique encore pour le renvoyer "
          + "au juge.");
    return;
  }
  renvoiForce = null;
  const jeton = ++soumissionCourante;
  enVol = { jeton: jeton, exercice: tp.id, cle: cle };
  effacerSysteme();
  occupe(true);
  verdict({ cls: "wait", titre: "Envoi…" });
  try {
    const r = await fetch(API("submit?poste=" + encodeURIComponent(posteId())), {
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
    // LE QUOTA A SON PROPRE CHEMIN : `retry_after` était envoyé par l'API et
    // jeté par la page depuis toujours.
    if (r.status === 429 && out && out.retry_after) {
      // La soumission n'est jamais partie : le verdict repart du repos plutôt
      // que de rester sur « Envoi… », qui serait faux.
      repos();
      attendreQuota(out.retry_after);
      return;
    }
    if (!r.ok || !out) {
      systeme((out && out.error)
              || `Le serveur a répondu ${r.status} et n'a pas pris ta `
                 + `soumission. Ton code est enregistré — réessaie dans un instant.`,
              true);
      occupe(false);
      return;
    }
    poll(out.id, 150, portee, jeton);
  } catch (e) {
    systeme("Le serveur ne répond pas. Ton code est enregistré sur cet "
          + "appareil ; réessaie dans un instant.", true);
    occupe(false);
  }
}

// LE CLIC EST IGNORÉ PENDANT UN TEST, et c'est ce qui remplace `disabled` :
// voir `occupe()`. Le bouton reste focalisable, donc la tabulation ne repart
// pas du haut de la page à chaque soumission.
// LA PROMESSE EST RENDUE, et ce n'est pas cosmétique : le harnais attend le
// clic pour savoir que la soumission est partie. Un garde en corps de bloc
// rendrait `undefined`, et tout ce qui suit s'exécuterait avant le fetch.
$("go").addEventListener("click", () => soumettre(null));
$("goex").addEventListener("click", () =>
  soumettre(ctester.quiz ? ctester.quiz.page() : null));

// --- Compteur de présence, pour tout le monde -----------------------------
// Un battement toutes les 60 s vers /live, qui ne touche qu'un dict en mémoire
// côté serveur (ni base, ni compte). C'est la SEULE requête que le parcours
// anonyme émet. ponytail: un identifiant de fenêtre tiré au hasard et gardé le
// temps de l'onglet -- falsifiable, mais c'est un chiffre affiché, pas un
// verrou. Une panne du compteur ne se voit pas : il reste caché.
let liveId = sessionGet("ctester.live");
if (!liveId) {
  liveId = (typeof crypto !== "undefined" && crypto.randomUUID)
    ? crypto.randomUUID()
    : String(Math.random()).slice(2) + Date.now();
  sessionSet("ctester.live", liveId);
}
async function battement() {
  try {
    const r = await fetch(API("live?id=" + encodeURIComponent(liveId)));
    const d = await r.json();
    if (d && typeof d.n === "number") {
      $("live").textContent =
        d.n > 1 ? d.n + " personnes en ligne" : "1 personne en ligne";
      $("live").hidden = false;
    }
  } catch (e) { /* cosmétique : on ne dérange personne si /live tombe */ }
}
battement();
setInterval(battement, 60000);
