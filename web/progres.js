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
  const block = node("div", "bloc plan");
  block.append(node("div", "kicker", "Action suivante"));
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

// THE MASTERY CARD: the headline of the section further down, so the top of
// the screen answers "what can I actually do?" before "how much have I
// done?". THE SAME NUMBERS AS THE SECTION -- both read `view.mastery`, so
// there is no second computation to disagree with the first.
function masteryCard(view) {
  const block = node("div", "bloc plan");
  block.append(node("div", "kicker", "Maîtrise vérifiée"));
  const rows = (view.mastery || {}).skills || [];
  if (!rows.length) {
    block.append(node("p", "aide", "Aucune vérification n'est ouverte pour "
      + "l'instant."));
    return block;
  }
  const verified = rows.filter(r => r.band === "verifie").length;
  block.append(node("p", "gros", verified + " compétence"
    + (verified > 1 ? "s" : "") + " sur " + rows.length));
  const bands = {};
  for (const b of (view.mastery || {}).bands || []) bands[b.id] = b.title;
  // ONE LINE PER BAND, with the skills it holds. Grouping by band is what
  // makes "where are the holes" a glance rather than a read-through -- and
  // the band's WORD is on the line, never a color on its own.
  for (const id of ["verifie", "en-progression", "a-consolider", "non-verifie"]) {
    const named = rows.filter(r => r.band === id);
    if (!named.length) continue;
    const line = node("p", "bandeligne");
    line.append(node("span", "tag" + (id === "verifie" ? " accent" : ""),
                      bands[id] || id));
    line.append(node("span", "", named.map(r => ctester.skillLabel(r.id)).join(", ")));
    block.append(line);
  }
  return block;
}

// THE PRACTICE CALENDAR (design 1b), and it REPLACES A STREAK on purpose:
// there is no counter to break, so a bad week takes nothing away and nothing
// has to be defended. Thirteen weeks of squares, one per day.
//
// NOTHING IS COMPUTED HERE EITHER: the server sends the days it observed, and
// this fills in the gaps. A page that decided for itself which days counted
// would be a page where one gives oneself a habit from the console.
const CALENDAR_DAYS = 91;

// FOUR STEPS, and the top one is open-ended: somebody who submitted thirty
// times in a day is not four times darker than somebody who submitted four.
function calendarStep(attempts) {
  if (!attempts) return "";
  if (attempts >= 8) return "n4";
  if (attempts >= 4) return "n3";
  if (attempts >= 2) return "n2";
  return "n1";
}

const isoDay = (date) => date.toISOString().slice(0, 10);

function calendarSection(view) {
  const block = node("div", "bloc plan");
  block.append(node("div", "kicker", "Ce que tu as pratiqué"));
  const counts = {};
  for (const row of view.practice_days || []) {
    if (row && typeof row.date === "string") counts[row.date] = row.attempts | 0;
  }
  const grid = node("div", "calendar");
  const today = new Date();
  for (let back = CALENDAR_DAYS - 1; back >= 0; back--) {
    const day = new Date(today.getTime() - back * 86400000);
    const key = isoDay(day);
    const n = counts[key] || 0;
    const cell = node("span", calendarStep(n));
    // THE TOOLTIP CARRIES THE DAY AND THE COUNT: ninety-one unlabeled
    // squares are a texture, not information, and a texture reads aloud as
    // nothing at all.
    cell.setAttribute("title", day.toLocaleDateString(undefined,
      { day: "numeric", month: "long" }) + " — "
      + (n ? plural(n, "test") : "aucune pratique"));
    grid.append(cell);
  }
  block.append(grid);
  const active = Object.keys(counts).length;
  block.append(node("p", "", plural(active, "jour") + " de pratique sur les "
    + "treize dernières semaines."));
  block.append(node("p", "aide", "Une case foncée = un jour où tu as testé du "
    + "code. Il n'y a pas de série à maintenir : un trou ne retire rien."));
  return block;
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

// --- THE LAB GRID -----------------------------------------------------------
// THE GRID, ONE ROW PER LAB (design 1b). It replaces a flat list of
// seventy-three sentences where the eye found no landmark: one glance now
// says what is done, what is left, and where the holes are.
//
// IT DOES NOT DEPEND ON `GET /progres`. A mute database drops the
// projection's numbers, not this grid: it draws itself from what `compte.js`
// has already read, and a lab's export must stay reachable on an evening when
// the database is down.
// The same single word as the core (`STATUS_WORD`), spelled here because
// this module does not import it -- see the one-way rule.
const STATE_WORD = { solved: "réussi", attempted: "essayé" };

// THE SAME FIVE STATES AS THE STRIP, and they come from the SAME function
// (`ctester.tuileEtat`). Two tables of states would drift, and the one that
// drifted would be the one nobody looks at twice.
function tile(ex, states, stats) {
  const note = ctester.noteVerrou(ex);
  let state = ctester.tuileEtat(ex, !!note);
  const done = states[ex.id];
  const count = (stats || {})[ex.id];
  // TWO SOURCES SAY "SOLVED", AND EITHER IS ENOUGH -- this is what the flat
  // list did before the grid replaced it. `/etats` carries the state the
  // server wrote from the verdict; `/pratique` carries the attempts it
  // counted. An account that practised before `exercise_state` existed only
  // has the second, and must still read as solved.
  if (!note && count && count.successes) state = { cls: "reussi", word: "réussi" };
  const label = node("button", "tile " + state.cls, tileLabel(ex));
  label.type = "button";
  // THE ATTEMPT COUNT SURVIVED THE GRID, in the tile's own words. The list
  // this replaced spelled out "3 tentatives — réussie" on every row; ninety
  // rows of that is what made it unreadable, but the number itself is worth
  // keeping -- it is the only place a student sees that an exercise took them
  // seven tries. So it moves into the tile's title and its off-screen text,
  // which is where a tile keeps everything it cannot draw.
  const tries = count && count.attempts
    ? ", " + count.attempts + " tentative" + (count.attempts > 1 ? "s" : "")
    : "";
  const word = (note || STATE_WORD[done] || state.word) + tries;
  label.setAttribute("title", ex.short + " — " + word);
  label.append(node("span", "horsecran", " — " + word));
  if (note) {
    label.setAttribute("aria-disabled", "true");
    label.append(node("span", "cadenas", "🔒"));
  } else {
    label.addEventListener("click", () => openExercise(ex.id));
  }
  return label;
}

// "ex.3" ON A TILE, "vérif" ON A VERIFICATION. The full name lives in the
// tooltip and off-screen: eleven thirty-character tiles fill three lines and
// stop being a glance.
function tileLabel(ex) {
  if (ex.verification) return "vérif";
  const bare = (ex.short || "").replace(/^[^:]*:\s*/, "");
  const number = bare.match(/^ex\.?\s*(\d+)/i);
  if (number) return number[1];
  return bare.length > 8 ? bare.slice(0, 7) + "…" : bare;
}

function exportRow(group) {
  const block = node("span", "exportligne");
  // THE LAB'S NAME STAYS IN THE BUTTON even though the row already names it:
  // this is the button's accessible name, and four rows of "Exporter en
  // main.c" are four identical buttons to anyone tabbing through them.
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

// A LAB'S ROW: its name, its theme, its tiles, and how far along it is.
function labRow(col, states, stats) {
  const row = node("div", "labo");
  const head = node("div", "quoi");
  head.append(node("span", "name", col.titre));
  // THE THEME IS THE LAB'S SKILLS, deduplicated and in order. It comes from
  // the catalog rather than from a second table of hand-written blurbs --
  // which would go stale the first time a lab is reorganized.
  const theme = labTheme(col);
  if (theme) head.append(node("span", "theme", theme));
  row.append(head);
  const tiles = node("div", "tiles");
  for (const ex of col.items) tiles.append(tile(ex, states, stats));
  row.append(tiles);
  const tail = node("div", "compte");
  const open = col.items.filter(ex => !ctester.noteVerrou(ex));
  const solved = open.filter(ex => states[ex.id] === "solved").length;
  // A LAB THAT IS NOT OPEN SAYS SO instead of reading "0 sur 0": the two look
  // identical in a column of numbers and mean opposite things.
  tail.append(node("span", "", open.length
    ? solved + " sur " + open.length + " réussi" + (solved > 1 ? "s" : "")
    : "pas encore ouvert"));
  if (ctester.groupeExportable(col.titre)) tail.append(exportRow(col.titre));
  row.append(tail);
  return row;
}

function labTheme(col) {
  const skills = [];
  for (const ex of col.items) {
    for (const skill of (ex.learning || {}).skills || []) {
      const word = ctester.skillLabel(skill);
      if (!skills.includes(word)) skills.push(word);
    }
  }
  return skills.slice(0, 4).join(", ");
}

function labGrid() {
  const states = ctester.compte ? ctester.compte.etats() : {};
  const stats = ctester.compte ? ctester.compte.pratique() : {};
  const box = node("div", "grille");
  // THE WHOLE TREE, locked labs included: a lab that opens next week must
  // show as locked, not be absent. `catalogue()` only carries what is open,
  // which is right for a counter and wrong for a map.
  for (const col of ctester.collections()) {
    if (col.items.length) box.append(labRow(col, states, stats));
  }
  const block = node("div", "bloc");
  block.append(title("Par laboratoire"));
  if (!box.children.length) {
    block.append(node("p", "aide", "Aucun exercice n'est publié pour l'instant."));
    return block;
  }
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
    box.append(node("p", "rate", error), labGrid());
    return;
  }
  // MASTERY BEFORE PRACTICE: it is the new subject, and the one that answers
  // "could I do this again on my own?". XP stays last, secondary.
  // THE THREE CARDS FIRST (design 1b): what to do next, where mastery
  // stands, and the practice calendar. Then the map of the labs, then the
  // detail. XP stays last and secondary -- it is a count of activity, and the
  // layout says so before the sentence does.
  const cards = node("div", "tableau");
  cards.append(nextAction(projection), masteryCard(projection),
               calendarSection(projection));
  box.append(cards, labGrid(), masterySection(projection),
             practiceSection(projection), levelSection(projection),
             achievementsSection(projection));
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
