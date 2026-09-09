// "Discussions": one peer-help thread per exercise, for signed-in accounts.
// Loaded ON CLICK, never before -- the anonymous visitor downloads none of
// it, and neither does a signed-in student who never opens it. Same
// contract as progres.js, same reasons.
//
// ONE WAY: this file reads `window.ctester` and deposits its own entry into
// it; the core only ever knows it through `ctester.forum`, never through an
// import.
//
// THIS FILE DECIDES NOTHING about permissions. Who is a moderator, which
// messages are visible, who may delete or hide: all of it is settled by the
// API from the authenticated `sub`. The `moderateur` flag that arrives here
// only ever decides what to DRAW -- every route recomputes it.
//
// MODERATION IS HUMAN, AND THE PAGE SAYS SO. Nothing here promises a shared
// solution would be detected automatically: it would not be. That is what
// makes the "Signaler" button useful rather than decorative.
(function (ctester) {
const $ = ctester.$;

// THE CHARTER, IN ONE PLACE. It displays in the view AND before the
// session's first post; two copies of the text would eventually contradict
// each other, and it is the forgotten copy that would get read at the
// moment it matters.
const CHARTE = [
  "Entraide conceptuelle : une question, une idée, ce que tu observes, "
  + "ce que tu as déjà essayé.",
  "Pas de solution complète, pas d'extrait de code, aucun fichier déposé.",
  "Pas de capture d'écran.",
  "Pas de lien vers une solution — un lien vers un corrigé sera masqué.",
  "Respect mutuel : on parle du problème, jamais de la personne.",
  "Tu vois passer une solution ? Signale-la plutôt que d'y répondre.",
];

const CHARTE_VUE = "ctester.charte";

// --- Rendering, and this is the part that matters ---------------------------
// MESSAGES ARE RESTRICTED MARKDOWN, STORED IN THEIR SOURCE FORM. The server
// renders nothing and sanitizes nothing: it bounds. All rendering happens
// here, on EVERY display -- the thread, the compose preview, and the
// moderation queue. Sanitizing once, at write time, would have left
// messages already in the database out of reach of any rule tightened
// later.
//
// TWO BARRIERS, IN THIS ORDER:
//   1. raw HTML is ESCAPED BEFORE Markdown parsing, so `marked` never sees a
//      tag and never emits one that came from a student;
//   2. `marked`'s output goes through DOMPurify with a closed allow-list.
// The document's CSP is a third layer, and it is not the main defense: these
// two are.
const MARKED = "vendor/marked-18.0.11.umd.js";
const PURIFY = "vendor/purify-3.4.14.min.js";

// THE ALLOW-LIST. Nothing else survives: no `style`, `class`, `id` or event
// attribute, no SVG, MathML, image, media, iframe, form or custom element.
// `pre` is not in it either -- no rendered code block, a fenced block
// therefore falls back to plain text.
const BALISES = ["p", "br", "strong", "em", "ul", "ol", "li", "blockquote",
                 "code", "a"];
// `href` for links, `rel` because the hook below writes it. No `target`: a
// forum link never opens a named target.
const ATTRIBUTS = ["href", "rel"];
const NETTOYAGE = {
  ALLOWED_TAGS: BALISES,
  ALLOWED_ATTR: ATTRIBUTS,
  // ABSOLUTE http(s) ONLY. Everything else -- `javascript:`, `data:`,
  // `vbscript:`, a relative URL -- loses its `href` and falls back to text.
  ALLOWED_URI_REGEXP: /^https?:\/\//i,
  ALLOW_DATA_ATTR: false,
  ALLOW_ARIA_ATTR: false,
  ALLOW_UNKNOWN_PROTOCOLS: false,
};

const MARKDOWN = { gfm: true, breaks: true };

// BEFORE PARSING, NOT AFTER. A `<` that never reaches the parser cannot come
// back out as a tag, however subtle the Markdown extension of the day.
//
// `<` ONLY, AND THAT IS EXACT: an HTML tag starts with `<`, comments
// (`<!--`) and processing instructions included. Escaping `>` AS WELL was
// tried and broke Markdown blockquotes (`> comme ceci`), which is in the
// allow-list -- that would have removed an advertised feature for zero
// gain. `marked` itself escapes the `>` in the text it renders. `&` is left
// alone too: touching it would break entities a student writes by hand, and
// an entity is text, not a tag.
const escapeAngle = (s) => s.replace(/</g, "&lt;");

let libraries = null;
let renderAvailable = false;       // is Markdown rendering actually available?

function loadLibraries() {
  if (!libraries) {
    libraries = Promise.all([ctester.charger(MARKED), ctester.charger(PURIFY)])
      // THE FAILURE IS FORGOTTEN, like the core's loader: a one-second
      // outage must not condemn rendering for the whole visit.
      .catch((e) => { libraries = null; throw e; });
  }
  return libraries;
}

let hookInstalled = false;

function sanitizer() {
  const p = window.DOMPurify;
  // `isSupported` is false when DOMPurify found no real DOM. In that state,
  // `sanitize()` RETURNS ITS INPUT AS-IS -- using it would amount to writing
  // a student's HTML into the page with no filter at all. We would rather
  // not render any Markdown at all.
  if (!p || !p.isSupported || typeof p.sanitize !== "function") return null;
  if (!hookInstalled && typeof p.addHook === "function") {
    hookInstalled = true;
    // `rel` SET HERE AND NEVER HOPED FOR FROM THE AUTHOR: a forum link
    // always comes out with `noopener noreferrer`, and never with a named
    // target -- `target` is not in the allow-list anyway, this says so
    // twice.
    p.addHook("afterSanitizeAttributes", (node) => {
      if (node.tagName === "A") {
        node.setAttribute("rel", "noopener noreferrer");
        node.removeAttribute("target");
      }
    });
  }
  return p;
}

function rendreMarkdown(target, source) {
  // PLAIN TEXT FIRST, ALWAYS. If a library is missing, if parsing throws, if
  // the sanitizer cannot be used: what stays on screen is text, never
  // unfiltered HTML.
  target.textContent = source;
  const purify = sanitizer();
  const md = window.marked;
  if (!purify || !md || typeof md.parse !== "function") return false;
  let clean;
  try {
    clean = purify.sanitize(md.parse(escapeAngle(source), MARKDOWN), NETTOYAGE);
  } catch (e) {
    return false;
  }
  target.textContent = "";
  // THE ONLY `innerHTML` IN THE ENTIRE CLIENT, and it receives the
  // sanitizer's output AT THAT VERY INSTANT: no variable lying around, no
  // concatenation, no cache. What gets written is exactly what DOMPurify
  // just rendered, for this source.
  target.innerHTML = clean;
  return true;
}

// The view's state. `fil === null` with an `erreur` means "we don't know":
// it must never display as an empty thread. Announcing "no messages" during
// an outage would make it look like nobody answered.
let fil = null;
let signalements = null;
let nomsSignales = null;
// THIS account's profile: the name it gave itself, its group, and what it
// chose to display. `null` until it has been read -- we do not invent an
// empty profile, that would amount to announcing "you have no name" during
// an outage.
let profil = null;
let moderateur = false;
let maxTexte = 0;
// THE TWO CLOSED LISTS AND THE THREAD'S STATE, all sent with the thread as a
// legend. Kept rather than copied into constants here: the server groups its
// instructor aggregate by these ids, and a second copy would drift from the
// one that actually counts.
let steps = [];
let blockedKinds = [];
let threadStateInfo = null;
// The instructor's "who needs help" rows (design 1h). `null` until read, and
// `null` is not "nobody" -- during an outage those are opposite claims.
let helpRows = null;
let topRows = null;          // « Questions du moment », modérateur seulement
let erreur = "";
let annonce = "";
let exercice = "";           // LA CLÉ DU FIL, pas l'exercice : `@chat:…` ou un id
let saisie = "";
// QUEL ESPACE ON REGARDE. Le chat est public, le forum garde le privé, et le
// préfixe `@chat:` est toute la distinction (voir `services/forum.py`). Le
// défaut est le chat : c'est ce qu'on vient chercher quand on ouvre
// « Discussions » pendant un labo.
let modeFil = "chat-ex";
let estChat = true;
let repondA = null;          // la racine à laquelle on répond, ou null
let socket = null;
let socketRetard = 1000;     // recul progressif entre deux reconnexions
let recherche = "";
let resultats = null;
let doublons = null;
let minuterieDoublon = null;
let permalien = null;        // une conversation ouverte depuis la recherche
let exerciceForce = "";     // l'exercice choisi DANS la vue, s'il l'a été
let titre = null;
let zone = null;
let apercu = null;
// The current view's "Nom affiché" field, so the Compte menu's "Mon
// identité" can bring focus to it. A REFERENCE, not a getElementById: the
// block does not always exist (a profile read failure).
let champPseudo = null;

// --- Network -----------------------------------------------------------------

// L'EXERCICE QUE LE FIL REGARDE, jamais la clé du fil. `exercice` porte
// maintenant `@chat:tp2-ex3` aussi bien que `tp2-ex3` : le chercher tel quel
// dans le catalogue ne trouverait rien et retomberait silencieusement sur le
// premier exercice de la liste.
function currentExercise() {
  const cat = ctester.catalogue();
  const nu = exercice.startsWith(CHAT_PREFIX)
    ? exercice.slice(CHAT_PREFIX.length) : exercice;
  const target = exerciceForce || nu
    || ctester.exerciceOuvert() || ctester.exerciceChoisi();
  const found = cat.find(t => t.id === target) || cat[0];
  return found ? found.id : "";
}

// LA CLÉ DU FIL EST CALCULÉE À UN SEUL ENDROIT. Le serveur ne connaît que des
// clés : `@chat:general`, `@chat:<exercice>`, ou l'identifiant d'exercice nu
// pour le forum. La page ne fabrique donc jamais un préfixe ailleurs qu'ici.
const CHAT_PREFIX = "@chat:";
const CHAT_GENERAL = CHAT_PREFIX + "general";

function cleFil() {
  if (modeFil === "chat-general") return CHAT_GENERAL;
  const ex = currentExercise();
  if (!ex) return modeFil === "chat-ex" ? CHAT_GENERAL : "";
  return modeFil === "forum" ? ex : CHAT_PREFIX + ex;
}

const INDISPO = "Les discussions ne sont pas disponibles pour l'instant. "
              + "L'exercice et le bouton « Tester », eux, fonctionnent "
              + "normalement.";

async function charger(id) {
  fil = null;
  signalements = null;
  nomsSignales = null;
  // ON NE RÉPOND PAS À UN MESSAGE D'UN AUTRE FIL. Changer de fil abandonne la
  // cible : sans ça, `reply_to` viserait une racine que le serveur refuserait
  // (le `WHERE` exige le même fil), et l'étudiant lirait « message
  // introuvable » sans comprendre pourquoi.
  if (id !== exercice) { repondA = null; permalien = null; }
  exercice = id;
  if (!ctester.compte) {
    erreur = "Reconnecte-toi pour ouvrir les discussions.";
    return;
  }
  if (!id) {
    erreur = "Aucun exercice n'est publié pour l'instant.";
    return;
  }
  const response = await ctester.compte.getJson(
    "forum?ex=" + encodeURIComponent(id));
  if (!response || !Array.isArray(response.messages)) {
    erreur = INDISPO;
    return;
  }
  fil = response.messages;
  estChat = !!response.chat;
  moderateur = !!response.moderator;
  maxTexte = response.max || 0;
  steps = Array.isArray(response.steps) ? response.steps : [];
  blockedKinds = Array.isArray(response.blocked_kinds) ? response.blocked_kinds : [];
  threadStateInfo = response.state || null;
  erreur = "";
  // The report queue is only ever requested by a moderator, and the server
  // refuses everyone else: this check just avoids a needless 403, it
  // protects nothing on its own.
  if (moderateur) {
    const queue = await ctester.compte.getJson("forum/moderation");
    signalements = queue && Array.isArray(queue.reports)
      ? queue.reports : null;
    nomsSignales = queue && Array.isArray(queue.reported_names) ? queue.reported_names : null;
    // "QUI A BESOIN D'AIDE" IS READ WITH THE QUEUE, not on its own tab: an
    // instructor opening moderation during a lab wants both, and two clicks
    // for two halves of the same question is one click too many.
    const helpResponse = await ctester.compte.getJson("forum/help");
    helpRows = helpResponse && Array.isArray(helpResponse.rows) ? helpResponse : null;
    // « QUESTIONS DU MOMENT » : ce qui est le plus demandé maintenant. Lu avec
    // le reste de l'écran de modération, pas sur un onglet à lui -- un
    // enseignant qui ouvre la modération pendant un labo veut les deux, et
    // deux clics pour deux moitiés de la même question, c'en est un de trop.
    const topResponse = await ctester.compte.getJson("forum/top");
    topRows = topResponse && Array.isArray(topResponse.rows) ? topResponse : null;
  }
  await chargerProfil();
}

// THE PROFILE READS ON ITS OWN. "Mon identité" opens from the Compte menu,
// with no thread and no exercise: loading it together with the thread would
// have made the setting depend on a view one has not necessarily opened.
async function chargerProfil() {
  if (!ctester.compte) return;
  const mine = await ctester.compte.getJson("forum/profil");
  profil = mine && typeof mine === "object" ? mine : null;
  // LES ÉQUIPES SONT LUES ICI PARCE QUE C'EST L'ÉCRAN « QUI JE SUIS ».
  // Elles ne sont PAS un réglage : rien de ce panneau ne peut les changer, et
  // c'est tout l'intérêt — un étudiant qui pourrait choisir son équipe
  // choisirait celle dont le travail est le plus avancé. Ce qu'il peut faire,
  // c'est constater qu'il est dans la mauvaise et le dire à son enseignant,
  // AVANT que le devoir n'ouvre.
  const teams = await ctester.compte.getJson("team/mine");
  equipes = teams && Array.isArray(teams.teams) ? teams.teams : null;
  // ET LA LISTE DES ÉQUIPES DISPONIBLES, tant qu'il y a quelque chose à
  // choisir. Une seule requête de plus, et seulement s'il existe un devoir
  // d'équipe : le déploiement qui n'en a pas n'en paie rien.
  listeEquipes = null;
  const devoir = (ctester.assignments() || []).find((a) => a && a.team);
  const mienne = devoir && (equipes || []).find(
    (e) => e.assignment_id === devoir.id);
  if (devoir && (!mienne || mienne.joinable)) await chargerEquipes(devoir.id);
}

// The API's error message is REUSED AS-IS when there is one: "message trop
// long", "trop de messages d'un coup". Replacing it with "échec" would make
// someone try the exact same thing again.
function pourquoi(response, fallback) {
  if (!response) return "le serveur est injoignable";
  if (response.corps && response.corps.error) return response.corps.error;
  return fallback + " (réponse " + response.status + ")";
}

async function ecrire(path, method, payload, successMsg, failMsg) {
  const response = await ctester.compte.sendJson(path, method, payload);
  const ok = !!(response && response.ok);
  annonce = ok ? successMsg : failMsg + " : " + pourquoi(response, "refusé");
  if (ok) await charger(exercice);
  redessiner();
  return ok;
}

// WE REDRAW THE SCREEN BEING LOOKED AT, not the other one: hiding a message
// from moderation used to redraw the THREAD instead, a screen that was not
// even displayed, and the action looked like it had done nothing.
function redessiner() {
  if (ctester.vue() === "moderation") dessinerModeration();
  else dessiner();
}

// RÉPONDRE : on retient la cible, le formulaire le dit, et `publier` ajoute
// `reply_to`. Le serveur aplatit vers la racine lui-même -- répondre à une
// réponse n'a donc rien de particulier ici.
function repondreA(id) {
  repondA = id;
  dessiner();
  if (zone && zone.focus) zone.focus();
}

async function publier(text, extra) {
  const ok = await ecrire("forum", "POST",
                          Object.assign({ exercise_id: exercice, text: text },
                                        extra || {}),
                          "Message publié.", "Message non publié");
  // CLEAR AFTERWARD, AND ONLY IF IT ACTUALLY WENT THROUGH. `ecrire` has
  // already redrawn, so `zone` is the new field. A refusal -- message too
  // long, quota -- must leave the text on screen: losing it would make
  // someone retype the same thing with the rule no longer in front of them.
  if (ok) {
    saisie = "";
    if (zone) zone.value = "";
    if (apercu) rendreMarkdown(apercu, "");
  }
}

const supprimer = (id) => ecrire(
  "forum?id=" + encodeURIComponent(id), "DELETE", undefined,
  "Ton message a été supprimé.", "Suppression impossible");

const signaler = (id) => ecrire(
  "forum/signalement", "POST", { id: id },
  "Signalé. Un responsable du cours va le lire.", "Signalement impossible");

const signalerNom = (id) => ecrire(
  "forum/signalement", "POST", { id: id, kind: "name" },
  "Nom signalé. Un responsable du cours va le lire.", "Signalement impossible");

// THE ONE TRANSITION (design 1g): private -> group, and only on one's own
// message. The server holds the rule in its `WHERE`; this only asks.
const openToGroup = (id) => ecrire(
  "forum/visibility", "POST", { id: id },
  "Ta question est maintenant visible par ton groupe.",
  "Impossible de l'ouvrir à ton groupe");

// LE VOTE. `value` vaut +1, -1 ou 0 (retirer). Le serveur refuse son propre
// message ET LE -1 SUR UNE QUESTION -- on ne dessine pas le bouton, mais ce
// n'est pas ce qui tient la règle : elle est dans le `WHERE` de l'instruction,
// donc elle tient aussi contre quelqu'un qui appelle la route à la main.
//
// IL N'ACCORDE RIEN : ni XP, ni succès, ni carte.
const voter = (id, value) => ecrire(
  "forum/helpful", "POST", { id: id, value: value },
  value === 0 ? "Vote retiré." : "Merci — ça aide les suivants.",
  "Impossible de voter");

const effacerNom = (id) => ecrire(
  "forum/moderation", "POST", { id: id, action: "clear-name" },
  "Nom effacé.", "Action impossible");

// TWO POSSIBLE SURFACES, ONE SINGLE WRITE: the Compte menu's panel, and the
// thread if it is open (displayed names can change). `ecrire` was no longer
// enough -- it redraws the forum view, which is not necessarily there.
async function enregistrerProfil(payload) {
  const response = await ctester.compte.sendJson("forum/profil", "POST", payload);
  const ok = !!(response && response.ok);
  annonce = ok ? "Identité enregistrée."
               : "Identité non enregistrée : " + pourquoi(response, "refusé");
  await chargerProfil();
  if (ctester.vue() === "forum") {
    await charger(exercice);
    dessiner();
  }
  if (!$("identitepanneau").hidden) renderPanel();
  return ok;
}

const moderer = (id, action) => ecrire(
  "forum/moderation", "POST", { id: id, action: action },
  action === "hide" ? "Message masqué." : "Message rétabli.",
  "Action impossible");

// --- Rendering the view -------------------------------------------------------
// `textContent` for EVERYTHING that is not a message. Messages themselves go
// through `rendreMarkdown` above, and through nothing else.

function node(tag, className, text) {
  const n = document.createElement(tag);
  if (className) n.className = className;
  if (text !== undefined) n.textContent = text;
  return n;
}

function button(text, className, action) {
  const b = node("button", className, text);
  b.type = "button";
  b.addEventListener("click", action);
  return b;
}

function guidelinesList() {
  const ul = node("ul", "regles");
  for (const rule of CHARTE) ul.append(node("li", "", rule));
  return ul;
}

// THE CHARTER BEFORE THE SESSION'S FIRST POST, in the same panel as the
// sign-in consent. Once read, it does not reappear on every message -- it
// stays in view, further up in the page.
function showGuidelines(then) {
  const box = $("charte");
  box.innerHTML = "";
  box.append(node("h2", "", "Avant de publier"));
  box.append(guidelinesList());
  box.append(node("p", "", "Les messages sont lus et modérés par des "
    + "personnes, pas par un automate. Un message qui contient une solution "
    + "peut être masqué."));
  const row = node("div", "row");
  row.append(button("J'ai compris — publier", "", () => {
    box.hidden = true;
    ctester.sessionSet(CHARTE_VUE, "1");
    then();
  }));
  row.append(button("Annuler", "nav", () => { box.hidden = true; }));
  box.append(row);
  box.hidden = false;
}

// Two digits, like on a course outline: "7" displays as "07".
const groupNumber = (n) => "groupe " + String(n).padStart(2, "0");

// MY IDENTITY. The name and the group are OPTIONAL and INVISIBLE by
// default: checking a box is a deliberate act, doing nothing keeps
// anonymity. The server revalidates everything -- this form only bounds
// input to save a round trip, it authorizes nothing.
// MY IDENTITY (design 1d). The name, the group, the plate and the ranking,
// all OPTIONAL and all INVISIBLE by default: ticking a box is a deliberate
// act, doing nothing keeps anonymity. The server revalidates everything --
// this form only bounds input to save a round trip, it authorizes nothing.
//
// THE PREVIEW IS THE POINT OF THE REDESIGN HERE. Four checkboxes describing
// what others see, with no picture of what others see, is a privacy setting
// one has to imagine. It redraws on every keystroke and every tick, from the
// same fields the save button will send.
// MON ÉQUIPE, ET C'EST ICI QU'ON LA CHOISIT.
//
// LES ÉQUIPES PRÉEXISTENT, NUMÉROTÉES PAR GROUPE, et on prend une place libre
// dans celle qu'on veut -- exactement le geste de Moodle, avec les MÊMES
// numéros, parce que l'enseignant tiendrait sinon deux listes qui divergent.
//
// POURQUOI DANS « Mon identité » ET PAS DANS L'ÉCRAN DU DEVOIR : le devoir
// ouvre en octobre et les équipes se choisissent avant. Un écran qui n'existe
// qu'une fois le devoir ouvert ferait choisir les équipes le matin de la
// remise. Ici, c'est l'écran « qui je suis », et « avec qui je remets » en
// fait partie -- avec le champ « Groupe » juste en dessous, qui est ce qui
// décide de la liste qu'on voit.
//
// RIEN N'EST CALCULÉ ICI. Combien d'équipes, combien de places, laquelle est
// pleine : tout arrive décidé du serveur. Une page qui déciderait qu'une
// équipe a de la place serait une page où l'on s'en déclare une depuis la
// console.

// L'action qui vient de se passer, ou son refus. Le panneau est redessiné en
// entier après chaque appel, donc ce texte est le seul lien entre « j'ai
// cliqué » et « voilà ce qui s'est passé ».
let motEquipe = "";
// La liste des équipes du groupe, telle que `GET /team/available` la rend.
// `null` = pas lue (devoir ouvert, groupe manquant, panne) -- et la raison est
// dans `motEquipe`, parce que les trois envoient à trois endroits différents.
let listeEquipes = null;

async function chargerEquipes(assignmentId) {
  const reponse = await ctester.compte.sendJson(
    "team/available?assignment=" + encodeURIComponent(assignmentId), "GET");
  if (reponse && reponse.ok) {
    listeEquipes = reponse.corps;
    return;
  }
  listeEquipes = null;
  // LE MESSAGE DU SERVEUR, PAS LE NÔTRE : lui seul sait si le devoir est
  // ouvert, si le groupe manque, ou si la base ne répond pas.
  motEquipe = (reponse && reponse.corps && reponse.corps.error) || "";
}

async function actionEquipe(chemin, corps) {
  const reponse = await ctester.compte.sendJson(chemin, "POST", corps);
  if (!reponse) {
    motEquipe = "Le serveur ne répond pas. Réessaie dans un instant.";
  } else if (!reponse.ok) {
    motEquipe = (reponse.corps && reponse.corps.error)
      || "Ça n'a pas marché. Réessaie dans un instant.";
  } else {
    motEquipe = "";
    listeEquipes = reponse.corps;
  }
  await chargerProfil();
  renderPanel();
}

function equipeDe(assignmentId) {
  return (equipes || []).find((e) => e.assignment_id === assignmentId) || null;
}

// LA LISTE, COMME SUR MOODLE : un numéro, un remplissage, un bouton. Elle ne
// dit PAS qui est dans quelle équipe -- « 3/4 » suffit à choisir, et publier
// les compositions ferait de ce choix un tri social sur une page.
function listeDesEquipes(devoir, mienne) {
  const box = node("div", "equipes");
  if (!listeEquipes) {
    box.append(node("p", "aide", motEquipe || "La liste des équipes n'est pas "
      + "disponible pour l'instant."));
    return box;
  }
  box.append(node("p", "aide", "Choisis ton équipe, la même que sur Moodle. "
    + "Vous serez " + devoir.team.min
    + (devoir.team.max > devoir.team.min ? " à " + devoir.team.max : "")
    + " ; tu peux en changer tant que le devoir n'est pas ouvert."));
  for (const equipe of listeEquipes.teams) {
    const ligne = node("div", "equipeligne" + (equipe.number === mienne ? " on" : ""));
    ligne.append(node("b", "nom", equipe.name));
    ligne.append(node("span", "places",
                      equipe.members + " / " + equipe.max));
    ligne.append(node("span", "grow"));
    if (equipe.number === mienne) {
      ligne.append(node("span", "tag ok", "la tienne"));
      ligne.append(button("Quitter", "nav", () => actionEquipe(
        "team/leave", { assignment_id: devoir.id })));
    } else if (equipe.full) {
      // COMPLÈTE : le bouton disparaît plutôt que d'être grisé. Un bouton
      // grisé invite à cliquer pour voir, et la réponse est toujours non.
      ligne.append(node("span", "tag", "complète"));
    } else if (mienne === null || mienne === undefined) {
      ligne.append(button("Rejoindre", "", () => actionEquipe(
        "team/join", { assignment_id: devoir.id, number: equipe.number })));
    } else {
      // ON EN A DÉJÀ UNE : il faut la quitter d'abord, et le serveur le dit.
      // Le bouton reste, parce que le refus explique -- l'absence, non.
      ligne.append(button("Rejoindre", "nav", () => actionEquipe(
        "team/join", { assignment_id: devoir.id, number: equipe.number })));
    }
    box.append(ligne);
  }
  return box;
}

// UNE ÉQUIPE À LAQUELLE ON APPARTIENT. Ce qu'on vient vérifier : le numéro
// (celui de Moodle), le groupe, qui est dedans, et quand le devoir ouvre.
function monEquipe(equipe) {
  const box = node("div", "equipe");
  const titre = node("div", "equipetitre");
  titre.append(node("b", "", equipe.label));
  titre.append(node("span", "tag", groupNumber(equipe.group_number)));
  titre.append(node("span", "tag", equipe.assignment_title));
  // LA DATE D'OUVERTURE PLUTÔT QUE RIEN : sans elle, une équipe sur un devoir
  // fermé n'a l'air de rien. Même choix que le cadenas daté du menu.
  if (equipe.access !== "available") {
    const quand = new Date(equipe.available_from || "");
    titre.append(node("span", "tag", isNaN(quand.getTime()) ? "à venir"
      : "ouvre le " + quand.toLocaleDateString(undefined,
                                               { day: "numeric", month: "long" })));
  } else {
    titre.append(node("span", "tag ok", "figée"));
  }
  box.append(titre);

  const gens = node("div", "equipegens");
  for (const membre of equipe.members || []) {
    const puce = node("span", "mate on");
    const point = node("i", "dot");
    point.setAttribute("style", "background:" + membre.color);
    puce.append(point, node("span", "", membre.name + (membre.you ? " (toi)" : "")));
    gens.append(puce);
  }
  box.append(gens);
  if (!equipe.joinable) {
    box.append(node("p", "aide", "Le devoir est ouvert : les équipes sont "
      + "figées. Si la tienne est fausse, vois avec ton enseignant."));
  }
  return box;
}

function mesEquipes() {
  // RIEN DU TOUT quand le déploiement n'a aucun devoir d'équipe : là, le
  // silence est la bonne réponse. Lu dans le catalogue que le noyau a déjà
  // chargé -- pas une requête de plus.
  const devoirs = (ctester.assignments() || []).filter((a) => a && a.team);
  if (!devoirs.length) return node("span", "");
  const box = node("div", "mesequipes");
  box.append(node("h3", "soustitre",
                  devoirs.length > 1 ? "Mes équipes" : "Mon équipe"));
  if (motEquipe) box.append(node("p", "rate", motEquipe));
  // TROIS ÉTATS, PAS DEUX. « pas d'équipe », « la liste n'a pas pu être lue »
  // et « il n'y a pas de devoir d'équipe » se ressemblaient tous les trois --
  // c'est-à-dire à rien du tout. Un écran de vérification qui se tait répond
  // « tout va bien » à toutes les questions.
  if (equipes === null) {
    box.append(node("p", "rate", "La liste de tes équipes n'a pas pu être lue."));
    box.append(node("p", "aide", "Réessaie dans un instant. Si ça persiste, "
      + "préviens ton enseignant : ce n'est pas toi, c'est le service."));
    return box;
  }
  for (const devoir of devoirs) {
    const mienne = equipeDe(devoir.id);
    if (mienne) box.append(monEquipe(mienne));
    if (!mienne || mienne.joinable) {
      box.append(listeDesEquipes(devoir, mienne ? mienne.number : null));
    }
  }
  return box;
}

function myIdentity() {
  const block = node("div", "");
  block.append(node("h2", "", "Mon identité"));
  if (annonce) block.append(node("p", "annonce", annonce));
  if (profil === null) {
    block.append(node("p", "rate", "Ton identité n'a pas pu être lue."));
    block.append(closeRow());
    return block;
  }

  block.append(mesEquipes());

  const nameId = "forumpseudo";
  const nameLabel = node("label", "", "Nom affiché (facultatif)");
  nameLabel.setAttribute("for", nameId);
  const nameField = node("input");
  nameField.id = nameId;
  nameField.type = "text";
  nameField.autocomplete = "off";
  nameField.maxLength = profil.max_display_name || 24;
  // RAUTHY'S SUGGESTION ONLY EVER PRE-FILLS, and only until a name has been
  // chosen. It is neither saved nor shown to others before a click on
  // "Enregistrer" with the box checked: someone's sign-in name does not get
  // published on its own.
  nameField.value = profil.display_name || profil.suggestion || "";
  nameField.placeholder = "Participant";
  champPseudo = nameField;

  const groupId = "forumgroupe";
  const groups = Array.isArray(profil.group_numbers) ? profil.group_numbers : [];
  const groupValue = profil.group_number === null || profil.group_number === undefined
    ? "" : String(profil.group_number);
  let groupField;
  if (groups.length) {
    // A fixed list for the session: only these groups exist, might as well
    // not let anything else be typed.
    groupField = node("select");
    const empty = node("option", "", "— aucun —");
    empty.value = "";
    groupField.append(empty);
    for (const g of groups) {
      const o = node("option", "", groupNumber(g));
      o.value = String(g);
      groupField.append(o);
    }
  } else {
    groupField = node("input");
    groupField.type = "number";
    groupField.min = "1";
    groupField.max = "99";
  }
  groupField.id = groupId;
  groupField.value = groupValue;
  const groupLabel = node("label", "", "Groupe (facultatif)");
  groupLabel.setAttribute("for", groupId);

  const [showName, nameRow] = checkbox("forumvoirnom",
    "Afficher mon nom dans les discussions", profil.display_name_public);
  const [showGroup, groupRow] = checkbox("forumvoirgroupe",
    "Afficher mon numéro de groupe", profil.group_number_public);
  const [showBadges, badgesRow] = checkbox("forumshowplate",
    "Afficher ma plaque et mes écussons", profil.badges_public);
  const [joinLeaderboard, leaderboardRow] = checkbox("forumleaderboard",
    "Participer au classement de mon groupe", profil.leaderboard_opt_in);

  block.append(nameLabel, nameField, groupLabel, groupField);
  const frameField = plateFramePicker(block);

  // THE MASKED NAME IS READ-ONLY AND REDRAWN, never typed: a name carrying
  // student-written text would need moderating, and this one does not,
  // because nothing typed can reach it.
  //
  // DRAWN UNCONDITIONALLY, AND THAT IS A FIX. It used to be `if
  // (profil.alias)`, which was a chicken-and-egg: the ONLY thing that writes
  // an alias is the button inside this block, so the button was hidden from
  // exactly the accounts that had no name -- all of them, unless they had
  // opened the leaderboard. Harmless while the alias was decoration on a
  // ranking; blocking now that it is how one appears in the chat.
  block.append(aliasBlock());

  const preview = node("div", "previewplate");
  const readForm = () => ({
    display_name: nameField.value,
    group_number: groupField.value,
    display_name_public: showName.checked,
    group_number_public: showGroup.checked,
    badges_public: showBadges.checked,
    leaderboard_opt_in: joinLeaderboard.checked,
    plate_frame: frameField ? frameField.value : (profil.plate_frame || ""),
  });
  const redraw = () => drawPlatePreview(preview, readForm());
  const watched = [nameField, groupField, showName, showGroup, showBadges];
  if (frameField) watched.push(frameField);
  for (const field of watched) {
    field.addEventListener("input", redraw);
    field.addEventListener("change", redraw);
  }

  block.append(nameRow, groupRow, badgesRow, leaderboardRow);
  if (!profil.display_name && profil.suggestion) {
    block.append(node("p", "aide", "Nom proposé par ta connexion — modifie-le si tu veux, il ne s'affiche qu'une fois enregistré et coché."));
  }
  block.append(node("p", "aide", "Décoché, ton vrai nom n'apparaît nulle part : "
    + "tu écris sous ton nom masqué ci-dessus. L'enseignant, lui, voit "
    + "toujours ton numéro de groupe — jamais ton nom si tu ne l'affiches "
    + "pas."));
  block.append(node("h3", "soustitre", "Aperçu"));
  block.append(preview);
  block.append(node("p", "aide", "Voilà exactement ce que les autres verront."));
  redraw();

  const row = node("div", "row");
  row.append(button("Enregistrer", "", () => enregistrerProfil(readForm())));
  row.append(button("Fermer", "nav", closeIdentity));
  block.append(row);
  return block;
}

// THE FRAMES COME FROM THE SERVER, computed from the level this account
// actually reached. Offering one it has not unlocked would be a form that
// lies, then a 400 the student cannot act on. One frame means no choice to
// make, so no picker.
function plateFramePicker(block) {
  const frames = Array.isArray(profil.frames) ? profil.frames : [];
  if (frames.length < 2) return null;
  const field = node("select");
  field.id = "forumcadre";
  const none = node("option", "", "— aucun —");
  none.value = "";
  field.append(none);
  for (const f of frames) {
    const o = node("option", "", f.title);
    o.value = f.id;
    field.append(o);
  }
  field.value = profil.plate_frame || "";
  const label = node("label", "", "Cadre de plaque");
  label.setAttribute("for", "forumcadre");
  block.append(label, field);
  return field;
}

// L'URL RESTE `leaderboard/alias` alors que le pseudonyme ne sert plus qu'au
// classement : elle vit dans le cache des pages des étudiants, et la renommer
// ne rachèterait rien. Même raisonnement que `/tp/<id>.json`.
function aliasBlock() {
  const box = node("div", "");
  box.append(node("label", "", "Mon nom masqué (tiré au hasard)"));
  const line = node("p", "aliasrow");
  line.append(node("b", "alias-value", profil.alias || "pas encore tiré"));
  line.append(button(profil.alias ? "Un autre nom" : "Tirer un nom", "nav",
    async () => {
      const answer = await ctester.compte.sendJson("leaderboard/alias", "POST", {});
      annonce = answer && answer.ok ? "Nouveau pseudonyme."
                                    : "Le pseudonyme n'a pas pu être changé.";
      await chargerProfil();
      renderPanel();
    }));
  box.append(line);
  box.append(node("p", "aide", "C'est sous ce nom que tu apparais dans le chat "
    + "et au classement tant que tu n'affiches pas le tien. Il est tiré d'une "
    + "liste fermée — personne ne peut écrire ce qu'il veut."));
  // CE QUE « RÉTROACTIF » VEUT DIRE, ÉCRIT AVANT LE CLIC. La dernière ligne
  // de profil FAIT le profil, donc changer de nom renomme aussi l'auteur de
  // tous ses messages passés. C'est une propriété (quelqu'un qui se sent
  // exposé se détache de son historique d'un clic), mais elle surprend si on
  // ne la dit pas.
  box.append(node("p", "aide", "Le changer remplace ton nom partout, y compris "
    + "sur tes messages déjà publiés."));
  return box;
}

// WHAT THE OTHERS WILL SEE, drawn from the FORM's current values and not from
// what is saved: the preview has to answer "if I tick this, what changes?",
// which a preview of the saved state cannot do.
//
// IT APPLIES THE SAME RULES AS THE SERVER: an unticked box shows nothing, and
// a ticked box over an empty field shows nothing either -- which is exactly
// what `forum_pseudo`/`forum_groupe` enforce. A preview promising more than
// the server delivers would be worse than no preview at all.
function drawPlatePreview(box, form) {
  box.innerHTML = "";
  const plate = node("div", "plate plan"
    + (form.plate_frame ? " frame-" + form.plate_frame : ""));
  const name = form.display_name_public ? String(form.display_name || "").trim() : "";
  // LE REPLI EST L'ALIAS, PAS « PARTICIPANT ». L'encart promet « voilà
  // exactement ce que les autres verront » : afficher un mot que personne ne
  // verra en ferait un aperçu qui ment, ce qui est pire que pas d'aperçu.
  const masque = (profil && profil.alias) || "Participant";
  const line = node("div", "row");
  line.append(node("span", "initials", initialsOf(name || masque)));
  line.append(node("span", "name", name || masque));
  plate.append(line);
  const tags = node("div", "tags");
  const group = form.group_number_public ? String(form.group_number || "").trim() : "";
  if (group) tags.append(node("span", "tag", groupNumber(group)));
  if (form.badges_public) tags.append(node("span", "tag accent", "écussons visibles"));
  if (tags.children.length) plate.append(tags);
  box.append(plate);
}

function initialsOf(name) {
  const words = String(name || "").trim().split(/\s+/).filter(Boolean);
  return words.slice(0, 2).map(w => w[0].toUpperCase()).join("");
}

function closeRow() {
  const row = node("div", "row");
  row.append(button("Fermer", "nav", closeIdentity));
  return row;
}

function closeIdentity() {
  annonce = "";
  champPseudo = null;
  $("identitepanneau").hidden = true;
}

function renderPanel() {
  const box = $("identitepanneau");
  box.innerHTML = "";
  box.append(myIdentity());
  box.hidden = false;
}

function checkbox(id, text, checked) {
  const row = node("label", "coche");
  row.setAttribute("for", id);
  const box = node("input");
  box.id = id;
  box.type = "checkbox";
  box.checked = !!checked;
  row.append(box, node("span", "", text));
  return [box, row];
}

function exercisePicker() {
  const block = node("div", "bloc");
  const label = node("label", "", "Exercice");
  label.setAttribute("for", "forumex");
  const menu = document.createElement("select");
  menu.id = "forumex";
  for (const tp of ctester.catalogue()) {
    const option = document.createElement("option");
    option.value = tp.id;
    option.textContent = tp.group + " — " + (tp.short || tp.label);
    menu.append(option);
  }
  // LE MENU PORTE L'EXERCICE, `exercice` PORTE LA CLÉ DU FIL. Les deux ne
  // sont plus la même chaîne depuis que le chat existe : `cleFil()` traduit,
  // et c'est le seul endroit qui le fait.
  const base = exercice.startsWith(CHAT_PREFIX)
    ? exercice.slice(CHAT_PREFIX.length) : exercice;
  menu.value = base;
  menu.addEventListener("change", async () => {
    annonce = "";
    await ouvrirFil(modeFil === "chat-general" ? "chat-ex" : modeFil,
                    menu.value);
  });
  block.append(label, menu);
  return block;
}

// LES TROIS ESPACES, ET LEUR DIFFÉRENCE EST ÉCRITE. Un étudiant doit savoir
// avant d'écrire si ce qu'il tape est public : c'est le contrat que le chat
// passe avec lui, et le cacher derrière un onglet muet le romprait.
function filPicker() {
  const block = node("div", "bloc");
  block.append(node("h3", "soustitre", "Où écrire"));
  const row = node("div", "row");
  const onglets = [
    ["chat-ex", "Chat de l'exercice"],
    ["chat-general", "Chat général"],
    ["forum", "Forum de l'exercice"],
  ];
  for (const [mode, titre] of onglets) {
    row.append(button(titre, modeFil === mode ? "" : "nav",
                      () => ouvrirFil(mode)));
  }
  block.append(row);
  block.append(node("p", "aide", estChat
    ? "Ici tout est public : ton message est lisible par tous les comptes du cours, sous ton nom masqué."
    : "Ici tu peux poser une question privée (« Je suis bloqué ici ») que seul le chargé de lab lira."));
  return block;
}

async function ouvrirFil(mode, base) {
  modeFil = mode;
  annonce = "";
  permalien = null;
  if (base !== undefined) exerciceForce = base;
  await charger(cleFil());
  brancherSocket();
  dessiner();
}

// LE CONTENEUR EST STABLE, SON CONTENU CHANGE. C'est ce qui permet de poser
// des propositions pendant la frappe SANS redessiner le formulaire : un
// `dessiner()` recréerait le `<textarea>` et renverrait le curseur à la fin,
// au milieu d'une phrase.
function remplirDoublons(box) {
  box.innerHTML = "";
  if (!doublons || !doublons.length) return;
  const bloc = node("div", "bloc second");
  bloc.append(node("h4", "soustitre", "Peut-être déjà demandé"));
  bloc.append(resultatsListe(doublons, ""));
  bloc.append(node("p", "aide", "Si ce n'est pas ta question, publie la tienne : c'est fait pour."));
  box.append(bloc);
}

function majDoublons() {
  const box = $("forumdoublons");
  if (box) remplirDoublons(box);
}

// LE DÉBOUNCE EST TOUTE LA GESTION DE CHARGE DE CETTE FONCTION. La route est
// une lecture sur index, sans quota (un cooldown de dix secondes la rendrait
// inutile pendant la frappe, c'est-à-dire au seul moment où elle sert) : ce
// qui la borne est de ne pas partir à chaque touche.
function guetterDoublon() {
  if (repondA) return;
  if (minuterieDoublon) clearTimeout(minuterieDoublon);
  const texte = saisie;
  if (texte.trim().length < 8) { doublons = null; return; }
  minuterieDoublon = setTimeout(async () => {
    const trouves = await chercher(texte);
    doublons = trouves.slice(0, 3);
    // ON NE REDESSINE QUE SI ON A QUELQUE CHOSE À MONTRER, et jamais le
    // formulaire entier : redessiner pendant la frappe rendrait le champ et
    // ferait perdre le curseur.
    if (doublons.length) majDoublons();
  }, 400);
}

// LA RECHERCHE ET LA DÉTECTION DE DOUBLON SONT LA MÊME ROUTE. Ici c'est
// l'accès à l'historique : un message d'il y a trois semaines n'est dans la
// fenêtre d'aucun fil, donc sans ça il est inatteignable.
function searchBox() {
  const block = node("div", "bloc");
  block.append(node("h3", "soustitre", "Chercher"));
  const field = document.createElement("input");
  field.type = "search";
  field.id = "forumrecherche";
  field.placeholder = "un mot de la question…";
  field.value = recherche;
  field.addEventListener("input", () => { recherche = field.value; });
  const go = async () => {
    resultats = await chercher(recherche);
    dessiner();
    const again = $("forumrecherche");
    if (again && again.focus) again.focus();
  };
  field.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  block.append(field);
  block.append(button("Chercher", "nav", go));
  if (resultats !== null) block.append(resultatsListe(resultats, "Aucun message ne correspond."));
  return block;
}

// UN RÉSULTAT S'OUVRE PAR LE PERMALIEN, jamais en devinant son fil : la
// conversation entière arrive du serveur, filtrée par les mêmes règles que le
// fil.
function resultatsListe(rows, vide) {
  if (!rows.length) return node("p", "aide", vide);
  const list = node("ul", "fil");
  for (const r of rows) {
    const item = document.createElement("li");
    item.className = "message";
    const head = node("p", "qui");
    head.append(node("span", "auteur", filLisible(r.exercise_id)));
    if (r.replies) head.append(node("span", "tag accent",
      r.replies > 1 ? r.replies + " réponses" : "1 réponse"));
    else head.append(node("span", "tag", "sans réponse"));
    if (r.upvotes) head.append(node("span", "tag", r.upvotes + " × même question"));
    item.append(head);
    // `textContent` POUR UN EXTRAIT : il ne passe pas par Markdown, donc pas
    // par l'assainisseur, donc il ne doit jamais devenir du HTML.
    item.append(node("p", "extrait", r.extrait));
    item.append(button("Ouvrir", "nav", () => ouvrirPermalien(r.id)));
    list.append(item);
  }
  return list;
}

function filLisible(cle) {
  if (cle === CHAT_GENERAL) return "Chat général";
  const nu = cle.startsWith(CHAT_PREFIX) ? cle.slice(CHAT_PREFIX.length) : cle;
  const trouve = (ctester.catalogue() || []).find((t) => t.id === nu);
  const nom = trouve ? (trouve.short || trouve.label) : nu;
  return cle.startsWith(CHAT_PREFIX) ? "Chat — " + nom : "Forum — " + nom;
}

async function chercher(terms) {
  if (!ctester.compte || !String(terms || "").trim()) return [];
  const answer = await ctester.compte.getJson(
    "forum/search?q=" + encodeURIComponent(terms));
  return answer && Array.isArray(answer.results) ? answer.results : [];
}

async function ouvrirPermalien(id) {
  const answer = await ctester.compte.getJson(
    "forum/message?id=" + encodeURIComponent(id));
  if (!answer || !Array.isArray(answer.messages)) {
    annonce = "Cette conversation n'est pas disponible.";
    dessiner();
    return;
  }
  fil = answer.messages;
  estChat = !!answer.chat;
  permalien = id;
  threadStateInfo = null;
  dessiner();
}

// WHICH FORM IS OPEN. "question" is the ordinary public post the forum has
// always had; "bloque" is design 1g's help request, which is PRIVATE by
// default and carries a step. One state, so the two can never be half-open at
// once.
let composeMode = "question";
let chosenStep = "";
let chosenBlockedKind = "";
let chosenVisibility = "private";

function postForm() {
  const block = node("div", "bloc");
  // RÉPONDRE À QUELQU'UN SE DIT AVANT D'ÉCRIRE. Sans cette bande, on tape une
  // réponse en croyant ouvrir une nouvelle question -- et l'inverse.
  if (repondA) {
    const bande = node("div", "row");
    bande.append(node("span", "tag accent", "Réponse à un message"));
    bande.append(button("Annuler la réponse", "nav", () => {
      repondA = null;
      dessiner();
    }));
    block.append(bande);
  }
  const tabs = node("div", "tabs");
  // DANS UN CHAT IL N'Y A QU'UNE FAÇON D'ÉCRIRE, parce qu'il n'y a rien de
  // privé à choisir. Les deux onglets appartiennent au forum : les montrer
  // ici promettrait une question privée que le serveur refuserait.
  const modes = estChat || repondA
    ? []
    : [["question", "Poser une question"], ["bloque", "Je suis bloqué ici"]];
  for (const pair of modes) {
    const tab = button(pair[1], "nav" + (composeMode === pair[0] ? " on" : ""), () => {
      if (composeMode === pair[0]) return;
      composeMode = pair[0];
      dessiner();
    });
    tab.setAttribute("aria-pressed", composeMode === pair[0] ? "true" : "false");
    tabs.append(tab);
  }
  block.append(tabs);

  const stuck = composeMode === "bloque" && !estChat && !repondA;
  if (stuck) {
    // WHAT GOES WITH THE QUESTION, SAID BEFORE IT IS WRITTEN. The exercise
    // and the step travel; THE CODE DOES NOT, and that is what keeps the
    // charter tenable -- there is no field here that could carry a source
    // file, and the sentence says so where it will be read.
    block.append(node("p", "aide", "Ta question partira avec l'exercice et "
      + "l'étape. Ton code, lui, ne part pas — décris ce que tu observes."));
    block.append(stepPicker());
    block.append(blockedPicker());
  }

  const label = node("label", "", (stuck
      ? "Ce que tu as déjà essayé"
      : repondA ? "Ta réponse"
      : estChat ? "Ta question — personne ne juge, et tu es masqué"
      : "Ta question ou ton explication")
    + (maxTexte ? " (" + maxTexte + " caractères au plus)" : ""));
  label.setAttribute("for", "forumtexte");
  zone = document.createElement("textarea");
  zone.id = "forumtexte";
  zone.value = saisie;
  zone.setAttribute("rows", "4");
  if (stuck) zone.placeholder = "J'ai vérifié le type de ma variable, mais…";
  block.append(label, zone);

  block.append(node("p", "aide", renderAvailable
    ? "Mise en forme simple : **gras**, *italique*, listes, > citation, `code court`. Le HTML n'est jamais interprété."
    : "Le rendu enrichi n'a pas pu être chargé : ton message part quand même, et il s'affiche en texte brut."));

  if (renderAvailable) {
    // THE PREVIEW IS NOT `aria-live`. Announcing every keystroke to a screen
    // reader would make the field unusable; the preview is a labeled
    // region, to be read whenever one wants.
    const previewTitle = node("h4", "soustitre", "Aperçu");
    previewTitle.id = "forumapercutitre";
    apercu = node("div", "md apercu");
    apercu.setAttribute("role", "region");
    apercu.setAttribute("aria-labelledby", "forumapercutitre");
    rendreMarkdown(apercu, saisie);
    zone.addEventListener("input", () => {
      saisie = zone.value;
      rendreMarkdown(apercu, saisie);
      guetterDoublon();
    });
    block.append(previewTitle, apercu);
  } else {
    apercu = null;
    zone.addEventListener("input", () => {
      saisie = zone.value;
      guetterDoublon();
    });
  }

  // « QUELQU'UN A DÉJÀ DEMANDÉ ÇA », ET ON NE FAIT QUE LE PROPOSER. Jamais
  // bloquant : décider à la place de quelqu'un que sa question est un doublon
  // est exactement la façon de le faire taire, ce que tout ceci cherche à
  // éviter. Pas sur une réponse -- on répond à un message précis.
  if (!repondA) {
    const box = node("div", "");
    box.id = "forumdoublons";
    block.append(box);
    remplirDoublons(box);
  }

  if (stuck) block.append(visibilityPicker());

  block.append(button(repondA ? "Répondre" : "Publier", "", () => {
    saisie = zone.value;
    const text = saisie;
    // UNE RÉPONSE NE PORTE NI ÉTAPE NI VISIBILITÉ : elle hérite de la
    // conversation qu'elle rejoint, et le serveur REFUSE qu'elle en porte
    // une. Les envoyer quand même ferait un 400 que personne ne comprendrait.
    const extra = repondA ? { reply_to: repondA }
      : stuck ? { step: chosenStep || "statement",
                  blocked_kind: chosenBlockedKind || undefined,
                  visibility: chosenVisibility } : {};
    if (ctester.sessionGet(CHARTE_VUE)) publier(text, extra);
    else showGuidelines(() => publier(text, extra));
  }));
  return block;
}

// THE STEP AND THE KIND COME FROM THE SERVER'S CLOSED LISTS. Radio buttons
// rather than a free field, because these are exactly what the instructor's
// aggregate groups by: six spellings of "compilation" would read as six
// different problems on the morning that count matters.
function stepPicker() {
  const box = node("div", "choix");
  box.append(node("label", "", "Où ça coince"));
  for (const step of steps) {
    const row = node("label", "coche");
    const input = node("input");
    input.type = "radio";
    input.name = "forumetape";
    input.checked = chosenStep ? chosenStep === step.id : step === steps[0];
    if (input.checked) chosenStep = step.id;
    input.addEventListener("change", () => { chosenStep = step.id; });
    row.append(input, node("span", "", step.title));
    box.append(row);
  }
  return box;
}

function blockedPicker() {
  const box = node("div", "choix");
  box.append(node("label", "", "Ce qui bloque"));
  for (const kind of blockedKinds) {
    const row = node("label", "coche");
    const input = node("input");
    input.type = "radio";
    input.name = "forumblocage";
    input.checked = chosenBlockedKind ? chosenBlockedKind === kind.id : kind === blockedKinds[0];
    if (input.checked) chosenBlockedKind = kind.id;
    input.addEventListener("change", () => { chosenBlockedKind = kind.id; });
    row.append(input, node("span", "", kind.title));
    box.append(row);
  }
  return box;
}

// PRIVATE IS THE DEFAULT, AND IT IS THE FIRST OPTION. Asking for help should
// not require deciding, in the same breath, to say so publicly -- and the
// second option says what one gains by choosing it, since that is the whole
// reason to.
function visibilityPicker() {
  const box = node("div", "choix");
  box.append(node("label", "", "Qui la voit"));
  const options = [
    ["private", "Seulement le chargé de lab", "par défaut"],
    ["group", "Aussi les autres de mon groupe", "quelqu'un peut répondre tout de suite"],
  ];
  for (const option of options) {
    const row = node("label", "coche");
    const input = node("input");
    input.type = "radio";
    input.name = "forumvisibilite";
    input.checked = chosenVisibility === option[0];
    input.addEventListener("change", () => { chosenVisibility = option[0]; });
    row.append(input, node("span", "", option[1]),
               node("span", "aide", "— " + option[2]));
    box.append(row);
  }
  box.append(node("p", "aide", "Tu pourras la rendre visible au groupe plus "
    + "tard, en un clic, sans la republier."));
  return box;
}

// THE READER'S TIME, NOT THE SERVER'S. The server sends the instant in UTC
// ("...T18:45Z"); only the browser knows which timezone to read it in. A
// value that cannot be parsed back displays as-is -- an old message beats an
// "Invalid Date".
function localTime(instant) {
  const d = new Date(instant);
  if (isNaN(d.getTime())) return String(instant);
  return d.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
}

function messageBody(text) {
  const body = node("div", "texte md");
  rendreMarkdown(body, text);
  return body;
}

// A MESSAGE (designs 1f and 1g). Four things were added to it, and each one
// is a state the reader can act on rather than a decoration:
//
//   * "réponse retenue" -- the answer a moderator stands behind. It is drawn
//     from the journal, so pinning EDITS NOTHING: the message is immutable,
//     which is what keeps a report readable.
//   * "Ça m'a aidé" -- a usefulness counter, deduplicated per account by the
//     database. It grants NO XP: a message written to be upvoted is a message
//     written for the counter.
//   * "privée" / "ouverte a mon groupe" -- who can read a "bloqué ici".
//   * "Rendre visible à mon groupe" -- the ONE transition, and only on one's
//     own private message. The server refuses the reverse; this button simply
//     does not offer it.
function messageItem(m) {
  const item = document.createElement("li");
  item.className = "message"
    + (m.retained ? " retenue" : "")
    + (m.visibility === "private" ? " privee" : "");
  // THE AUTHOR IS A WORD, NOT AN ID: "Vous", "Participant" or "Enseignant",
  // derived by the server. Nothing here lets two messages be tied back to
  // the same student.
  const head = node("p", "qui");
  if (m.retained) head.append(node("span", "tag accent", "réponse retenue"));
  head.append(node("span", "auteur", m.author));
  if (m.group) head.append(node("span", "groupe", groupNumber(m.group)));
  const when = node("time", "quand", localTime(m.created_at));
  when.setAttribute("datetime", String(m.created_at).replace(" ", "T"));
  head.append(when);
  // EVERY STATE IS SPELLED OUT, not only tinted: a state that only reads
  // through color does not read at all for some people.
  if (m.hidden) head.append(node("span", "etat", "masqué"));
  if (m.visibility === "private") head.append(node("span", "tag", "privée"));
  if (m.visibility === "group") head.append(node("span", "tag", "ouverte à ton groupe"));
  if (m.step) head.append(node("span", "tag", stepLabel(m.step)));
  item.append(head, messageBody(m.text));

  const actions = node("div", "row");
  if (m.mine) {
    actions.append(button("Supprimer mon message", "nav", () => supprimer(m.id)));
    // THE ESCAPE HATCH OF DESIGN 1G: a private question nobody answered is a
    // question one can open to the group, in one click and without
    // republishing it. The reverse is not offered and not accepted.
    if (m.visibility === "private") {
      actions.append(button("Rendre visible à mon groupe", "", () => openToGroup(m.id)));
    }
  } else {
    // LE VOTE N'EST PAS OFFERT SUR SON PROPRE MESSAGE -- le serveur le refuse
    // en SQL, et un bouton qui échoue toujours est un bouton qui ment.
    //
    // SUR UNE QUESTION, +1 SE LIT « MOI AUSSI » ; SUR UNE RÉPONSE, « ÇA M'A
    // AIDÉ » ET SON CONTRAIRE. Le -1 n'est pas dessiné sur une racine, mais
    // ce n'est pas ce qui l'interdit : c'est le `WHERE` de l'instruction. Une
    // question ne peut donc pas être enterrée par un vote, ce qui est la
    // promesse d'un endroit fait pour ceux qui ont peur de demander.
    const estReponse = !!m.reply_to;
    const plus = estReponse ? "Ça m'a aidé" : "Moi aussi";
    actions.append(button(
      (m.my_vote === 1 ? "✓ " : "") + plus + (m.upvotes ? " (" + m.upvotes + ")" : ""),
      m.my_vote === 1 ? "" : "nav",
      () => voter(m.id, m.my_vote === 1 ? 0 : 1)));
    if (estReponse) {
      actions.append(button(
        (m.my_vote === -1 ? "✓ " : "") + "Ça m'a induit en erreur"
        + (m.downvotes ? " (" + m.downvotes + ")" : ""),
        "nav", () => voter(m.id, m.my_vote === -1 ? 0 : -1)));
    }
    actions.append(button("Signaler", "nav", () => signaler(m.id)));
  }
  // RÉPONDRE EST OFFERT SUR TOUT MESSAGE VISIBLE, y compris le sien : on
  // complète sa propre question sans en publier une seconde.
  actions.append(button("Répondre", "nav", () => repondreA(m.id)));
  if (m.mine && m.upvotes) {
    actions.append(node("span", "tag", m.upvotes + " personne"
      + (m.upvotes > 1 ? "s ont" : " a") + (m.reply_to ? " trouvé ça utile"
                                                       : " la même question")));
  }
  // ONLY WHAT IS DISPLAYED CAN BE REPORTED: the button only exists on a name
  // someone else chose. "Participant" cannot be reported, there is nothing
  // in it.
  if (m.reportable_name) {
    actions.append(button("Signaler le nom", "nav", () => signalerNom(m.id)));
  }
  if (moderateur) {
    actions.append(m.hidden
      ? button("Rétablir", "nav", () => moderer(m.id, "restore"))
      : button("Masquer", "nav", () => moderer(m.id, "hide")));
    // RETENIR N'ÉDITE RIEN. The action goes into the append-only journal and
    // the latest one wins -- so it is reversible, and it is journalled.
    actions.append(m.retained
      ? button("Ne plus retenir", "nav", () => moderer(m.id, "unretain"))
      : button("Retenir comme réponse", "nav", () => moderer(m.id, "retain")));
  }
  item.append(actions);
  return item;
}

// THE LABELS COME FROM THE SERVER, sent with the thread as a legend. A second
// copy here would drift from the closed list the aggregate groups by, and the
// copy that drifted would be the one the student reads.
function stepLabel(id) {
  const found = (steps || []).find(e => e.id === id);
  return found ? found.title : id;
}

function blockedLabel(id) {
  const found = (blockedKinds || []).find(b => b.id === id);
  return found ? found.title : id;
}

// THE THREAD'S STATE, as three counters the server derived from what THIS
// caller can see. Not a filter: with one thread per exercise there is nothing
// to filter, and showing it as tabs would promise a list that does not exist.
function threadState() {
  if (!threadStateInfo) return null;
  const row = node("div", "etatfil");
  const words = [["resolved", "résolue", "accent"],
                 ["answered", "répondue", "contour"],
                 ["unanswered", "sans réponse", ""]];
  for (const entry of words) {
    if (!threadStateInfo[entry[0]]) continue;
    row.append(node("span", "tag " + entry[2], entry[1]));
  }
  return row.children.length ? row : null;
}

function theThread() {
  const block = node("div", "bloc");
  block.append(node("h3", "soustitre", permalien ? "Une conversation" : "Le fil"));
  if (permalien) {
    // ON EST ARRIVÉ ICI PAR LA RECHERCHE. Le bouton de retour est la seule
    // sortie : sans lui, on lirait une conversation isolée sans savoir
    // comment revenir au fil qu'on regardait.
    block.append(button("Revenir au fil", "nav", async () => {
      permalien = null;
      await charger(cleFil());
      dessiner();
    }));
  }
  if (!fil.length) {
    block.append(node("p", "aide", estChat
      ? "Personne n'a encore écrit ici. Une question, même « bête », en débloque souvent plusieurs."
      : "Personne n'a encore écrit sur cet exercice. Une question bien posée en aide souvent plusieurs."));
    return block;
  }
  const state = threadState();
  if (state) block.append(state);
  const list = node("ul", "fil");
  // LES RÉPONSES SOUS LEUR RACINE. `reply_to` porte toujours la racine (le
  // serveur aplatit), donc il n'y a qu'un niveau à dessiner et aucune
  // récursion : un fil reste plat, ce qui est exactement pourquoi la colonne
  // est faite comme ça.
  const racines = fil.filter((m) => !m.reply_to);
  const parRacine = {};
  for (const m of fil) {
    if (!m.reply_to) continue;
    (parRacine[m.reply_to] = parRacine[m.reply_to] || []).push(m);
  }
  // RETENUES D'ABORD, puis chronologique. Un fil qu'on ouvre pour une réponse
  // ne doit pas faire défiler neuf messages avant celle que le cours assume
  // -- et le reste garde son ordre, une discussion lue en désordre n'étant
  // plus une discussion.
  const ordre = racines.filter((m) => m.retained)
                       .concat(racines.filter((m) => !m.retained));
  for (const racine of ordre) {
    list.append(messageItem(racine));
    for (const reponse of (parRacine[racine.id] || [])) {
      const item = messageItem(reponse);
      item.className += " reponse";
      list.append(item);
    }
  }
  block.append(list);
  return block;
}

function moderationQueue() {
  const block = node("div", "bloc second");
  block.append(node("h3", "soustitre", "Signalements"));
  if (signalements === null) {
    block.append(node("p", "rate",
      "La file de signalements n'a pas pu être lue."));
    return block;
  }
  if (!signalements.length) {
    block.append(node("p", "aide", "Aucun signalement en attente."));
    return block;
  }
  const list = node("ul", "fil");
  for (const s of signalements) {
    const item = document.createElement("li");
    item.className = "message";
    const head = node("p", "qui");
    head.append(node("span", "auteur", s.exercise_id));
    head.append(node("time", "quand", localTime(s.created_at)));
    head.append(node("span", "etat", s.report_count + " signalement"
      + (s.report_count > 1 ? "s" : "") + (s.hidden ? " — masqué" : "")));
    // SAME PIPELINE AS EVERYWHERE ELSE. A moderator reads exactly what a
    // student reads, sanitized the same way: a moderation view that
    // rendered raw HTML "to see what's inside" would be the site's easiest
    // page to attack, and the one where an attack would pay off the most.
    item.append(head, messageBody(s.text));
    const actions = node("div", "row");
    actions.append(s.hidden
      ? button("Rétablir", "nav", () => moderer(s.id, "restore"))
      : button("Masquer", "nav", () => moderer(s.id, "hide")));
    item.append(actions);
    list.append(item);
  }
  block.append(list);
  return block;
}

// REPORTED NAMES, next to reported messages but not inside them: it is not
// the message that is the problem, it is the name, and the action is not
// the same.
function nameQueue() {
  const block = node("div", "bloc second");
  block.append(node("h3", "soustitre", "Noms signalés"));
  if (nomsSignales === null) {
    block.append(node("p", "rate", "La file des noms n'a pas pu être lue."));
    return block;
  }
  if (!nomsSignales.length) {
    block.append(node("p", "aide", "Aucun nom signalé."));
    return block;
  }
  const list = node("ul", "fil");
  for (const n of nomsSignales) {
    const item = document.createElement("li");
    item.className = "message";
    const head = node("p", "qui");
    head.append(node("span", "auteur", n.display_name || "(nom déjà effacé)"));
    if (n.group_number) head.append(node("span", "groupe", groupNumber(n.group_number)));
    head.append(node("time", "quand", localTime(n.created_at)));
    head.append(node("span", "etat", n.report_count + " signalement"
      + (n.report_count > 1 ? "s" : "")));
    item.append(head);
    const actions = node("div", "row");
    actions.append(button("Effacer le nom", "nav", () => effacerNom(n.id)));
    item.append(actions);
    list.append(item);
  }
  block.append(list);
  return block;
}

function dessiner() {
  const box = $("vueforum");
  box.innerHTML = "";
  zone = null;
  apercu = null;
  champPseudo = null;
  titre = node("h2", "", "Discussions");
  titre.id = "forumtitre";
  titre.tabIndex = -1;
  box.append(titre);
  // CE QUE L'ÉTUDIANT DOIT SAVOIR AVANT D'ÉCRIRE : que c'est public, et sous
  // quel nom il apparaît. Le second point est la raison d'être de tout ceci,
  // donc il est dit ici et pas seulement dans un panneau qu'on n'ouvre pas.
  const masque = (profil && profil.alias) || "un nom masqué";
  box.append(node("p", "aide", "Visible par les autres comptes connectés du "
    + "cours. Ce n'est pas une note, et ça n'a aucun effet sur tes progrès. "
    + "Tu y apparais sous « " + masque + " » — ton vrai nom n'apparaît que si "
    + "tu l'affiches dans Compte → Mon identité."));

  // THE CONTEXT WE JUST LOST. Opening discussions clears the workbench: we
  // arrive here to talk about a verdict that is no longer visible. Recalling
  // it avoids a round trip to copy it back -- and it is the first thing
  // we'll be asked in the thread.
  const last = ctester.dernierVerdict();
  if (last && last.exercice === exercice) {
    const reminder = node("p", "rappel");
    reminder.append(node("span", "quoi", "Ton dernier test sur cet exercice : "));
    reminder.append(node("b", "", last.titre));
    box.append(reminder);
  }
  const status = node("p", "annonce", annonce);
  status.setAttribute("aria-live", "polite");
  box.append(status);

  // TWO COLUMNS ON A LARGE SCREEN, a single one on a small one, and the CSS
  // grid decides: what one writes on the left, what one reads on the
  // right. Stacked, the thread used to start below three panels and left
  // two thirds of the screen empty.
  const left = node("div", "colonne");
  const right = node("div", "colonne large");
  box.append(left, right);

  left.append(filPicker());
  if (ctester.catalogue().length && modeFil !== "chat-general") {
    left.append(exercisePicker());
  }

  const rules = node("div", "bloc second");
  rules.append(node("h3", "soustitre", "Ce qui se publie ici"));
  rules.append(guidelinesList());
  rules.append(node("p", "aide", "Modération humaine : rien n'est vérifié automatiquement. Signale plutôt que de répondre à une fuite."));
  left.append(rules);

  if (fil === null) {
    // WE DO NOT INVENT AN EMPTY THREAD. "No messages" during an outage
    // tells someone nobody answered them, and that would be false.
    right.append(node("p", "rate", erreur));
    return;
  }
  left.append(postForm());
  right.append(searchBox());
  right.append(theThread());
  // MODERATION IS NO LONGER RENDERED HERE. What remains is a door to it,
  // visible only to a moderator.
  if (moderateur) right.append(moderationDoor());
}

function moderationDoor() {
  const block = node("div", "bloc second");
  block.append(node("h3", "soustitre", "Modération"));
  const count = (signalements || []).length + (nomsSignales || []).length;
  const stuck = ((helpRows || {}).rows || []).reduce((n, r) => n + r.people, 0);
  block.append(node("p", "", count
    ? count + (count > 1 ? " éléments signalés" : " élément signalé")
      + " à examiner."
    : "Rien de signalé pour l'instant."));
  if (stuck) {
    block.append(node("p", "", stuck > 1
      ? stuck + " personnes ont signalé être bloquées."
      : "1 personne a signalé être bloquée."));
  }
  const openButton = node("button", "", "Ouvrir la modération");
  openButton.type = "button";
  openButton.addEventListener("click", () => basculerModeration());
  block.append(openButton);
  return block;
}

// "QUI A BESOIN D'AIDE" (design 1h). COUNTS AND STEPS, NEVER PEOPLE: no
// name, no text, no code -- a number is what says where to walk in the room,
// and six people on the same conversion is one explanation at the board
// rather than six replies.
//
// PRIVATE QUESTIONS ARE COUNTED, NOT SHOWN. Their author is the only one who
// can open them; this table says a number exists, which is exactly what the
// student's form promised ("seulement le chargé de lab").
function helpQueue() {
  const block = node("div", "bloc");
  block.append(node("h3", "soustitre", "Qui a besoin d'aide"));
  if (helpRows === null) {
    // NOT "personne n'est bloqué": during an outage those are opposite
    // claims, and the wrong one sends an instructor home.
    block.append(node("p", "rate", "Le tableau d'aide n'a pas pu être lu."));
    return block;
  }
  block.append(node("p", "aide", "Agrégé par exercice et par étape sur les "
    + helpRows.hours + " dernières heures. Aucun code, aucun nom : un compte de "
    + "personnes suffit pour savoir où aller dans le local."));
  if (!helpRows.rows.length) {
    block.append(node("p", "aide", "Personne n'a signalé être bloqué pour l'instant."));
    return block;
  }
  const table = document.createElement("table");
  table.className = "rank-table";
  const head = document.createElement("tr");
  const labels = ["Exercice", "Où ça coince", "Personnes", "Ouvertes au groupe", "Depuis"];
  for (const label of labels) head.append(node("th", "", label));
  table.append(head);
  for (const row of helpRows.rows) {
    const tr = document.createElement("tr");
    tr.append(node("td", "", exerciseLabel(row.exercise_id)));
    tr.append(node("td", "", stepLabel(row.step)
      + (row.blocked_kind ? " — " + blockedLabel(row.blocked_kind) : "")));
    tr.append(node("td", "num", String(row.people)));
    // "0 ouvertes" IS INFORMATION, not an empty cell: it says every one of
    // them is private, so nobody in the room can answer them but the
    // instructor.
    tr.append(node("td", "num", row.opened + " sur " + row.people));
    tr.append(node("td", "", localTime(row.since)));
    table.append(tr);
  }
  block.append(table);
  block.append(node("p", "aide", "Une question privée reste privée : seul son "
    + "auteur peut l'ouvrir à son groupe. Ce tableau les compte toutes, parce "
    + "que c'est le compte qui dit où aller."));
  return block;
}

// The exercise's own words rather than its id, read from the catalog the core
// already loaded. An id nobody recognizes is a row nobody can act on.
function exerciseLabel(id) {
  const found = ctester.catalogue().find(t => t.id === id);
  return found ? (found.label || found.short || id) : id;
}

// THE MODERATION SCREEN, kept apart. It has no business in a student's
// path, and the instructor opening it does not need to go through a thread
// to get there.
// LES QUESTIONS LES PLUS VOTÉES, ET SEULEMENT POUR L'ENSEIGNANT. Les
// étudiants ne voient aucun palmarès : un compteur public sur ce que chacun a
// demandé est le contraire de ce que le chat cherche à obtenir.
//
// LE « MOI AUSSI » EST CE QUI RÉPOND À « QU'EST-CE QUI BLOQUE LA CLASSE ? »
// sans compter personne : c'est un nombre par question, pas un nombre par
// étudiant.
function topQueue() {
  const block = node("div", "bloc");
  block.append(node("h3", "soustitre", "Questions du moment"));
  if (!topRows) {
    block.append(node("p", "rate", "Le classement des questions n'a pas pu être lu."));
    return block;
  }
  const rows = (topRows.rows || []).filter((r) => r.upvotes || !r.replies);
  if (!rows.length) {
    block.append(node("p", "aide", "Rien qui ressorte sur les dernières "
      + topRows.hours + " heures."));
    return block;
  }
  const list = node("ul", "fil");
  for (const r of rows.slice(0, 10)) {
    const item = document.createElement("li");
    item.className = "message";
    const head = node("p", "qui");
    head.append(node("span", "auteur", filLisible(r.exercise_id)));
    if (r.upvotes) {
      head.append(node("span", "tag accent", r.upvotes + " × « moi aussi »"));
    }
    head.append(node("span", "tag", r.replies
      ? (r.replies > 1 ? r.replies + " réponses" : "1 réponse")
      : "sans réponse"));
    if (r.visibility !== "thread") head.append(node("span", "tag", "privée"));
    if (r.step) head.append(node("span", "tag", stepLabel(r.step)));
    item.append(head);
    // `textContent` : ce texte vient d'un étudiant et ne passe pas par
    // l'assainisseur -- il ne doit donc jamais devenir du HTML.
    item.append(node("p", "extrait", r.text));
    item.append(button("Ouvrir la conversation", "nav", async () => {
      await basculer();
      await ouvrirPermalien(r.id);
    }));
    list.append(item);
  }
  block.append(list);
  block.append(node("p", "aide", "Sur les dernières " + topRows.hours
    + " heures. Aucun nom, aucun compte : un nombre par question."));
  return block;
}

function dessinerModeration() {
  const box = $("vuemoderation");
  box.innerHTML = "";
  const head = node("h2", "", "Modération");
  head.id = "moderationtitre";
  head.tabIndex = -1;
  box.append(head);
  const status = node("p", "annonce", annonce);
  status.setAttribute("aria-live", "polite");
  box.append(status);
  if (!moderateur) {
    box.append(node("p", "rate", "Cette page est réservée à la modération."));
    return;
  }
  // THE AGGREGATE COMES FIRST: during a lab it is the actionable half, and
  // the report queue is the one that can wait ten minutes.
  box.append(topQueue(), helpQueue(), moderationQueue(), nameQueue());
}

async function basculerModeration() {
  if (ctester.vue() === "moderation") { await basculer(); return; }
  await charger(exercice || cleFil());
  dessinerModeration();
  ctester.afficherVue("moderation");
  const head = $("moderationtitre");
  if (head && head.focus) head.focus();
}

// --- Le direct ----------------------------------------------------------------
// LA SOCKET EST UNE SONNETTE. Elle ne transporte aucun message : le serveur
// dit « du neuf », on relit le fil par HTTP, et `can_see()` s'applique par
// lecteur exactement comme d'habitude. Rien de la règle de visibilité ne vit
// de ce côté-ci.
//
// DÉGRADER, JAMAIS BLOQUER : socket morte, le fil se recharge sur action
// comme avant. C'est l'inverse de `team.js`, où l'absence de Yjs doit
// verrouiller l'éditeur -- là-bas un « au mieux » détruirait du travail, ici
// il ne coûte qu'un clic.

function debrancherSocket() {
  const ancienne = socket;
  socket = null;
  if (ancienne) {
    try { ancienne.close(); } catch (e) { /* déjà fermée */ }
  }
}

function brancherSocket() {
  debrancherSocket();
  if (!ctester.compte || !ctester.token() || !exercice) return;
  let ouverte;
  try {
    ouverte = new WebSocket(ctester.socketUrl("/forum/live"));
  } catch (e) {
    return;                       // pas de direct : le reste marche
  }
  socket = ouverte;
  const vise = exercice;
  ouverte.onopen = () => {
    socketRetard = 1000;
    // LE JETON PART DANS LA PREMIÈRE TRAME, jamais dans l'URL : un navigateur
    // ne peut pas poser d'`Authorization` sur une WebSocket, et un jeton en
    // paramètre d'URL est un jeton dans tous les journaux de proxy du chemin.
    try {
      ouverte.send(JSON.stringify(
        { t: "hello", token: ctester.token(), thread: vise }));
    } catch (e) { /* fermée entre-temps */ }
  };
  ouverte.onmessage = (ev) => {
    let trame = null;
    try { trame = JSON.parse(ev.data); } catch (e) { return; }
    if (!trame || trame.t !== "new") return;
    rafraichirFil();
  };
  ouverte.onclose = () => {
    if (socket !== ouverte) return;     // remplacée : rien à reconnecter
    socket = null;
    if (ctester.vue() !== "forum") return;
    setTimeout(brancherSocket, socketRetard);
    socketRetard = Math.min(socketRetard * 2, 30000);
  };
}

// LA SIGNATURE ÉVITE DE REDESSINER POUR RIEN. Sans elle, chaque sonnette
// recréerait le `<textarea>` et renverrait le curseur à la fin pendant qu'on
// tape. Elle porte ce qui change à l'écran : les identifiants, le masquage et
// les votes.
function signatureDuFil(messages) {
  return (messages || []).map(
    (m) => m.id + ":" + (m.hidden ? 1 : 0) + ":" + m.upvotes + ":"
           + m.downvotes + ":" + m.my_vote + ":" + (m.retained ? 1 : 0)).join(",");
}

async function rafraichirFil() {
  // LE FIL SEUL, pas `charger()` : celui-ci enchaîne la file de modération et
  // l'agrégat d'aide pour un modérateur, c'est-à-dire deux requêtes de plus à
  // chaque message publié dans la salle.
  if (permalien || !ctester.compte || !exercice) return;
  const avant = signatureDuFil(fil);
  const response = await ctester.compte.getJson(
    "forum?ex=" + encodeURIComponent(exercice));
  if (!response || !Array.isArray(response.messages)) return;
  if (signatureDuFil(response.messages) === avant) return;
  fil = response.messages;
  threadStateInfo = response.state || null;
  dessiner();
}

// --- Entry points -------------------------------------------------------------

async function basculer() {
  if (ctester.vue() === "forum") {
    // LA SOCKET MEURT AVEC LA VUE. Une salle par onglet ouvert et par fil,
    // gardée pendant qu'on code, serait la charge que le compteur de présence
    // a refusée pour de bonnes raisons.
    debrancherSocket();
    ctester.afficherVue("");
    return;
  }
  annonce = "";
  // THE LIBRARIES ARRIVE WITH THE VIEW, not with the page. A failure is not
  // blocking: `renderAvailable` stays false and everything displays as
  // plain text.
  try {
    await loadLibraries();
    renderAvailable = !!(window.marked && sanitizer());
  } catch (e) {
    renderAvailable = false;
  }
  await charger(cleFil());
  brancherSocket();
  dessiner();
  ctester.afficherVue("forum");
  // Focus follows the view: without this, tabbing would restart from the
  // top of the page and a screen reader would not announce the screen
  // change.
  if (titre && titre.focus) titre.focus();
}

function oublier() {
  // LA SOCKET PART AVEC LA SESSION. Sans ça, une déconnexion laisserait une
  // salle ouverte sur un jeton qui n'est plus valide.
  debrancherSocket();
  repondA = null;
  permalien = null;
  resultats = null;
  doublons = null;
  recherche = "";
  exerciceForce = "";
  fil = null;
  signalements = null;
  moderateur = false;
  erreur = "";
  annonce = "";
  saisie = "";
  profil = null;
  nomsSignales = null;
  topRows = null;
  // THE NEW STATE LEAVES TOO. `helpRows` is a moderator's aggregate and
  // `threadStateInfo` a thread's, both about people who are still here -- neither has
  // any business surviving the session that read them.
  helpRows = null;
  threadStateInfo = null;
  steps = [];
  blockedKinds = [];
  composeMode = "question";
  $("charte").hidden = true;
  // THE IDENTITY PANEL LEAVES WITH THE SESSION: it carries someone's name,
  // and signing out must not leave it open on screen.
  closeIdentity();
  const view = ctester.vue();
  if (view === "forum" || view === "moderation") ctester.afficherVue("");
}

// "MON IDENTITÉ" FROM THE COMPTE MENU, AND NOWHERE ELSE. This is a setting,
// not a reading step: in the thread's column, it used to push the charter
// and the post form further down on every visit. One single place, so one
// single place where visibility can drift from what the database says.
// Les équipes de ce compte, telles que `GET /team/mine` les rend. `null` veut
// dire « pas lues » (base muette, ou pas de session) et `[]` « aucune équipe » :
// les deux ne se disent pas pareil, et les confondre annoncerait « tu n'as pas
// d'équipe » à quelqu'un qui en a une, pendant une panne.
let equipes = null;

async function ouvrirIdentite() {
  if (!$("identitepanneau").hidden) { closeIdentity(); return; }
  annonce = "";
  await chargerProfil();
  renderPanel();
  if (champPseudo) champPseudo.focus();
}

ctester.forum = {
  basculer: basculer,
  basculerModeration: basculerModeration,
  ouvrirIdentite: ouvrirIdentite,
  oublier: oublier,
  fil: () => fil,
  // Exposées pour le harnais : le direct et la recherche sont les deux
  // chemins qu'un `node --check` ne peut pas éprouver.
  rafraichirFil: rafraichirFil,
  ouvrirFil: ouvrirFil,
  socketOuverte: () => !!socket,
  // Exposed for the test harness: this is THE function the whole safety of
  // rendering depends on, and it must be testable against real hostile
  // payloads rather than by code inspection.
  rendreMarkdown: rendreMarkdown,
  // Exposed for the same reason: the timezone is the kind of bug that only
  // shows up the moment someone reads "in four hours".
  quandLocal: localTime,
};
})(window.ctester);
