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
let erreur = "";
let annonce = "";
let exercice = "";
let saisie = "";
let titre = null;
let zone = null;
let apercu = null;
// The current view's "Nom affiché" field, so the Compte menu's "Mon
// identité" can bring focus to it. A REFERENCE, not a getElementById: the
// block does not always exist (a profile read failure).
let champPseudo = null;

// --- Network -----------------------------------------------------------------

function currentExercise() {
  const cat = ctester.catalogue();
  const target = exercice || ctester.exerciceOuvert() || ctester.exerciceChoisi();
  const found = cat.find(t => t.id === target) || cat[0];
  return found ? found.id : "";
}

const INDISPO = "Les discussions ne sont pas disponibles pour l'instant. "
              + "L'exercice et le bouton « Tester », eux, fonctionnent "
              + "normalement.";

async function charger(id) {
  fil = null;
  signalements = null;
  nomsSignales = null;
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
  moderateur = !!response.moderateur;
  maxTexte = response.max || 0;
  erreur = "";
  // The report queue is only ever requested by a moderator, and the server
  // refuses everyone else: this check just avoids a needless 403, it
  // protects nothing on its own.
  if (moderateur) {
    const queue = await ctester.compte.getJson("forum/moderation");
    signalements = queue && Array.isArray(queue.signalements)
      ? queue.signalements : null;
    nomsSignales = queue && Array.isArray(queue.noms) ? queue.noms : null;
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

async function publier(text) {
  const ok = await ecrire("forum", "POST", { exercise_id: exercice, texte: text },
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
  "forum/signalement", "POST", { id: id, quoi: "nom" },
  "Nom signalé. Un responsable du cours va le lire.", "Signalement impossible");

const effacerNom = (id) => ecrire(
  "forum/moderation", "POST", { id: id, action: "effacer-nom" },
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
  action === "masquer" ? "Message masqué." : "Message rétabli.",
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
function myIdentity() {
  const block = node("div", "");
  block.append(node("h2", "", "Mon identité"));
  if (annonce) block.append(node("p", "annonce", annonce));
  if (profil === null) {
    block.append(node("p", "rate", "Ton identité n'a pas pu être lue."));
    block.append(closeRow());
    return block;
  }

  const nameId = "forumpseudo";
  const nameLabel = node("label", "", "Nom affiché (facultatif)");
  nameLabel.setAttribute("for", nameId);
  const nameField = node("input");
  nameField.id = nameId;
  nameField.type = "text";
  nameField.autocomplete = "off";
  nameField.maxLength = profil.max_pseudo || 24;
  // RAUTHY'S SUGGESTION ONLY EVER PRE-FILLS, and only until a name has been
  // chosen. It is neither saved nor shown to others before a click on
  // "Enregistrer" with the box checked: someone's sign-in name does not get
  // published on its own.
  nameField.value = profil.pseudo || profil.suggestion || "";
  nameField.placeholder = "Participant";
  champPseudo = nameField;

  const groupId = "forumgroupe";
  const groups = Array.isArray(profil.groupes) ? profil.groupes : [];
  const groupValue = profil.groupe === null || profil.groupe === undefined
    ? "" : String(profil.groupe);
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

  const [showName, nameRow] = checkbox(
    "forumvoirnom", "Afficher mon nom dans les discussions",
    profil.pseudo_public);
  const [showGroup, groupRow] = checkbox(
    "forumvoirgroupe", "Afficher mon numéro de groupe",
    profil.groupe_public);

  block.append(nameLabel, nameField, groupLabel, groupField, nameRow, groupRow);
  // WHAT THE CHECKBOX DOES NOT COVER, and it must be said: the instructor
  // sees the group number at all times. Letting anyone believe otherwise
  // would be consent obtained the wrong way.
  if (!profil.pseudo && profil.suggestion) {
    block.append(node("p", "aide", "Nom proposé par ta connexion — modifie-le si tu veux, il ne s'affiche qu'une fois enregistré et coché."));
  }
  block.append(node("p", "aide", "Décoché, rien de tout ça n'apparaît aux "
    + "autres. L'enseignant, lui, voit toujours ton numéro de groupe — "
    + "jamais ton nom si tu ne l'affiches pas."));
  const row = node("div", "row");
  row.append(button("Enregistrer", "", () => enregistrerProfil({
    pseudo: nameField.value,
    groupe: groupField.value,
    pseudo_public: showName.checked,
    groupe_public: showGroup.checked,
  })));
  row.append(button("Fermer", "nav", closeIdentity));
  block.append(row);
  return block;
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
  menu.value = exercice;
  menu.addEventListener("change", async () => {
    annonce = "";
    await charger(menu.value);
    dessiner();
  });
  block.append(label, menu);
  return block;
}

function postForm() {
  const block = node("div", "bloc");
  block.append(node("h3", "soustitre", "Poser une question"));
  const label = node("label", "", "Ta question ou ton explication"
    + (maxTexte ? " (" + maxTexte + " caractères au plus)" : ""));
  label.setAttribute("for", "forumtexte");
  zone = document.createElement("textarea");
  zone.id = "forumtexte";
  zone.value = saisie;
  zone.setAttribute("rows", "4");
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
    });
    block.append(previewTitle, apercu);
  } else {
    apercu = null;
    zone.addEventListener("input", () => { saisie = zone.value; });
  }

  block.append(button("Publier", "", () => {
    saisie = zone.value;
    const text = saisie;
    if (ctester.sessionGet(CHARTE_VUE)) publier(text);
    else showGuidelines(() => publier(text));
  }));
  return block;
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

function messageItem(m) {
  const item = document.createElement("li");
  item.className = "message";
  // THE AUTHOR IS A WORD, NOT AN ID: "Vous", "Participant" or "Enseignant",
  // derived by the server. Nothing here lets two messages be tied back to
  // the same student.
  const head = node("p", "qui");
  head.append(node("span", "auteur", m.auteur));
  if (m.groupe) head.append(node("span", "groupe", groupNumber(m.groupe)));
  const when = node("time", "quand", localTime(m.cree_le));
  when.setAttribute("datetime", String(m.cree_le).replace(" ", "T"));
  head.append(when);
  // "Masqué" SPELLED OUT, not only in gray: a state that only reads through
  // color does not read at all for some people.
  if (m.masque) head.append(node("span", "etat", "masqué"));
  item.append(head, messageBody(m.texte));

  const actions = node("div", "row");
  if (m.mien) {
    actions.append(button("Supprimer mon message", "nav", () => supprimer(m.id)));
  } else {
    actions.append(button("Signaler", "nav", () => signaler(m.id)));
  }
  // ONLY WHAT IS DISPLAYED CAN BE REPORTED: the button only exists on a name
  // someone else chose. "Participant" cannot be reported, there is nothing
  // in it.
  if (m.nom_signalable) {
    actions.append(button("Signaler le nom", "nav", () => signalerNom(m.id)));
  }
  if (moderateur) {
    actions.append(m.masque
      ? button("Rétablir", "nav", () => moderer(m.id, "retablir"))
      : button("Masquer", "nav", () => moderer(m.id, "masquer")));
  }
  item.append(actions);
  return item;
}

function theThread() {
  const block = node("div", "bloc");
  block.append(node("h3", "soustitre", "Le fil"));
  if (!fil.length) {
    block.append(node("p", "aide", "Personne n'a encore écrit sur cet exercice. Une question bien posée en aide souvent plusieurs."));
    return block;
  }
  const list = node("ul", "fil");
  for (const m of fil) list.append(messageItem(m));
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
    head.append(node("span", "auteur", s.exercice_id));
    head.append(node("time", "quand", localTime(s.cree_le)));
    head.append(node("span", "etat", s.signalements + " signalement"
      + (s.signalements > 1 ? "s" : "") + (s.masque ? " — masqué" : "")));
    // SAME PIPELINE AS EVERYWHERE ELSE. A moderator reads exactly what a
    // student reads, sanitized the same way: a moderation view that
    // rendered raw HTML "to see what's inside" would be the site's easiest
    // page to attack, and the one where an attack would pay off the most.
    item.append(head, messageBody(s.texte));
    const actions = node("div", "row");
    actions.append(s.masque
      ? button("Rétablir", "nav", () => moderer(s.id, "retablir"))
      : button("Masquer", "nav", () => moderer(s.id, "masquer")));
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
    head.append(node("span", "auteur", n.pseudo || "(nom déjà effacé)"));
    if (n.groupe) head.append(node("span", "groupe", groupNumber(n.groupe)));
    head.append(node("time", "quand", localTime(n.cree_le)));
    head.append(node("span", "etat", n.signalements + " signalement"
      + (n.signalements > 1 ? "s" : "")));
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
  box.append(node("p", "aide", "Visible par les autres comptes connectés du cours. Ce n'est pas une note, et ça n'a aucun effet sur tes progrès. Tu y apparais comme « Participant » tant que tu n'as pas choisi de nom dans Compte → Mon identité."));

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

  if (ctester.catalogue().length) left.append(exercisePicker());

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
  right.append(theThread());
  // MODERATION IS NO LONGER RENDERED HERE. What remains is a door to it,
  // visible only to a moderator.
  if (moderateur) right.append(moderationDoor());
}

function moderationDoor() {
  const block = node("div", "bloc second");
  block.append(node("h3", "soustitre", "Modération"));
  const count = (signalements || []).length + (nomsSignales || []).length;
  block.append(node("p", "", count
    ? count + (count > 1 ? " éléments signalés" : " élément signalé")
      + " à examiner."
    : "Rien de signalé pour l'instant."));
  const openButton = node("button", "", "Ouvrir la modération");
  openButton.type = "button";
  openButton.addEventListener("click", () => basculerModeration());
  block.append(openButton);
  return block;
}

// THE MODERATION SCREEN, kept apart. It has no business in a student's
// path, and the instructor opening it does not need to go through a thread
// to get there.
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
  box.append(moderationQueue(), nameQueue());
}

async function basculerModeration() {
  if (ctester.vue() === "moderation") { await basculer(); return; }
  await charger(exercice || currentExercise());
  dessinerModeration();
  ctester.afficherVue("moderation");
  const head = $("moderationtitre");
  if (head && head.focus) head.focus();
}

// --- Entry points -------------------------------------------------------------

async function basculer() {
  if (ctester.vue() === "forum") { ctester.afficherVue(""); return; }
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
  await charger(currentExercise());
  dessiner();
  ctester.afficherVue("forum");
  // Focus follows the view: without this, tabbing would restart from the
  // top of the page and a screen reader would not announce the screen
  // change.
  if (titre && titre.focus) titre.focus();
}

function oublier() {
  fil = null;
  signalements = null;
  moderateur = false;
  erreur = "";
  annonce = "";
  saisie = "";
  profil = null;
  nomsSignales = null;
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
  // Exposed for the test harness: this is THE function the whole safety of
  // rendering depends on, and it must be testable against real hostile
  // payloads rather than by code inspection.
  rendreMarkdown: rendreMarkdown,
  // Exposed for the same reason: the timezone is the kind of bug that only
  // shows up the moment someone reads "in four hours".
  quandLocal: localTime,
};
})(window.ctester);
