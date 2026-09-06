// "Mes progrès": a signed-in account's private view. Loaded ON CLICK, never
// before -- the anonymous visitor downloads none of it, and neither does a
// signed-in student who never opens it. Same contract as compte.js, same
// reasons.
//
// ONE WAY: this file reads `window.ctester` and deposits its own entry into
// it; the core only ever knows it through `ctester.progres`, never through an
// import.
//
// NOTHING IS COMPUTED HERE. The balance, the level, the skills, the
// achievements and the recommendation arrive ready-made from `GET /progres`,
// which derives them from facts the server itself wrote. A page that
// computed its own XP would be a page where one gives it to oneself from the
// console.
(function (ctester) {
const $ = ctester.$;

// The last projection received, or null when there is nothing reliable to
// show. THE TWO ARE DISTINCT: `null` with an error message means "we don't
// know", and it must not display like a zero. Announcing 0 XP to someone
// whose database is down tells them their work is gone.
let projection = null;
let error = "";

async function load() {
  if (!ctester.compte) {
    projection = null;
    error = "Reconnecte-toi pour voir tes progrès.";
    return;
  }
  const response = await ctester.compte.getJson("progres");
  if (!response || typeof response.xp !== "number") {
    projection = null;
    error = "Tes progrès ne sont pas disponibles pour l'instant. "
           + "L'exercice et le bouton « Tester », eux, fonctionnent normalement.";
    return;
  }
  projection = response;
  error = "";
}

// --- Rendering ---------------------------------------------------------------
// `textContent` EVERYWHERE: skill ids come from the test repository and
// achievement labels from the server's policy. None of it is HTML, and the
// day one of them contains an angle bracket, it must display as an angle
// bracket.

function node(tag, className, text) {
  const n = document.createElement(tag);
  if (className) n.className = className;
  if (text !== undefined) n.textContent = text;
  return n;
}

function title(text) {
  return node("h3", "soustitre", text);
}

function gauge(done, total) {
  // DECORATIVE, and declared as such: the same information is spelled out
  // right above. A screen reader has nothing to announce here.
  const bar = node("span", "jauge");
  bar.setAttribute("aria-hidden", "true");
  const fill = document.createElement("i");
  fill.setAttribute("style",
    "width:" + (total ? Math.round(done / total * 100) : 0) + "%");
  bar.append(fill);
  return bar;
}

const plural = (n, word) => n + " " + word + (n > 1 ? "s" : "");

function exerciseLabel(id) {
  const tp = ctester.catalogue().find(t => t.id === id);
  return tp ? (tp.label || tp.short || id) : id;
}

function nextAction(view) {
  const block = node("div", "bloc");
  block.append(title("Action suivante"));
  const next = view.next;
  if (!next) {
    block.append(node("p", "", view.exercises.total
      ? "Tu as réussi tous les exercices publiés. Rien de neuf à proposer "
        + "pour l'instant."
      : "Aucun exercice n'est publié pour l'instant."));
    return block;
  }
  const what = exerciseLabel(next.exercise_id);
  block.append(node("p", "", next.skill
    ? "Tu as déjà pratiqué « " + ctester.skillLabel(next.skill)
      + " » : continue avec « " + what + " »."
    : "Commence par « " + what + " »."));
  const button = node("button", "", "Ouvrir « " + what + " »");
  button.type = "button";
  button.addEventListener("click", () => openExercise(next.exercise_id));
  block.append(button);
  return block;
}

function openExercise(id) {
  const tp = ctester.catalogue().find(t => t.id === id);
  if (!tp) return;
  ctester.fillExercises(tp.id);
  ctester.afficherVue("");
}

function practiceSection(view) {
  const block = node("div", "bloc");
  block.append(title("Ce que tu as pratiqué"));
  const ex = view.exercises;
  block.append(node("p", "", plural(ex.practiced, "exercice") + " pratiqué"
    + (ex.practiced > 1 ? "s" : "") + " sur " + ex.total + " publié"
    + (ex.total > 1 ? "s" : "") + ", dont " + ex.solved + " réussi"
    + (ex.solved > 1 ? "s" : "") + "."));

  if (!view.skills.length) {
    block.append(node("p", "aide",
      "Les exercices que tu as ouverts n'annoncent pas encore de compétence."));
    return block;
  }
  // A LIST, NOT A CHART. Each row spells out its values: that is what a
  // screen reader reads, what a 400% zoom keeps, and what stays true with no
  // color at all.
  const list = node("ul", "competences");
  for (const c of view.skills) {
    const item = document.createElement("li");
    item.append(node("span", "nom", ctester.skillLabel(c.id)));
    item.append(node("span", "chiffres",
      c.practiced + " exercice" + (c.practiced > 1 ? "s" : "")
      + " pratiqué" + (c.practiced > 1 ? "s" : "") + " sur " + c.total
      + ", dont " + c.solved + " réussi" + (c.solved > 1 ? "s" : "")));
    item.append(gauge(c.practiced, c.total));
    list.append(item);
  }
  block.append(list);
  block.append(node("p", "aide",
    "« Pratiquée » veut dire que tu as soumis un exercice qui porte cette "
    + "compétence. Ce n'est pas une maîtrise vérifiée."));
  return block;
}

// --- Verified mastery --------------------------------------------------------
// THIS SECTION IS NEW, it does not relabel "Ta pratique". The two say
// different things and must keep saying so: the judge is self-service, so a
// solve only proves something that passes was submitted; a verification is a
// separate activity, built for exactly that.
//
// NOTHING IS COMPUTED HERE EITHER: bands arrive from the server, legend
// included. A page that decided on its own what "verified" means would be a
// page where one grants it to oneself from the console.
function masterySection(view) {
  const block = node("div", "bloc");
  block.append(title("Maîtrise vérifiée"));
  const mastery = view.mastery || {};
  const rows = mastery.skills || [];
  const bands = mastery.bands || [];
  if (!rows.length) {
    block.append(node("p", "aide",
      "Aucune vérification n'est ouverte pour l'instant. Ce sont les activités "
      + "marquées « vérification » dans le menu des exercices."));
    return block;
  }
  const definition = {};
  for (const b of bands) definition[b.id] = b;
  const list = node("ul", "competences");
  for (const c of rows) {
    const item = document.createElement("li");
    item.append(node("span", "nom", ctester.skillLabel(c.id)));
    const word = definition[c.band] || { title: c.band };
    item.append(node("span", "bande " + c.band, word.title));
    // THE COUNT SPELLED OUT, next to the word: "verified" on a single piece
    // of evidence and "verified" on four are not worth the same, and the
    // student has the right to know which one they are reading.
    item.append(node("span", "chiffres",
      c.passed + " vérification" + (c.passed > 1 ? "s" : "") + " réussie"
      + (c.passed > 1 ? "s" : "") + " sur " + c.total
      + (c.attempted ? ", " + c.attempted + " tentée" + (c.attempted > 1 ? "s" : "")
                   : ", aucune tentée")));
    item.append(gauge(c.passed, c.total));
    list.append(item);
  }
  block.append(list);
  // The legend, once: the four words above do not explain themselves.
  const legend = node("dl", "bandes");
  for (const b of bands) {
    legend.append(node("dt", "", b.title));
    legend.append(node("dd", "", b.description));
  }
  block.append(legend);
  block.append(node("p", "aide",
    "Une vérification ne rapporte aucun XP : elle dit ce que tu sais refaire, "
    + "pas combien tu as travaillé. Une bande basse ne retire rien et n'est "
    + "pas une note — elle indique où revenir pratiquer."));
  return block;
}

function levelSection(view) {
  // SECONDARY, and the sentence that follows is not decorative: it is the
  // only thing that keeps an activity counter from reading like a grade.
  const block = node("div", "bloc second");
  block.append(title("Niveau et XP"));
  const n = view.level;
  block.append(node("p", "", "Niveau " + n.rank + " — " + view.xp + " XP."
    + (n.next === null
       ? " C'est le dernier niveau de la politique en cours."
       : " Encore " + n.remaining + " XP avant le niveau " + (n.rank + 1) + ".")));
  block.append(gauge(view.xp - n.since,
                    (n.next === null ? view.xp : n.next) - n.since));
  block.append(node("p", "aide", "Les XP reflètent l'activité de pratique ; "
    + "ce ne sont ni une note ni une maîtrise vérifiée."));
  return block;
}

function achievementsSection(view) {
  const block = node("div", "bloc");
  block.append(title("Accomplissements"));
  if (!view.achievements.length) {
    block.append(node("p", "aide",
      "Aucun pour l'instant. Ils arrivent en pratiquant ; aucun n'est "
      + "obligatoire."));
    return block;
  }
  // TITLE, DESCRIPTION AND DATE, as text. No color swatch alone, no icon
  // alone: all three read aloud and survive black and white.
  const list = node("dl", "succes");
  for (const s of view.achievements) {
    list.append(node("dt", "", s.title));
    const desc = document.createElement("dd");
    desc.append(node("span", "quoi", s.description));
    const when = node("time", "quand", "obtenu le " + s.unlocked_at);
    when.setAttribute("datetime", s.unlocked_at);
    desc.append(when);
    list.append(desc);
  }
  block.append(list);
  return block;
}

// --- THE EXERCISE LIST -------------------------------------------------------
// IT DOES NOT DEPEND ON `GET /progres`. A mute database drops the
// projection's numbers, not this list: it draws itself from what `compte.js`
// has already read, and the export must stay reachable on an evening when
// the database is down.
const STATE_WORD = { solved: "validé", attempted: "essayé" };
// The CSS classes stay "valide"/"essaye" -- style.css's selectors were left
// untouched on purpose, so the wire values need a translation on the way in.
const STATE_CLASS = { solved: "valide", attempted: "essaye" };

function exportRow(group) {
  const block = node("div", "exportligne");
  const button = node("button", "nav", "Exporter le " + group + " en main.c");
  button.type = "button";
  const status = node("span", "exportetat");
  status.setAttribute("aria-live", "polite");
  const announce = (text, failed) => {
    status.textContent = text;
    status.className = failed ? "exportetat rate" : "exportetat";
  };
  button.addEventListener("click", async () => {
    // `activateModule` already says what did not arrive -- but it says it in
    // the system banner. We say it again on the spot, or the button stays
    // inert.
    if (!await ctester.activerModule("exporter", "l'export du TP")) {
      announce("l'export n'a pas pu être chargé — réessaie", true);
      return;
    }
    await ctester.exporter.exporter(group, announce);
  });
  block.append(button, status);
  return block;
}

function exerciseList() {
  // THE `liste` ID IS KEPT: all of the old destination's styling hangs off
  // it, and copying it under another name would have made two sheets to keep
  // in sync for zero visible change.
  const box = node("div");
  box.id = "liste";
  const states = ctester.compte ? ctester.compte.etats() : {};
  const stats = ctester.compte ? ctester.compte.pratique() : {};
  const tps = ctester.catalogue();
  for (let rank = 0; rank < tps.length; rank++) {
    const tp = tps[rank];
    const row = node("button", "ligne");
    row.type = "button";
    row.append(node("span", "tpname", tp.group));
    row.append(node("span", "titre", tp.short || tp.label));
    const count = stats[tp.id];
    const state = states[tp.id] || "";
    const dot = node("span", "puce " + (count && count.successes ? "valide" : (STATE_CLASS[state] || "")),
      count
        ? count.attempts + " tentative" + (count.attempts > 1 ? "s" : "")
          + (count.successes ? " — réussie" + (count.successes > 1 ? "s" : "") : "")
        : STATE_WORD[state] || "à faire");
    row.append(dot);
    row.addEventListener("click", () => openExercise(tp.id));
    box.append(row);
    // THE BUTTON CLOSES THE GROUP, it does not open it: it comes after the
    // lab's last row, right after reading what is left to do in it.
    const next = tps[rank + 1];
    if ((!next || next.group !== tp.group)
        && ctester.groupeExportable(tp.group)) {
      box.append(exportRow(tp.group));
    }
  }
  const block = node("div", "bloc");
  block.append(title("Tes exercices"));
  block.append(box);
  return block;
}

function render() {
  const box = $("vueprogres");
  box.innerHTML = "";
  const head = node("h2", "", "Mes progrès");
  head.id = "progrestitre";
  head.tabIndex = -1;
  box.append(head);
  box.append(node("p", "aide", "Cette page n'est visible que par toi. Rien "
    + "n'est transmis à ton enseignant, et ce n'est pas une note."));
  if (!projection) {
    // WE DO NOT INVENT A ZERO. A balance shown as zero during a database
    // outage reads as "all my work is gone", and that would be false.
    //
    // BUT THE LIST STAYS: it does not come from the projection, and a lab's
    // export must not disappear on the evening Postgres coughs.
    box.append(node("p", "rate", error), exerciseList());
    return;
  }
  // MASTERY BEFORE PRACTICE: it is the new subject, and the one that answers
  // "could I do this again on my own?". XP stays last, secondary.
  box.append(nextAction(projection), exerciseList(), masterySection(projection),
             practiceSection(projection), levelSection(projection), achievementsSection(projection));
}

// --- Entry points -------------------------------------------------------------

async function toggle() {
  if (ctester.vue() === "progres") { ctester.afficherVue(""); return; }
  await load();
  render();
  ctester.afficherVue("progres");
  // Focus follows the view: without this, tabbing would restart from the top
  // of the page and a screen reader would not announce the screen change.
  const head = $("progrestitre");
  if (head.focus) head.focus();
}

// AFTER A VERDICT. The projection is redone even when the view is closed:
// opening it afterward must not show the second-to-last submission.
async function refresh() {
  await load();
  if (ctester.vue() === "progres") render();
}

function forget() {
  projection = null;
  error = "";
  if (ctester.vue() === "progres") ctester.afficherVue("");
}

ctester.progres = {
  basculer: toggle,
  rafraichir: refresh,
  oublier: forget,
  projection: () => projection,
};
})(window.ctester);
