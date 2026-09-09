// The leaderboard: a signed-in account's OPTIONAL view. Loaded ON CLICK,
// never before -- the anonymous visitor downloads none of it, and neither
// does a signed-in student who never opens it. Same contract as compte.js and
// progres.js, same reasons.
//
// ONE WAY: this file reads `window.ctester` and deposits its own entry into
// it; the core only ever knows it through `ctester.leaderboard`, never through
// an import.
//
// NOTHING IS COMPUTED HERE. Ranks, the gap to the row above, the cohort
// threshold and the divisions all arrive decided from `GET /leaderboard`. A
// page that ranked itself would be a page where one ranks oneself from the
// console -- and this is the one screen where that would be worth doing.
//
// NOBODY IS NAMED LAST, and that is the server's doing too: it only ever
// sends the top of the table plus one's own row. There is nothing here to
// truncate, because nothing more ever arrives.
(function (ctester) {
const $ = ctester.$;

let projection = null;
let error = "";
let annonce = "";
// "group" | "course". The scope is a request parameter, not a filter applied
// to a full table: the full table never comes down.
let scope = "group";

async function load() {
  if (!ctester.compte) {
    projection = null;
    error = "Reconnecte-toi pour voir le classement.";
    return;
  }
  // `?group=` N'EST HONORÉ QUE POUR UN MODÉRATEUR, et c'est le serveur qui
  // recalcule le rôle : l'envoyer depuis ici ne donne rien à un étudiant.
  const response = await ctester.compte.getJson(
    "leaderboard?scope=" + encodeURIComponent(scope)
    + (groupeVise === null ? "" : "&group=" + encodeURIComponent(groupeVise)));
  if (!response || typeof response.participating !== "boolean") {
    projection = null;
    error = "Le classement n'est pas disponible pour l'instant. L'exercice et "
          + "le bouton « Tester », eux, fonctionnent normalement.";
    return;
  }
  projection = response;
  error = "";
}

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

const plural = (n, word) => n + " " + word + (n > 1 ? "s" : "");

// --- Rendering ----------------------------------------------------------------
// `textContent` EVERYWHERE. An alias is drawn from a closed vocabulary on the
// server, so it cannot carry markup -- but the rule does not depend on that
// staying true, and the day it changes this file must not be the reason.

// LE GROUPE QUE L'ENSEIGNANT REGARDE. `null` = le sien (donc, pour un
// enseignant sans groupe au profil, tout le cours).
let groupeVise = null;

// LE SÉLECTEUR N'EXISTE QUE POUR UN MODÉRATEUR, et c'est le SERVEUR qui le
// dit (`moderator` dans la réponse) : la page ne devine pas un rôle.
function groupSwitch(view) {
  if (!view.moderator || !(view.groups || []).length) return null;
  const row = node("div", "tabs");
  const entries = [[null, "Tous les groupes"]].concat(
    view.groups.map((g) => [g, "Groupe " + String(g).padStart(2, "0")]));
  for (const [value, title] of entries) {
    const tab = button(title, "nav" + (groupeVise === value ? " on" : ""),
      async () => {
        if (groupeVise === value) return;
        groupeVise = value;
        scope = value === null ? "course" : "group";
        await load();
        render();
      });
    tab.setAttribute("aria-pressed", groupeVise === value ? "true" : "false");
    row.append(tab);
  }
  return row;
}

function scopeSwitch() {
  const row = node("div", "tabs");
  for (const pair of [["group", "Mon groupe"], ["course", "Cours entier"]]) {
    const id = pair[0];
    const tab = button(pair[1], "nav" + (scope === id ? " on" : ""), async () => {
      if (scope === id) return;
      scope = id;
      await load();
      render();
    });
    // `aria-pressed` RATHER THAN A CLASS: "on" says nothing to a screen
    // reader, and which scope one is looking at is the whole context of the
    // numbers below.
    tab.setAttribute("aria-pressed", scope === id ? "true" : "false");
    row.append(tab);
  }
  return row;
}

// THE OPT-IN IS NOT HERE, and that is deliberate: joining a ranking is an
// identity setting, next to "show my name" and "show my group". Two places to
// consent would be two places that can disagree about whether one did.
function invitation() {
  const block = node("div", "bloc plan");
  block.append(node("div", "kicker", "Tu n'y participes pas"));
  block.append(node("p", "", "Le classement est facultatif, et tu n'y es pas. "
    + "Rien de ce que tu fais n'y apparaît tant que tu ne l'as pas coché."));
  block.append(node("p", "aide", "Tu y apparaîtrais sous un pseudonyme tiré au "
    + "hasard, jamais sous ton nom, et tu pourrais te retirer à tout moment "
    + "sans que ta pratique ni tes progrès changent."));
  block.append(button("Ouvrir « Mon identité »", "", async () => {
    if (!await ctester.activerModule("forum", "les discussions")) return;
    await ctester.forum.ouvrirIdentite();
  }));
  return block;
}

// UNDER THE MINIMUM COHORT THERE IS NO TABLE, and the reason is written on
// screen: a ranking of four people names those four people, including the
// last one. The server already refuses to send it; this says why, so an
// empty screen does not read as a failure.
function tooSmall(view) {
  const block = node("div", "bloc");
  block.append(node("p", "", "Vous êtes " + plural(view.cohort, "compte")
    + " à participer ici. Il en faut au moins " + view.minimum
    + " pour afficher un tableau."));
  block.append(node("p", "aide", "En dessous, un classement nomme tout le monde "
    + "— y compris la dernière personne. Tu vois donc ta ligne, et rien d'autre."));
  return block;
}

// ONE'S OWN STANDING, AND THE STEP UP. "Deux de plus et tu passes 3e" is
// something to do; "quelqu'un te rattrape" is pressure with nothing to do
// about it, and it is not sent.
function standing(view) {
  const block = node("div", "bloc plan rang");
  block.append(node("span", "chiffre", String(view.me.rank)));
  const right = node("div", "");
  right.append(node("p", "", "sur " + plural(view.cohort, "compte")
    + (view.scope === "course" ? " du cours" : " de ton groupe")
    + ", ces " + view.window_days + " derniers jours"));
  if (view.gap) {
    right.append(node("p", "aide", view.gap.solved > 0
      ? plural(view.gap.solved, "exercice") + " de plus et tu passes "
        + view.gap.rank + (view.gap.rank === 1 ? "er" : "e") + "."
      : "Tu es à égalité avec la place au-dessus."));
  } else {
    right.append(node("p", "aide", "Personne devant toi cette semaine."));
  }
  block.append(right);
  return block;
}

function table(view) {
  const block = node("div", "bloc");
  const t = document.createElement("table");
  t.className = "rank-table";
  const head = document.createElement("tr");
  const labels = ["#", "Compte", "Exercices réussis pour la première fois"];
  for (const label of labels) head.append(node("th", "", label));
  t.append(head);
  for (const row of view.rows) {
    const tr = document.createElement("tr");
    if (row.mine) tr.className = "mine";
    tr.append(node("td", "num", String(row.rank)));
    tr.append(node("td", "", row.mine ? "Toi — " + row.alias : row.alias));
    tr.append(node("td", "num", String(row.solved)));
    t.append(tr);
  }
  block.append(t);
  block.append(node("p", "aide", "Refaire un exercice déjà réussi ne compte "
    + "pas : la colonne ne bouge qu'à la première réussite. Les rangs suivants "
    + "ne sont pas affichés — chaque personne voit sa propre ligne."));
  return block;
}

function divisions(view) {
  const block = node("div", "bloc");
  block.append(node("h3", "soustitre", "Divisions du cours"));
  const row = node("div", "divisions");
  const mine = (view.division || {}).id;
  for (const d of view.divisions || []) {
    const cell = node("div", "division" + (d.id === mine ? " on" : ""));
    cell.append(node("span", "name", d.title));
    cell.append(node("span", "quoi", d.id === mine
      ? "tu es ici — " + plural(d.accounts, "compte")
      : plural(d.accounts, "compte")));
    row.append(cell);
  }
  block.append(row);
  block.append(node("p", "aide", "Les divisions montent, jamais ne descendent "
    + "en cours de session : un mauvais mois ne fait rien perdre."));
  return block;
}

// THE ALIAS, AND THE BUTTON THAT REDRAWS IT. Drawn server-side from a closed
// vocabulary, so nothing anyone typed ever lands in a ranking -- which is why
// this screen needs no moderation of its own.
function aliasRow(view) {
  const block = node("div", "bloc");
  // ON NE DIT PAS « TU APPARAIS SOUS X » À QUELQU'UN QUE LE `WHERE` EXCLUT.
  // L'enseignant lit le classement et n'y figure jamais -- son XP est de l'XP
  // de test, et un tableau qui le porterait serait injuste pour tous ceux qui
  // y sont. La règle est en SQL ; ce qui est ici, c'est de ne pas mentir
  // dessus.
  if (view.moderator) {
    block.append(node("p", "", "Tu n'apparais pas au classement : il ne "
      + "compte que les comptes étudiants qui s'y sont inscrits."));
    return block;
  }
  const row = node("p", "aliasrow");
  row.append(node("span", "", "Tu apparais sous"));
  row.append(node("b", "alias-value", view.alias || "—"));
  row.append(button("Un autre nom", "nav", async () => {
    const response = await ctester.compte.sendJson("leaderboard/alias", "POST", {});
    annonce = response && response.ok
      ? "Nouveau pseudonyme."
      : "Le pseudonyme n'a pas pu être changé.";
    await load();
    render();
  }));
  block.append(row);
  block.append(node("p", "aide", "Tiré au hasard, jamais ton vrai nom, et "
    + "rechangeable autant de fois que tu veux."));
  return block;
}

function render() {
  const box = $("viewleaderboard");
  box.innerHTML = "";
  const head = node("h2", "", "Classement");
  head.id = "leaderboardtitle";
  head.tabIndex = -1;
  box.append(head);
  box.append(node("p", "aide", "Facultatif. Tu y participes parce que tu l'as "
    + "coché, et tu peux te retirer à tout moment : ta pratique et tes progrès "
    + "ne changent pas."));
  if (annonce) {
    const status = node("p", "annonce", annonce);
    status.setAttribute("aria-live", "polite");
    box.append(status);
  }
  if (!projection) {
    // WE DO NOT INVENT AN EMPTY RANKING. "Personne" during an outage says
    // nobody is working, and that would be false.
    box.append(node("p", "rate", error));
    return;
  }
  if (!projection.participating) {
    box.append(invitation());
    return;
  }
  const parGroupe = groupSwitch(projection);
  if (parGroupe) box.append(parGroupe);
  else box.append(scopeSwitch());
  box.append(aliasRow(projection), standing(projection));
  box.append(projection.rows.length ? table(projection) : tooSmall(projection));
  box.append(divisions(projection));
}

// --- Entry points -------------------------------------------------------------

async function toggle() {
  if (ctester.vue() === "leaderboard") { ctester.afficherVue(""); return; }
  annonce = "";
  await load();
  render();
  ctester.afficherVue("leaderboard");
  // Focus follows the view: without this, tabbing would restart from the top
  // of the page and a screen reader would not announce the screen change.
  const head = $("leaderboardtitle");
  if (head && head.focus) head.focus();
}

function forget() {
  projection = null;
  error = "";
  annonce = "";
  if (ctester.vue() === "leaderboard") ctester.afficherVue("");
}

ctester.leaderboard = {
  basculer: toggle,
  oublier: forget,
  projection: () => projection,
};
})(window.ctester);
