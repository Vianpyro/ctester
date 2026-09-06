const $ = (id) => document.getElementById(id);

// SHARED STATE IS NAMED, NOT IMPLICIT. The quiz and the account are loaded on
// demand; they read this context and deposit their own entries into it. The
// direction is one-way -- the core depends on neither, each of them depends on
// the core -- and that is what forbids the cycle. An ES module would do the
// same thing by linking in a temporal dead zone on a circular import, the
// exact failure this page already saw in production.
const ctester = window.ctester = {};

const loaded = {};
// Cloudflare caches static assets independently from index.html.  Keep this
// token in sync with index.html whenever app.js or a lazy module changes, so a
// deployed page cannot combine a new core with an old compte.js/quiz.js.
const ASSET_REVISION = "20260904-catalogue-v2";

// ponytail: <script> injection, not import(). See above. Move to ES modules
// the day shared state is truly separated.
function load(name) {
  if (!loaded[name]) {
    loaded[name] = new Promise((ok, ko) => {
      const tag = document.createElement("script");
      tag.onload = () => ok();
      tag.onerror = () => ko(new Error(name));
      tag.src = name + "?v=" + ASSET_REVISION;
      document.body.append(tag);
    }).catch((e) => {
      // THE FAILURE IS FORGOTTEN. Without this, a one-second network blip
      // condemns the function for the whole visit: the second click would
      // fall back onto the rejected promise without ever retrying.
      delete loaded[name];
      throw e;
    });
  }
  return loaded[name];
}

// `activateModule`, NOT `activate`: this file already has an `activate`
// function, the one that switches tabs in the editor. Two function
// declarations of the same name do not warn each other, the last one wins,
// and the caller silently receives the other one.
async function activateModule(name, what) {
  if (ctester[name]) return true;
  try {
    await load(name + ".js");
  } catch (e) {
    announceSystem("Impossible de charger " + what + ". Vérifie ta connexion, "
          + "puis recharge la page.", true);
    return false;
  }
  if (!ctester[name]) {
    // The file arrived but did not register itself: a cached version of an
    // old deploy, a connection cut mid-transfer. Staying silent here would
    // make the button inert without a word.
    announceSystem("Impossible d'utiliser " + what
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

// THE ACCESS KEY SURVIVES A RELOAD WITHOUT ITS QUERY STRING. It arrives via
// Moodle's link (`?k=…`); a student who types the address from memory,
// follows a shared link without the key, or comes back through a bookmark,
// used to end up without it -- and only found out after writing their code.
//
// `sessionStorage` AND NOT `localStorage`, deliberately: the key dies with
// the tab. On a shared lab machine, leaving it behind would hand it to the
// next student who sits down.
const ACCESS_KEY_STORAGE = "ctester.cle";
const keyFromLink = new URLSearchParams(location.search).get("k") || "";
if (keyFromLink) sessionSet(ACCESS_KEY_STORAGE, keyFromLink);
const key = keyFromLink || sessionGet(ACCESS_KEY_STORAGE);

// SAID AT LOAD TIME, NOT ON THE FIRST SUBMISSION. Without this, a student
// would write their whole exercise before learning they could not test it --
// and they would learn it through "clé de session invalide ou expirée",
// which means nothing to them and does not say what to do. Non-blocking:
// writing and saving work perfectly fine without a key.
if (!key) {
  announceSystem("Il manque ta clé d'accès. Rouvre le lien de CTester depuis Moodle "
        + "pour pouvoir tester ton code. Tu peux écrire en attendant : "
        + "ton brouillon est enregistré.");
}
const out = $("out");
// FOCUSABLE WITHOUT BEING IN THE TAB ORDER: `scrollResultIntoView()` puts
// focus on it on small screens, where the verdict lands off-screen.
out.tabIndex = -1;

const THEME_KEY = "ctester.theme";

function applyTheme(name) {
  document.documentElement.dataset.theme = name;
  const light = name === "light";
  $("theme").textContent = light ? "☾" : "☀";
  $("theme").title = light ? "Passer au thème sombre" : "Passer au thème clair";
  $("theme").setAttribute("aria-label", $("theme").title);
}

// LOCAL STORAGE STAYS THE DEVICE'S MEMORY, even when the account has the
// last word: it is what the `<head>` script reads before the first paint,
// and nothing else can arrive early enough to avoid the flash. What the
// server says is therefore copied here -- not to be read back by the page,
// but so that the NEXT visit already starts from the right theme.
function rememberTheme(name) {
  try { localStorage.setItem(THEME_KEY, name); } catch (e) {}
}

applyTheme(document.documentElement.dataset.theme === "light"
               ? "light" : "dark");

const currentTheme = () =>
  document.documentElement.dataset.theme === "light" ? "light" : "dark";

$("theme").addEventListener("click", () => {
  const next = currentTheme() === "light" ? "dark" : "light";
  applyTheme(next);
  rememberTheme(next);
  // AND ON THE ACCOUNT, WHEN THERE IS ONE. `compte.js` is only loaded for a
  // signed-in session: the anonymous visitor triggers no request here, and
  // the module itself does nothing without a token. Nothing is awaited --
  // the theme is already applied on screen, and a failed round trip must not
  // make it look like the button did not work.
  if (ctester.compte) ctester.compte.enregistrerTheme(next);
});

// --- TWO CHANNELS, AND THEY MUST NEVER BE CONFUSED AGAIN -------------------
//
// THE VERDICT TALKS ABOUT THE STUDENT'S CODE. THE SYSTEM BANNER TALKS ABOUT
// THE SERVICE. A single red `show("bad")` used to serve both: "your file
// does not compile" and "the server is unreachable" displayed identically,
// in the same place, in the same title typography. A beginner concludes they
// broke something -- a false attribution of blame, in exactly the situations
// where it is not their fault.
//
// Of the seventeen red messages this page used to show, only FOUR were an
// actual verdict. Do not merge these two functions back into one.

function node(tag, className, text) {
  const n = document.createElement(tag);
  if (className) n.className = className;
  if (text !== undefined) n.textContent = text;
  return n;
}

// WHAT IS ANNOUNCED TO SCREEN READERS, AND NOTHING ELSE: one short line.
// `#out` deliberately has NO aria-live -- it carries the compiler's output,
// and announcing all of it would be worse than silence.
function announce(text) {
  $("annonce").textContent = text;
}

// --- The service channel ----------------------------------------------------
// Network, quota, full queue, session key, missing module, sign-in: everything
// the student is not responsible for. Neutral tone, never in the verdict's
// spot, and always a sentence saying what is NOT lost.
function announceSystem(text, failed) {
  const box = $("systeme");
  box.textContent = text || "";
  box.className = failed ? "panne" : "";
  box.hidden = !text;
  if (text) announce(text);
}

const clearSystem = () => announceSystem("");

// --- The verdict channel -----------------------------------------------------

// THE THREE STAGES A BEGINNER MUST LEARN TO TELL APART. The persona does not
// separate compilation, execution and logic; the server always knows which
// one broke, and the page used to throw that information away. Naming the
// stage NOT REACHED is what answers "did my program even run?". AGREEMENT
// FOLLOWS THE STAGE. "Tests pas atteinte" is gibberish, and this page speaks
// to French-speaking students: the first two stages are feminine singular,
// the third masculine plural.
const STEPS = [["Compilation", "f"], ["Exécution", "f"], ["Tests", "mp"]];
const STEP_STATE = {
  f:  { ok: "réussie",  ko: "échouée",  "": "pas atteinte" },
  mp: { ok: "réussis",  ko: "échoués",  "": "pas atteints" },
};

// THE STRIP STOPS WHERE THE COUNT TAKES OVER. When the judge has graded,
// the verdict displays "3 / 3 cas réussis" right below, in large type: a
// "Tests 3/3" box above it would only repeat that. So only TWO stages get
// shown in that case. When the judge has NOT graded, the third box instead
// carries the missing information -- "not reached" -- and it stays.
function stepBar(states) {
  const bar = node("div", "etapes");
  states.forEach((state, i) => {
    const [name, gender] = STEPS[i];
    const step = node("span", "pas " + (state || "vide"));
    // THE WORD, NOT ONLY THE COLOR nor only a check mark: a state that is
    // only visible through a tint disappears in black and white as under
    // color blindness, and does not read aloud.
    step.append(node("b", "", name));
    step.append(node("i", "", STEP_STATE[gender][state]));
    bar.append(step);
  });
  return bar;
}

// WHAT EACH STATE MEANS FOR THE STUDENT: where it broke, how to say so in one
// line, and what to do next. Everything is derived from what `/r/<id>`
// already returns.
//
//   `etapes`: "ok" passed, "ko" failed, "" not reached.
//   `titre`:  SHORT. It carries the color and it is what gets announced.
//   `suite`:  the next action. Always exactly one.
//
// THE EXPLANATION IS NOT HERE: that is `message`, written by the server for
// the student. Copying it here would make two places to fix, one of which
// would go stale silently. When the title below IS the server's message,
// `renderVerdict()` does not repeat it.
const OUTCOMES = {
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
  // "Compilation failed" rather than a fourth "Linking" stage: gcc does both
  // in a single command in this course, and adding a concept for a single
  // state would cost more than it earns. The server's message says the
  // nuance, and the title below says it too.
  link_error: {
    etapes: ["ko", "", ""],
    titre: "Ton code ne s'assemble pas avec les tests",
    // THE ACTION ADDS, IT DOES NOT REPEAT. The server's message already says
    // what to check; what a beginner lacks is HOW to go about it.
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

// THE NEXT ACTION, AND ONE IS NEEDED EVERYWHERE -- success included. The
// moment the student is most receptive used to be exactly the one where the
// page offered nothing.
function nextStepBar(text, button) {
  const block = node("div", "suite");
  block.append(node("span", "", text));
  if (button) {
    const b = node("button", "nav", button.libelle);
    b.type = "button";
    b.addEventListener("click", button.faire);
    block.append(b);
  }
  return block;
}

// HELP IS OFFERED WHERE THE NEED IS BORN: in front of a failing verdict, not
// in a button on the global bar. The thread is ALREADY per exercise
// (`forum.js` scopes it to the current exercise); only its entry point was
// global, at the other end of the screen, and went unnoticed at the moment
// it would have mattered.
//
// THE SAME TWO CONDITIONS AS THE BAR'S BUTTON, and both come from the
// server: being signed in, and a deployment that has moderators. A forum
// with nobody to read it does not open "in the meantime".
function helpButton() {
  if (!token || !(oidc && oidc.forum)) return null;
  const b = node("button", "nav aide", "En parler dans les discussions");
  b.type = "button";
  b.addEventListener("click", async () => {
    if (!await activateModule("forum", "les discussions")) return;
    await ctester.forum.basculer();
  });
  return b;
}

// THE LAST RENDERED VERDICT, to recall it at the top of a discussion thread.
// DECLARED HERE, above the function that writes it: a `let` set a thousand
// lines further down is a temporal dead zone, and it is the only failure
// this page has ever seen in production.
let lastVerdict = null;

// `v`: {cls, etapes, compte, titre, texte, bar, detail, suite, bouton}
// Only `titre` is required.
function renderVerdict(v) {
  // KEPT FOR DISCUSSIONS: opening a thread clears the workbench, and what one
  // came to talk about along with it. Only real verdicts count -- neither the
  // wait, nor the idle state.
  if (v.cls === "ok" || v.cls === "bad") {
    lastVerdict = { exercice: selectedId, titre: v.titre };
  }
  out.className = v.cls;
  out.innerHTML = "";
  if (v.etapes) out.append(stepBar(v.etapes));
  // THE COUNT KEEPS THE LARGE SIZE, a state's title no longer has it. "3 / 4"
  // reads at a glance and deserves it; "Ton code ne s'assemble pas avec les
  // tests" at 2.1rem used to crush the whole area. Only the `ok` path sets a
  // count, so the flag separates exactly the two cases.
  out.append(node("div", "verdict " + v.cls + (v.compte ? " compte" : ""),
                   v.titre));
  if (v.cls === "wait") out.append(indeterminateBar());
  if (v.bar) out.append(v.bar);
  // AS BODY TEXT, NEVER AGAIN AT 2.1REM. `link_error` and `memory_error`
  // messages run two hundred characters: in title typography, they used to
  // crush the whole result area.
  if (v.texte && v.texte !== v.titre) out.append(node("p", "explique", v.texte));
  if (v.detail) out.append(v.detail);
  if (v.suite) {
    const bar = nextStepBar(v.suite, v.bouton);
    // ONLY ON A FAILURE: we do not offer to go ask someone for help when
    // everything they just did passed.
    const help = v.cls === "bad" ? helpButton() : null;
    if (help) bar.append(help);
    out.append(bar);
  }
  announce(v.titre);
}

// THE IDLE STATE. No steps -- nothing has run yet, and a strip of three
// "not reached" before the first submission would announce a failure.
function idleState() {
  renderVerdict({
    cls: "idle",
    titre: "En attente d'une soumission.",
    texte: "Écris ton code, puis clique sur « Tester ». Les résultats ne sont "
         + "pas une note : ces tests t'aident à trouver tes erreurs, ils ne "
         + "remplacent pas la correction.",
  });
}

function indeterminateBar() {
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

// THE FIRST ERROR, NOT THE LAST. In C, errors cascade: one missing `;`
// produces six, five of which do not really exist. The raw output scrolls,
// and what a beginner reads is the BOTTOM -- so the most derived one, which
// matches nothing in their code. We isolate the first and fold the rest,
// without hiding anything.
const DIAGNOSTIC = /(^|\s)(error|erreur|warning|attention|note)\s*:/i;

function firstError(output) {
  const lines = (output || "").split("\n");
  const start = lines.findIndex(l => /(^|\s)(error|erreur)\s*:/i.test(l));
  if (start < 0) return null;
  // We keep what FOLLOWS the error line up to the next diagnostic: that is
  // the source excerpt and the `^` cursor, which show the exact spot.
  let end = start + 1;
  while (end < lines.length && !DIAGNOSTIC.test(lines[end])) end++;
  return lines.slice(start, end).join("\n").replace(/\s+$/, "");
}

function compilerOutput(gcc) {
  const box = node("div", "gcc");
  const first = firstError(gcc);
  if (!first) return block(gcc || "");
  box.append(block(first));
  // EVERYTHING IS ALWAYS THERE, just folded: hiding the rest would raise
  // doubt about what is not shown, and some errors only make sense read as a
  // chain.
  const rest = document.createElement("details");
  rest.className = "case";
  const head = document.createElement("summary");
  head.textContent = "Voir toute la sortie du compilateur";
  rest.append(head, block(gcc || ""));
  box.append(rest);
  return box;
}

// TWO READS OF THE SAME CONTENT, and that is intentional.
//   `collections` carries the MENU TREE: every exercise, open or not, with
//     its lock and its date. Showing is not giving -- v1 made anything not
//     open disappear, which looked like an outage the night before class.
//   `catalog` only carries OPEN exercises, in the shape "Mes exercices", the
//     export and progress already read. A locked exercise has no business in
//     a progression count nor in a submission main.c, and keeping the two
//     separate avoids adding a filter in three modules that would each
//     eventually forget it.
let catalog = [];
let collections = [];
// THE ID CHOSEN IN THE MENU, and the only source of that truth since the two
// <select> elements disappeared. `currentId` is something else: what the
// EDITOR actually holds, set by setupFiles once the fill-in has come back.
let selectedId = "";
// The exercise from a deep link that could not be opened: its collection is
// unfolded anyway, so the lock and date show instead of nothing.
let spotlighted = "";
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

// THE STATION ID, so the anonymous quota is not the whole room's. In the
// first labs, 27 stations exit through a single NATed IP. It lives in
// `localStorage` and NOT in `sessionStorage` like /live's: two tabs are
// indeed two open windows, but a single student. It proves nothing and only
// ever travels to /submit.
function stationId() {
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

// THE TOKEN LIVES IN THE CORE because submission needs it, and a submission
// leaves well before "Mes progrès" even exists.
function setToken(value) {
  token = value || null;
  if (token) sessionSet(TOKEN_KEY, token);
  else sessionDrop(TOKEN_KEY);
  refreshAccount();
}

// The banner must know how to draw itself BEFORE compte.js is there:
// otherwise the "Se connecter" button would only appear after the file that
// is only supposed to load once you click it.
function refreshAccount() {
  const on = !!token;
  $("connexion").hidden = !oidc || on;
  $("deconnexion").hidden = !on;
  $("oublier").hidden = !on;
  $("mesprogres").hidden = !on;
  // TWO CONDITIONS, AND BOTH COME FROM THE SERVER: being signed in, and a
  // deployment with at least one configured moderator (`oidc.forum`).
  // Without either, the button does not exist, so `forum.js` is never
  // requested -- the anonymous visitor downloads none of it, and a
  // deployment with no configured moderator does not open a channel nobody
  // rereads.
  $("discussions").hidden = !on || !(oidc && oidc.forum);
  // SAME CONDITION AS "Discussions": the name and group number only matter
  // there, and the form lives in that view.
  $("identite").hidden = !on || !(oidc && oidc.forum);
  $("moi").hidden = !on;
  $("moi").textContent = on ? "connecté" : "";
  // The menu only opens on an account: "Se connecter" stays outside, because
  // burying the entry in a menu makes it disappear.
  $("menucompte").hidden = !on;
}

// ONE VIEW AT A TIME, AND THE ARBITRATION LIVES HERE. "Mes progrès" and
// "Discussions" live in two separately loaded modules: if each hid the other
// on its own, opening the second over the first would leave both halves on
// screen, or neither.
let currentView = "";

function showView(name) {
  // "" (the exercise) | "progres" | "forum" | "moderation"
  // "Mes exercices" merged into "Mes progrès": two destinations used to
  // answer "where do I stand", with two counts of the same exercises.
  currentView = name;
  $("vueprogres").hidden = name !== "progres";
  $("vueforum").hidden = name !== "forum";
  $("vuemoderation").hidden = name !== "moderation";
  $("travail").hidden = name !== "";
  $("mesprogres").textContent =
    name === "progres" ? "Retour à l'exercice" : "Mes progrès";
  $("discussions").textContent =
    name === "forum" ? "Retour à l'exercice" : "Discussions";
}

// AN EXERCISE'S STATUS, IN THE CORE. It used to live only in "Mes
// exercices": neither the catalog menu nor the workbench said "already
// solved", even though the data was already loaded. Knowing what one has
// done should not require switching screens.
//
// PUSHED BY `compte.js`, never pulled: the direction stays one-way, and the
// anonymous visitor -- who has no statuses -- triggers nothing.
let statuses = {};

function setStatuses(map) {
  statuses = map || {};
  renderMenu();
  renderStrip();
}

const STATUS_MARK = { solved: "✓", attempted: "•" };
const STATUS_WORD = { solved: "validé", attempted: "essayé" };
// The CSS classes stay "valide"/"essaye" -- style.css's selectors were left
// untouched on purpose, so the wire values need a translation on the way in.
const STATUS_CLASS = { solved: "valide", attempted: "essaye" };

const currentExercise = () => catalog.find(t => t.id === selectedId) || null;

// WHAT THE SUBMISSION FORMAT CAN DO, AND NOTHING ELSE. The one-piece
// `main.c` relies on `#define exercice N` to choose WHICH `main()` gets
// compiled: that only makes sense for "io" exercises, which are complete
// programs. A "unity" exercise is a module WITH NO `main()`, a quiz has no
// code at all, and offering the button there would promise a file that does
// not compile.
//
// TWO EXERCISES AT LEAST, because a file that bundles a single exercise
// bundles nothing: the student already has that code in front of them in
// the editor.
//
// THE RULE LIVES HERE, IN THE CORE, AND NOT IN `exporter.js`: it is what
// decides whether the button exists, and that must be known BEFORE fetching
// the module. A second copy in the module would silently drift from the
// first.
const EXPORT_MINIMUM = 2;
// VERIFICATIONS ARE NOT THERE: they are not part of the submission, and an
// io verification would sneak in with its own `#if exercice == N` among the
// exercise's own labs.
const exportableExercises = (group) =>
  catalog.filter(t => t.group === group && t.mode === "io" && !t.verification);
const isGroupExportable = (group) =>
  exportableExercises(group).length >= EXPORT_MINIMUM;

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

// WHAT A LOCK SAYS, and it must say a date: "not open yet" without "opens
// September 18" sends the student off to write an email.
function lockNote(entry) {
  if (!entry || entry.access === "available") return "";
  if (entry.access === "archived") return "archivé";
  const when = new Date(entry.available_from || "");
  return isNaN(when.getTime())
    ? "à venir"
    : "ouvre le " + when.toLocaleDateString(undefined,
                                             { day: "numeric", month: "long" });
}

// THE SHAPE THE REST OF THE PAGE READS. "Mes exercices", "Mes progrès" and
// the export need a flat list {id, mode, label, short, group, files,
// learning}; the catalog is a tree. One function translates, and it also
// keeps access and the date, which only exist here.
function catalogEntry(ex, group) {
  const learning = {};
  if (Array.isArray(ex.skills) && ex.skills.length) learning.skills = ex.skills;
  if (Array.isArray(ex.contexts) && ex.contexts.length) learning.context = ex.contexts[0];
  if (ex.difficulty) learning.difficulty = ex.difficulty;
  // `label` QUALIFIED, `short` BARE. "Mes exercices" already shows the
  // collection in its own column; "Mes progrès" and the export only have
  // this string -- and "ex.1" alone names an exercise in each of the ten
  // labs.
  return {
    id: ex.id, mode: ex.mode, short: ex.title, group: group,
    // Absent from the published catalog when false -- hence the `!!`.
    verification: !!ex.verification,
    label: group ? group.replace(/\s+/g, "") + " : " + ex.title : ex.title,
    files: (ex.files || []).map(f => ({ name: f.name })),
    learning: learning,
    access: ex.access,
    available_from: (ex.release || {}).available_from || "",
  };
}

function normalize(publishedCatalog) {
  const byId = new Map();
  for (const ex of publishedCatalog.exercises || []) {
    if (ex && typeof ex.id === "string") byId.set(ex.id, ex);
  }
  const tree = [];
  const classified = new Set();
  for (const col of publishedCatalog.collections || []) {
    const items = (col.items || []).filter(id => byId.has(id));
    if (!items.length) continue;
    const title = String(col.title || col.id || "");
    for (const id of items) classified.add(id);
    tree.push({ titre: title, access: col.access,
                 available_from: (col.release || {}).available_from || "",
                 items: items.map(id => catalogEntry(byId.get(id), title)) });
  }
  // AN EXERCISE MAY BE IN NO COLLECTION AT ALL (invariant 3 of the plan).
  // Publishing it must be enough to make it reachable, or forgetting one
  // collection line would make it disappear with nothing to flag it.
  const orphans = [...byId.keys()].filter(id => !classified.has(id));
  if (orphans.length) {
    tree.push({ titre: "Autres", access: "available", available_from: "",
                 items: orphans.map(id => catalogEntry(byId.get(id), "Autres")) });
  }
  collections = tree;
  // UNIQUE, AND IN COLLECTION ORDER. An exercise shared by two collections
  // displays twice in the menu -- that is the point of a cross-cutting path
  // -- but only counts once in a progression and only exports once into a
  // main.c.
  const seen = new Set();
  catalog = [];
  for (const col of tree) {
    for (const ex of col.items) {
      if (ex.access !== "available" || seen.has(ex.id)) continue;
      seen.add(ex.id);
      catalog.push(ex);
    }
  }
}

function menuRow(ex) {
  const row = document.createElement("button");
  row.type = "button";
  row.className = ex.id === selectedId ? "exline on" : "exline";
  row.dataset.id = ex.id;
  const name = document.createElement("span");
  name.className = "titre";
  name.textContent = ex.short;
  row.append(name);
  // THE STATUS, WHERE ONE CHOOSES.
  // MARKED, AND SPELLED OUT. A verification must be recognizable BEFORE it
  // is opened: that is what tells it apart from a practice exercise
  // (docs/gamification/mastery.md), and color alone would not say so.
  if (ex.verification) {
    row.append(node("span", "verif", "vérification"));
  }
  const done = statuses[ex.id];
  if (done) {
    const mark = node("span", "etat " + (STATUS_CLASS[done] || done),
                         (STATUS_MARK[done] || "") + " " + (STATUS_WORD[done] || done));
    row.append(mark);
  }
  const note = lockNote(ex);
  if (note) {
    // `aria-disabled` AND NOT `disabled`. A `disabled` button drops out of
    // the tab order: opening dates used to only exist for the mouse, when
    // they are the whole reason to keep the exercise displayed. It therefore
    // stays reachable, announced as unavailable, and with no click listener.
    row.setAttribute("aria-disabled", "true");
    row.className += " verrouille";
    const mark = document.createElement("span");
    mark.className = "cadenas";
    mark.textContent = "🔒 " + note;
    row.append(mark);
  } else {
    row.addEventListener("click", () => {
      $("menuex").open = false;
      fillExercises(ex.id);
    });
  }
  return row;
}

// ONE <details> PER COLLECTION, INSIDE THE MENU'S <details>. The browser
// knows how to collapse: no JS accordion, no open/closed state to track
// elsewhere.
// THE LAB STRIP: the displayed collection's OPEN exercises, with their
// status. This is the navigation a student does twenty times a session --
// going from ex.2 to ex.3 -- and it used to require opening a menu that
// covers the screen for a target one step away.
//
// IT DOES NOT REPLACE THE MENU: that one stays the switch between
// collections, which is rare, and it keeps locked exercises with their date.
// Two scopes, two mechanisms -- the usual global/local split.
//
// FEWER THAN TWO EXERCISES, NO STRIP: a strip of one item would help nothing
// and would steal a line from the statement.
// A SHORT LABEL, BECAUSE THERE ARE ELEVEN OF THEM. `short` is not bare
// despite its name: the content itself writes "TP5 : ex.1
// celcius_to_fahrenheit" in the title. Eleven thirty-character pills fill
// three lines and steal from the statement the room it needs -- when the
// full name is already shown right above, in `#now`.
//
// The number is kept, since it is how the course statement names them.
function stripLabel(ex) {
  const bare = (ex.short || "").replace(/^[^:]*:\s*/, "");
  const number = bare.match(/^ex\.?\s*(\d+)/i);
  if (number) return "ex." + number[1];
  // THE ELLIPSIS IS LOAD-BEARING: "convertir_en_radia" cut off flat reads
  // like a display bug, not like a shortcut.
  return bare.length > 20 ? bare.slice(0, 19) + "…" : bare;
}

function renderStrip() {
  const box = $("bandelabo");
  box.innerHTML = "";
  const tp = currentExercise();
  const neighbors = tp ? catalog.filter(t => t.group === tp.group) : [];
  box.hidden = neighbors.length < 2;
  if (box.hidden) return;
  for (const ex of neighbors) {
    const isCurrent = ex.id === selectedId;
    const status = statuses[ex.id] || "";
    const pill = node("button", "puce" + (isCurrent ? " on" : "")
                                 + (status ? " " + (STATUS_CLASS[status] || status) : ""),
                       stripLabel(ex));
    pill.type = "button";
    // THE FULL NAME STAYS REACHABLE: on hover for the mouse, and in
    // off-screen text for a reader -- the pill itself only says "ex.3".
    pill.setAttribute("title", ex.short);
    pill.append(node("span", "horsecran", " — " + ex.short));
    // `aria-current` RATHER THAN A COLOR: that is what says "you are here"
    // to a screen reader, and the `on` class means nothing to anyone else.
    if (isCurrent) pill.setAttribute("aria-current", "true");
    if (status) {
      // THE WORD IN ADDITION TO THE SIGN. A green check mark alone
      // disappears in black and white, under color blindness, and does not
      // read aloud.
      pill.append(node("i", "marque", STATUS_MARK[status] || ""));
      pill.setAttribute("title", ex.short + " — " + (STATUS_WORD[status] || status));
      pill.append(node("span", "horsecran", " — " + (STATUS_WORD[status] || status)));
    }
    pill.addEventListener("click", () => {
      if (ex.id !== selectedId) fillExercises(ex.id);
    });
    box.append(pill);
  }
}

function renderMenu() {
  const box = $("exliste");
  box.innerHTML = "";
  for (const col of collections) {
    const block = document.createElement("details");
    block.className = "col";
    // COLLAPSED EXCEPT THE ONE BEING WORKED ON: with eleven collections and
    // seventy-three exercises, unfolding all of them is the same as not
    // organizing anything.
    block.open = col.items.some(ex => ex.id === selectedId || ex.id === spotlighted);
    const head = document.createElement("summary");
    const title = document.createElement("span");
    title.textContent = col.titre;
    head.append(title);
    const note = lockNote(col);
    if (note) {
      const mark = document.createElement("span");
      mark.className = "cadenas";
      mark.textContent = "🔒 " + note;
      head.append(mark);
    }
    block.append(head);
    for (const ex of col.items) block.append(menuRow(ex));
    box.append(block);
  }
  const open = currentExercise();
  $("excourant").textContent = open ? open.short : "Exercices";
}

// `/catalog.json` IS THE ONLY SOURCE since phase 8. The `tps.json` fallback
// existed for pages left in a student's cache during the switch; that
// window is closed, and the rollback is once again what it is server-side: a
// `current.json` pointer to rewrite.
(async () => {
  let published = null;
  try {
    const r = await fetch(API("catalog.json"));
    if (r.ok) published = await r.json();
  } catch (e) { /* network, or nothing published: the message below settles it */ }
  if (!published || !Array.isArray(published.exercises)) {
    announceSystem("La liste des exercices n'a pas pu être chargée. Recharge la "
          + "page ; si ça recommence, préviens ton enseignant.", true);
    return;
  }
  normalize(published);
  if (!collections.length) {
    announceSystem("Aucun exercice n'est publié pour l'instant.");
    return;
  }
  // A DEEP LINK TO A LOCKED EXERCISE DOES NOT OPEN THE EXERCISE: it opens the
  // menu on its lock and its date. Sharing it early therefore bypasses
  // nothing, and does not look like a dead link either.
  const target = new URLSearchParams(location.search).get("tp") || "";
  const openable = catalog.some(t => t.id === target);
  if (target && !openable
      && collections.some(c => c.items.some(e => e.id === target))) {
    spotlighted = target;
    $("menuex").open = true;
  }
  fillExercises(openable ? target : (catalog[0] || {}).id || "");
  // EVERYTHING IS PUBLISHED, NOTHING IS OPEN YET: this is the normal state at
  // the start of a term, not an outage, and the menu carries the dates --
  // might as well open it.
  if (!catalog.length) {
    $("menuex").open = true;
    renderVerdict({ cls: "idle", titre: "Aucun exercice n'est encore ouvert.",
              texte: "Le menu « Exercices » donne la date d'ouverture de chacun." });
  }
})();

function navigate(step) {
  const i = catalog.findIndex(t => t.id === selectedId);
  const target = catalog[i + step];
  if (!target) return;
  fillExercises(target.id);
}
$("prev").addEventListener("click", () => navigate(-1));
$("next").addEventListener("click", () => navigate(1));

// THE NAME STAYS: `progres.js` calls it to open an exercise from its list,
// and renaming it would mean editing two modules for zero added behavior.
function fillExercises(preselect) {
  if (preselect) selectedId = preselect;
  renderMenu();
  renderStrip();
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

// THE SAVE STATUS, AND IT IS PERMANENT. It used to stay EMPTY until the
// student had typed for a second and a half: someone who just opened an
// exercise, or just pasted their code without touching it again, had no way
// to know whether their work was safe.
//
// AND IT SAYS WHERE, not only when. "saved at 14:32" does not answer the real
// question, which is "will I find this again on the other machine?".
function showDraftStatus(text, failed) {
  $("sauvegarde").textContent = text;
  $("sauvegarde").className = failed ? "rate" : "";
}

// THE EXPORT KEEPS ITS OWN SPOT, in the action bar, next to its button. The
// two messages used to share a slot and erase each other: "main.c exported"
// would replace "draft NOT saved", which was the page's only data-loss
// warning.
function announceExport(text, failed) {
  $("brouillon").textContent = text;
  $("brouillon").className = failed ? "rate" : "";
}

const twoDigits = (n) => String(n).padStart(2, "0");
const now = () => {
  const t = new Date();
  return twoDigits(t.getHours()) + ":" + twoDigits(t.getMinutes());
};

// THE WRITE ALONE, shared with the quiz: it too has a draft, of the same
// `{key: text}` shape, and it has neither tabs nor a template to cross.
function persistDrafts() {
  try {
    localStorage.setItem(DRAFTS_KEY, JSON.stringify(drafts));
  } catch (e) {
    showDraftStatus("NON enregistré — garde une copie de ton code", true);
    return false;
  }
  // "ON THIS DEVICE" IS THE HALF THAT WAS MISSING. Without an account, work
  // does not follow from one machine to another, and that is exactly what a
  // lab student must know BEFORE going home -- not discover on their own.
  // `syncDraft` will replace this text with "on your account" if the copy
  // succeeds.
  showDraftStatus("enregistré sur cet appareil · " + now());
  $("purger").hidden = false;
  return true;
}

function saveDraft() {
  if (currentId === null || activeFile === null) return;
  sources[activeFile] = $("code").value;
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
  const tp = currentExercise();
  // `currentId` IS WHAT THE EDITOR HOLDS, not what the menu shows. Filling it
  // in goes through the network since the detail loads on demand: setting it
  // here would attribute the previous exercise's code, still displayed, to
  // the new id as soon as the next saveDraft() runs. It is setupFiles that
  // sets it, once the editor is truly filled in.
  currentId = null;
  const quiz = tp && tp.mode === "quiz";
  const i = catalog.findIndex(t => t.id === selectedId);
  $("prev").disabled = i <= 0;
  $("next").disabled = i < 0 || i >= catalog.length - 1;
  $("editor").hidden = quiz;
  $("filewrap").hidden = quiz;
  $("quizwrap").hidden = !quiz;
  // THE EXPORT FOLLOWS THE DISPLAYED LAB, NOT THE EXERCISE: the submission
  // file covers the whole lab. The button therefore only exists on a lab
  // whose format can do something, and the module only loads on click.
  $("exporttp").hidden = !isGroupExportable(tp && tp.group);
  // Outside a quiz there is only one button and it is primary. In a quiz,
  // the current action is the displayed exercise: testing all 40 questions
  // stays possible, but stops being the default landing action.
  $("goex").hidden = !quiz;
  // THE IDLE LABEL GOES THROUGH `setBusy()`, which is also what replaces it
  // with "Test en cours…". Two places writing the same button would
  // eventually contradict each other -- typically, switching exercises
  // during a test would put "Tester" back on a button still busy.
  goSecondary = quiz;
  goLabel = quiz ? "Tester tout le quiz" : "Tester";
  setBusy(busy);

  $("now").innerHTML = "";
  if (tp) {
    const title = document.createElement("b");
    title.textContent = tp.label;
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = EXPECTED[tp.mode] || "";
    $("now").append(title, badge);
    // MARKED HERE TOO, not only in the menu. A verification must stay
    // recognizable once OPENED: this is where one decides to start it, and
    // the only other signal was a statement sentence that can be folded away.
    if (tp.verification) {
      $("now").append(node("span", "badge verif", "vérification — sans XP"));
    }
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

  showStatement(null);
  idleState();
  prepareExercise(tp, quiz, ++loadToken);
}

// THREE STATES, NOT TWO. "No statement online" and "the statement has not
// arrived" used to display identically: the student believed it was a
// property of the exercise, so they never retried -- when a reload would
// have been enough. `loadDetail` deliberately does not cache this fallback,
// so that retrying works.
function showStatement(text, failed) {
  const box = $("consignetexte");
  if (text === null) {
    box.textContent = "Chargement…";
    box.className = "vide";
    return;
  }
  box.textContent = failed
    ? "La consigne n'a pas pu être chargée. Tu peux quand même écrire et "
      + "tester : les noms de fichiers attendus, eux, sont déjà là."
    : text
      || "Cet exercice n'a pas de consigne en ligne. Reporte-toi à l'énoncé du "
       + "TP sur Moodle : les noms de fichiers et de fonctions attendus y sont.";
  box.className = text && !failed ? "" : "vide";
  if (!failed) return;
  // A BUTTON, NOT AN INVITATION TO RELOAD THE PAGE: reloading would lose the
  // not-yet-saved code of someone who just pasted their file.
  const retry = node("button", "nav", "Réessayer");
  retry.type = "button";
  retry.addEventListener("click", () => {
    const tp = currentExercise();
    if (!tp) return;
    showStatement(null);
    prepareExercise(tp, tp.mode === "quiz", ++loadToken);
  });
  box.append(retry);
}

const details = {};

// AN EXERCISE'S DETAIL, loaded when it is opened. The statement and the
// templates would make up three quarters of the catalog for 73 exercises of
// which only one is displayed; `/catalog.json` only carries a menu. Kept in
// memory: coming back to an already-seen exercise asks for nothing again.
async function loadDetail(id) {
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
    // Network down, missing detail: the page is not blocked. The statement
    // falls back to its default message, the editor to empty templates --
    // file NAMES come from the catalog and are therefore always there, so
    // one can still paste code and submit. The fallback is NOT cached: a
    // network that comes back must be able to retry.
    return { statement: "", files: [], panne: true };
  }
}

async function prepareExercise(tp, quiz, thisLoad) {
  if (!tp) { showStatement(""); return; }
  const detail = await loadDetail(tp.id);
  if (thisLoad !== loadToken) return;
  showStatement(detail.statement, detail.panne);
  if (quiz) {
    if (await activateModule("quiz", "le quiz")) ctester.quiz.load(tp.id);
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

let displayedLineCount = -1;

function gutter(n) {
  if (n === displayedLineCount) return;
  displayedLineCount = n;
  let s = "";
  for (let i = 1; i <= n; i++) s += i + "\n";
  $("gutter").textContent = s;
}

function paint() {
  $("hlcode").innerHTML = highlight($("code").value);
  gutter($("code").value.split("\n").length);
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
  if (!await activateModule("compte", "la partie « compte »")) return;
  // AWAITED, NOT FIRED INTO THE VOID. `startSignIn` does a network discovery
  // then a PKCE challenge: without this `await`, a failure becomes a
  // rejected promise nobody reads, and the button does NOTHING -- no
  // redirect, no message. That is exactly the failure that was observed.
  try {
    await ctester.compte.startSignIn();
  } catch (e) {
    announceSystem("La connexion n'a pas pu démarrer : " + e.message
          + ". Tu peux continuer sans compte : tout fonctionne pareil.", true);
  }
});
// A <details> does not close itself when clicked inside.
$("menucompte").addEventListener("click", (e) => {
  if (e.target && e.target.tagName === "BUTTON") $("menucompte").open = false;
});
// THE EXPORT WORKS WITH NO ACCOUNT, and that is intentional: this device's
// drafts are enough to assemble the file. The account only adds one thing --
// fetching exercises worked on from ANOTHER machine -- and `exporter.js`
// handles that on its own if there is a token. The message goes on the
// draft's line: it is the one right next to the button.
$("exporttp").addEventListener("click", async () => {
  if (!await activateModule("exporter", "l'export du TP")) return;
  const tp = currentExercise();
  if (tp) await ctester.exporter.exporter(tp.group, announceExport);
});
// THE BUTTON ONLY EXISTS SIGNED IN (refreshAccount), and the file only
// arrives on click: same contract as compte.js. A signed-in student who
// never opens their progress downloads none of it either.
$("mesprogres").addEventListener("click", async () => {
  if (!await activateModule("progres", "« Mes progrès »")) return;
  await ctester.progres.basculer();
});
// SAME CONTRACT AS "Mes progrès": the button only exists signed in AND if
// the deployment has moderators, and the file only comes down on click. A
// shortcut to the Discussions view's form, not a second form: this is where
// one looks for their name when not thinking about the forum.
$("identite").addEventListener("click", async () => {
  if (!await activateModule("forum", "les discussions")) return;
  await ctester.forum.ouvrirIdentite();
});
$("discussions").addEventListener("click", async () => {
  if (!await activateModule("forum", "les discussions")) return;
  await ctester.forum.basculer();
});
$("deconnexion").addEventListener("click", () => {
  if (ctester.compte) ctester.compte.signOut();
});
$("oublier").addEventListener("click", () => {
  if (ctester.compte) ctester.compte.oublier();
});

// THE ANONYMOUS PATH DOWNLOADS NOTHING ACCOUNT-RELATED. compte.js is only
// fetched if there is a session in progress, a sign-in return, or a click on
// "Se connecter": that is, never for the student passing through with no
// account, and that is the default path.
fetch(API("oidc.json")).then(r => r.json()).then(async (config) => {
  if (!config || !config.issuer || !config.client_id) return;
  oidc = config;
  const savedToken = sessionGet(TOKEN_KEY);
  token = savedToken || null;
  refreshAccount();
  if (!savedToken && !authCode) return;
  if (await activateModule("compte", "la partie « compte »")) await ctester.compte.demarrer();
}).catch(() => {});

Object.assign(ctester, {
  $: $,
  // `systeme` AND NOT `show`: the service channel. The modules' only two
  // calls -- a failed sign-in, a confirmed account deletion -- talk about
  // the service, never about the student's code. The verdict itself has no
  // reason to ever be written from a module.
  systeme: announceSystem,
  sessionGet: sessionGet,
  sessionSet: sessionSet,
  sessionDrop: sessionDrop,
  authCode: authCode,
  authState: authState,
  // The script loader, exposed for the forum's TWO rendering libraries
  // (`web/vendor/`). Same mechanism as the modules, same guarantees: one
  // promise per file, a failure never kept, and the caller decides what to
  // do when it does not arrive -- for the forum, falling back to plain text.
  charger: load,
  // The MODULE loader, the one that tells the student what did not arrive.
  // Exposed because "Mes progrès" (progres.js) also offers the export:
  // without it, progres.js would rewrite `load()` plus its two error
  // messages, and the missing half would always be those.
  activerModule: activateModule,
  // The theme: the core sets it (the button lives in the bar, and it exists
  // for the anonymous visitor too), `compte.js` syncs it with the account.
  appliquerTheme: applyTheme,
  retenirTheme: rememberTheme,
  themeCourant: currentTheme,
  // FUNCTIONS, NOT `get`s. `catalogue`, `token` and `oidc` are reassigned
  // after loading, so a copy would lie -- and `Object.assign` copies exactly
  // the VALUE of a getter, not the getter itself: `ctester.token` would have
  // stayed frozen at null for the whole visit, and everything that follows
  // an account (states, practice, draft syncing) would have failed
  // silently. This happened.
  catalogue: () => catalog,
  token: () => token,
  oidc: () => oidc,
  setToken: setToken,
  refreshAccount: refreshAccount,
  switchMode: switchMode,
  fillExercises: fillExercises,
  showDraftStatus: showDraftStatus,
  maintenant: now,
  poserStatuts: setStatuses,
  dernierVerdict: () => lastVerdict,
  // THE QUIZ'S DRAFT, local only: `/brouillon` validates the file names an
  // exercise declares, and a question id is not one of them. Same store,
  // same "Effacer mes brouillons" button.
  brouillon: (id) => drafts[id] || null,
  enregistrerBrouillon: (id, values) => {
    if (!id) return;
    drafts[id] = values;
    persistDrafts();
  },
  exerciceOuvert: () => currentId,
  // WHAT THE MENU SHOWS, when `currentId` is not yet set: the editor's fill-in
  // goes through the network, and the forum knows how to open before it has
  // come back.
  exerciceChoisi: () => selectedId,
  // THE EXPORT, AS SEEN FROM THE CORE: who gets a button (`groupeExportable`)
  // and what must be assembled (`exercicesExportables`). Both `exporter.js`
  // and `compte.js` read from here -- one rule, one place.
  exercicesExportables: exportableExercises,
  groupeExportable: isGroupExportable,
  afficherVue: showView,
  vue: () => currentView,
  // Skill labels are already here for the context bar: copying them into
  // progres.js would make two tables to keep in sync, one of which would go
  // stale silently.
  skillLabel: (id) => SKILL_LABELS[id] || id,
});

let keyboardEscape = false;
$("code").addEventListener("keydown", (e) => {
  if (e.key === "Escape") { keyboardEscape = true; return; }
  if (e.key !== "Tab" || e.ctrlKey || e.metaKey || e.altKey) {
    keyboardEscape = false;
    return;
  }
  if (keyboardEscape) { keyboardEscape = false; return; }
  e.preventDefault();
  const zone = $("code");
  const start = zone.selectionStart, end = zone.selectionEnd;
  zone.value = zone.value.slice(0, start) + "    " + zone.value.slice(end);
  zone.selectionStart = zone.selectionEnd = start + 4;
  paint();
});

let sources = {};
let activeFile = null;

function setupFiles(tp, templateFiles) {
  // NAMES are authoritative and come from the catalog -- the allow-list the
  // API checks a submission against. Templates come from the detail and may
  // be missing: a tab with no template opens empty.
  const templates = Object.fromEntries(
    (templateFiles || []).map(f => [f.name, f.template || ""]));
  const files = ((tp && tp.files && tp.files.length)
    ? tp.files : [{ name: "submission.c" }])
    .map(f => ({ name: f.name, template: templates[f.name] || "" }));
  sources = (tp && drafts[tp.id]) || null;
  // THE STARTING STATE IS SAID TOO. "Draft found" answers the "I'm coming
  // back after a break" task BEFORE one has to check whether the code is
  // really the one left behind; and on a fresh exercise, announcing that
  // saving is automatic avoids wondering where the missing "Enregistrer"
  // button is.
  showDraftStatus(sources ? "brouillon retrouvé" : "enregistrement automatique");
  if (!sources) {
    sources = {};
    for (const f of files) sources[f.name] = f.template || "";
  }
  activeFile = null;
  currentId = tp ? tp.id : null;
  $("tabs").innerHTML = "";
  for (const f of files) {
    const tab = document.createElement("button");
    tab.type = "button";
    tab.className = "tab";
    tab.textContent = f.name;
    tab.dataset.name = f.name;
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-controls", "edwrap");
    tab.addEventListener("click", () => activateTab(f.name));
    $("tabs").append(tab);
  }
  $("tabs").hidden = files.length <= 1;
  $("edtitle").hidden = files.length > 1;
  activateTab(files[0].name);
}

function activateTab(name) {
  if (activeFile !== null) sources[activeFile] = $("code").value;
  activeFile = name;
  $("edtitle").textContent = name;
  // THE FIELD HAD NO ACCESSIBLE NAME: `#edtitle` is a <span>, not a <label>.
  // A screen reader announced "text area", without saying which of the
  // module's two files was being edited.
  $("code").setAttribute("aria-label", "Code de " + name);
  $("code").value = sources[name] || "";
  for (const tab of $("tabs").children) {
    const isCurrent = tab.dataset.name === name;
    tab.className = isCurrent ? "tab on" : "tab";
    tab.setAttribute("aria-selected", isCurrent ? "true" : "false");
    tab.tabIndex = isCurrent ? 0 : -1;
  }
  paint();
}

$("tabs").addEventListener("keydown", (e) => {
  const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
  if (!step) return;
  const names = [...$("tabs").children].map(o => o.dataset.name);
  const i = names.indexOf(activeFile);
  if (i >= 0) activateTab(names[(i + step + names.length) % names.length]);
});

// IMPORT USED TO LOSE THE IMPORTED FILE. `saveDraft` was only called on the
// `input` event, and `input` DOES NOT FIRE when a script writes into a
// `<textarea>`: the file only existed in the DOM, and a reload -- or a tab
// closed by mistake -- would take it away without a word. It is the easiest
// way to lose code on the whole page.
$("file").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  const text = await f.text();
  // THE FILE GOES INTO THE TAB CARRYING ITS NAME, when there is one.
  // Importing `calendrier.c` over `calendrier.h` just because that is the
  // open tab is a silent overwrite, at the exact moment the student is
  // looking elsewhere -- they just picked a file in a system dialog.
  const target = Object.prototype.hasOwnProperty.call(sources, f.name)
    ? f.name : activeFile;
  if (target !== activeFile) activateTab(target);
  // WE ASK BEFORE OVERWRITING WORK: there is no undo in this editor, replaced
  // code is gone for good. An empty tab, or one still at its template, is not
  // worth a question.
  const replaced = ($("code").value || "").trim();
  if (replaced && typeof confirm === "function"
      && !confirm("Remplacer le contenu de « " + target + " » par « " + f.name
                  + " » ? Ce qui est écrit dans cet onglet sera perdu.")) {
    e.target.value = "";
    return;
  }
  $("code").value = text;
  paint();
  clearTimeout(saveTimer);
  saveDraft();
  // RESET THE FIELD TO EMPTY: without this, reimporting the SAME file after
  // fixing it on disk does not trigger `change`, and the button looks dead.
  e.target.value = "";
});

// THE ERROR CLASS, drawn from the reason the server wrote. A summary that
// repeated the whole sentence ("Cas 1 : ta sortie contient inf ou nan :
// division par zéro, ou une variable utilisée alors que…") did not scan at a
// glance: with three cases folded, one could not tell at a glance whether
// the program had crashed or simply miscalculated.
function caseClass(reason) {
  const r = reason || "";
  if (/n'a pas terminé|interrompu/.test(r)) return "n'a pas fini";
  if (/débordé de la mémoire/.test(r)) return "débordement mémoire";
  if (/terminé anormalement/.test(r)) return "a planté";
  return "mauvaise sortie";
}

// THE GRADING CONTRACT, WRITTEN OUT. The judge is MUCH more permissive than
// the student thinks -- `match_subsequence` accepts any text around the
// expected values -- and nobody told them. So they used to spend time
// guessing an output format that was never imposed.
//
// This reveals no answer: it says HOW the comparison works, not WHAT it
// compares against. THE EXAMPLE IS ALWAYS THE SAME, across every exercise,
// and it carries a value that is nobody's actual answer: an example that
// varied with the exercise would read as a hint about the expected answer.
const CONTRAT = "On lit les NOMBRES de ta sortie, dans l'ordre ; le texte autour "
              + "est libre. Par exemple, « Aire = 42 cm2 » et « 42 » sont lus de "
              + "la même façon.";

// The INPUTS as the program receives them, one per line. "stdin" means
// nothing to a beginner; "ton programme reçoit 12 puis 7" describes exactly
// what its two scanf calls do.
function caseInputs(stdin) {
  return (stdin || "").split("\n").map(v => v.trim()).filter(v => v !== "");
}

function caseRow(label, value, className) {
  const block = node("div", "champ" + (className ? " " + className : ""));
  block.append(node("span", "quoi", label));
  block.append(node("pre", "valeur", value));
  return block;
}

function cases(items) {
  const box = document.createElement("div");
  for (const c of items) {
    const wrap = document.createElement("details");
    wrap.className = "case";
    wrap.open = !box.children.length;
    const className = caseClass(c.reason);
    const why = document.createElement("summary");
    why.textContent = `Cas ${c.case} — ${className}`;
    const body = node("div", "corps");

    const received = caseInputs(c.stdin);
    body.append(caseRow(
      received.length === 1 ? "Ton programme reçoit :"
                          : "Ton programme reçoit, dans cet ordre :",
      received.length ? received.join("   puis   ")
                    : "rien — ce cas ne lui fournit aucune entrée"));

    body.append(caseRow("Ce qu'il a affiché :", c.stdout || "(rien)"));

    // THE NUMBERS THE JUDGE READ, surfaced at the same rank as the output.
    // This is the block's single most actionable piece of information -- it
    // takes apart the matching black box -- and it used to live in 12px gray
    // under everything else.
    if (c.nombres) {
      body.append(caseRow(
        "Les nombres que le juge y a lus :",
        c.nombres.length ? c.nombres.join(", ") : "aucun"));
    }

    if (c.stderr) body.append(caseRow("Sa sortie d'erreur :", c.stderr));

    // The server's reason, spelled out: it carries the diagnostics that are
    // actually useful ("inf ou nan", "aucun nombre").
    body.append(node("p", "pourquoi", c.reason));
    // The contract only makes sense for a VALUE comparison: a program that
    // crashed, or a case looking for a word, is not fixed by reformatting
    // its output.
    if (className === "mauvaise sortie" && !/mot attendu|mentionne/.test(c.reason || "")) {
      body.append(node("p", "contrat", CONTRAT));
    }
    wrap.append(why, body);
    box.append(wrap);
  }
  return box;
}

function warningsBlock(text) {
  const block = document.createElement("div");
  block.className = "avert";
  const title = document.createElement("div");
  title.className = "titre";
  title.textContent = "Avertissements du compilateur";
  const what = document.createElement("div");
  what.className = "quoi";
  what.textContent = "Ce n'est pas une erreur : ton programme compile. "
                   + "Mais gcc a remarqué ceci, et ça vaut le coup d'œil.";
  const body = document.createElement("pre");
  body.textContent = text;
  block.append(title, what, body);
  return block;
}

const UNITS = {quiz: "réponses justes", io: "cas réussis", unity: "tests réussis"};

// WHAT IS EXPECTED AS A SUBMISSION, by mode. All THREE modes, and not "quiz
// or the rest": a unity exercise expects a module with NO main(), and
// promising the opposite sends 42 of the 72 exercises straight into a
// linking error the student has no way to connect to the badge that asked
// for it.
const EXPECTED = {
  quiz: "réponses à saisir",
  io: "programme complet, avec son main()",
  unity: "module seul, sans main()",
};

// "Tester l'exercice" changes NOTHING about grading: the judge keeps the
// reference solution and grades the whole quiz, and it is from that
// complete verdict that the API derives "solved". Only the READING is
// restricted -- other exercises' questions leave the count and the list.
// A correct exercise therefore cannot validate a half-filled lab.
function restrictToScope(r, scope) {
  const wrong = (r.wrong || []).filter(w => scope.ids.indexOf(w.id) >= 0);
  return Object.assign({}, r, {
    total: scope.ids.length,
    passed: scope.ids.length - wrong.length,
    wrong: wrong,
  });
}

// THE NEXT OPEN EXERCISE, for the action following a success. `catalog` only
// carries open exercises: there is therefore no lock to sidestep.
function nextOpenExercise() {
  const i = catalog.findIndex(t => t.id === selectedId);
  return i >= 0 ? catalog[i + 1] || null : null;
}

// WHAT IS OFFERED AFTER A COMPLETE SUCCESS. A button, not a sentence: it is
// the only moment in the loop where the student has nothing left to fix, and
// the page used to offer them nothing.
function afterSuccess() {
  const next = nextOpenExercise();
  if (!next) {
    return { suite: "C'est le dernier exercice ouvert pour l'instant." };
  }
  return {
    suite: "Tu peux passer à la suite.",
    bouton: { libelle: "Ouvrir « " + next.short + " »",
              faire: () => fillExercises(next.id) },
  };
}

// WHAT IS SAID AFTER A TEST FAILURE, by mode. The judge ran the program: what
// is left to do is no longer making it run, it is reading what it produced.
const AFTER_FAILURE = {
  io: "Ouvre le cas qui échoue : il montre ce que ton programme a reçu et ce "
    + "qu'il a affiché.",
  unity: "Le nom de chaque vérification décrit le cas qu'elle teste.",
  quiz: "Corrige les réponses ci-dessus, puis relance le test.",
};

// TEST NAMES ARE WRITTEN FOR THE STUDENT -- one still has to say so. A list
// of bare ids (`test_pop_pile_vide`) does not announce itself as French; and
// silence about what is not shown reads as a lack of information rather than
// a decision.
function failedTests(names) {
  const block = node("div", "rates");
  block.append(node("p", "quoi", names.length === 1
    ? "Cette vérification a échoué. Son nom décrit le cas qu'elle teste :"
    : "Ces vérifications ont échoué. Leur nom décrit le cas qu'elles testent :"));
  block.append(list(names));
  block.append(node("p", "contrat",
    "Les valeurs attendues ne sont pas montrées : les trouver EST l'exercice."));
  return block;
}

function render(r, scope) {
  // A VERDICT CLEARS THE SYSTEM BANNER. Leaving "the server is unreachable"
  // above a result that just arrived would say two contradictory things.
  clearSystem();
  if (r.status !== "ok") {
    // A JUDGE FAILURE IS NOT A VERDICT. `error` covers two very different
    // things server-side: a student program crashing (steps to show) and an
    // internal error ("Erreur interne du juge", "Le juge a été interrompu"),
    // which is not about the code and has no business here.
    if (r.status === "error" && /juge/.test(r.message || "")) {
      announceSystem(r.message + " Ton code est enregistré.", true);
      // AND WE GO BACK TO IDLE: without this, the verdict stayed frozen on
      // "Envoi…" while the banner announced a failure -- two screens saying
      // two different things at the same time.
      idleState();
      return;
    }
    const outcome = OUTCOMES[r.status] || OUTCOMES.error;
    renderVerdict({
      cls: "bad",
      etapes: outcome.etapes,
      titre: outcome.titre,
      texte: r.message || "",
      detail: r.status === "compile_error" ? compilerOutput(r.gcc) : null,
      suite: outcome.suite,
    });
  } else {
    const frame = scope && r.kind === "quiz" ? " — " + scope.titre : "";
    if (scope && r.kind === "quiz") r = restrictToScope(r, scope);
    const all = r.passed === r.total;
    const title = `${r.passed} / ${r.total} ${UNITS[r.kind] || "réussis"}${frame}`;
    const bar = r.total > 0 ? ticks(r.passed, r.total) : null;
    // THE PROGRAM COMPILED AND IT RAN: the first two steps pass by
    // construction, we are only here because the judge could grade it.
    // ONLY TWO STEPS when the judge has graded: the count displayed right
    // below IS the tests' result, a third box would only repeat it.
    const steps = ["ok", "ok"];
    if (all) {
      const next = afterSuccess();
      renderVerdict({ cls: "ok", etapes: steps, compte: true, titre: title, bar: bar,
                suite: next.suite, bouton: next.bouton });
    } else if (r.kind === "quiz") {
      renderVerdict({ cls: "bad", etapes: steps, compte: true, titre: title, bar: bar,
                suite: AFTER_FAILURE.quiz,
                detail: list(r.wrong.map(w => {
        const group = ctester.quiz ? ctester.quiz.groupeDe(w.id) : "";
        const ex = group.match(/Exercice\s*\d+/i);
        const empty = !(w.given && w.given.trim());
        const given = empty ? "" : ` (tu as répondu « ${w.given} »)`;
        // Not answered is not wrong: red is reserved for actual errors.
        return {
          text: (ex ? ex[0] + " — " : "") + w.label + given
              + (w.hint ? " — " + w.hint : ""),
          cls: empty ? "rien" : "",
        };
      })) });
    } else if (r.kind === "io") {
      renderVerdict({ cls: "bad", etapes: steps, compte: true, titre: title, bar: bar,
                detail: cases(r.cases), suite: AFTER_FAILURE.io });
    } else {
      renderVerdict({ cls: "bad", etapes: steps, compte: true, titre: title, bar: bar,
                detail: r.failed.length ? failedTests(r.failed) : null,
                suite: AFTER_FAILURE.unity });
    }
  }
  if (r.warnings) out.append(warningsBlock(r.warnings));
  scrollResultIntoView();
}

// ON A SMALL SCREEN, THE RESULT SITS BELOW THE EDITOR AND OFF-SCREEN:
// clicking "Tester" visibly produced NOTHING there. We scroll it into view and
// put focus on it. On a large screen it is already in the grid, next to the
// editor, and stealing focus mid-correction would be worse than the problem.
function scrollResultIntoView() {
  const narrow = typeof matchMedia === "function"
              && matchMedia("(max-width: 900px)").matches;
  if (!narrow) return;
  if (out.scrollIntoView) out.scrollIntoView({ block: "start", behavior: "smooth" });
  if (out.focus) out.focus();
}

// NOT `disabled`, AND THAT IS DELIBERATE. Disabling the button that has
// focus drops it onto <body>: with a keyboard, one had to tab through the
// whole page again after EVERY submission. And a grayed-out button with no
// word reads as "broken" rather than "in progress". It therefore stays
// focusable, and it SAYS what it is doing.
//
// IT ALSO STAYS CLICKABLE, and that is not an oversight: a poll that never
// completes -- a stuck queue, a network drop between two heartbeats -- used
// to leave the student in front of a dead button, with no word and no way
// out. Clicking again is an unambiguous intent: the new test REPLACES the
// old one, whose verdict no longer matters. The real safeguard against
// hammering it is the server's quota (8s signed in, 15s otherwise), and it
// is already there.
let busy = false;
let goLabel = "Tester";
let goSecondary = false;

function setBusy(isBusy, text) {
  busy = isBusy;
  const say = text || "Test en cours…";
  $("go").textContent = isBusy ? say : goLabel;
  $("goex").textContent = isBusy ? say : "Tester l'exercice";
  for (const id of ["go", "goex"]) {
    // `aria-busy` only when it is ACTUALLY WORKING: during a quota countdown,
    // nothing is running, and announcing busy would be false.
    $(id).setAttribute("aria-busy", isBusy && !text ? "true" : "false");
  }
  $("go").className = (goSecondary ? "secondaire" : "") + (isBusy ? " occupe" : "");
  $("goex").className = isBusy ? "occupe" : "";
}

// A STALE POLL STAYS SILENT. Without this token, an abandoned test's verdict
// would overwrite the one for the test just launched -- and it would arrive
// LAST, so it is the one that would be read. Same mechanism as `loadToken`
// for loading an exercise, for the same reason.
let currentSubmissionToken = 0;

// --- Do not ask again for what was just asked -------------------------------
// Resending identical code costs a queue slot, a cooldown and a wait, for a
// verdict already on screen. So the page does not send it: it redisplays.
//
// IT ASSERTS NOTHING TO THE SERVER, and that is the only reason this
// shortcut is allowed here. A hash sent in the request, on the other hand,
// would CHOOSE which stored verdict comes back -- broken code plus the hash
// of a successful submission would yield `passed == total`, which the API
// turns into "validé" and into XP. Deciding not to bother the server needs no
// trust; dictating its answer would need all of it.
//
// `rejouer` COMES FROM THE SERVER: the worker sets it on any verdict it
// refuses to cache itself -- timeout, judge failure, and exercises whose
// program is randomized, which the page has no way to recognize on its own.
// The rule therefore lives in exactly one place.
//
// IN MEMORY ONLY: a page reload re-judges, which is the right default. It is
// a session shortcut, not a cache.
const alreadySubmitted = {};    // exercise -> {cle, verdict}
let forcedResend = null;   // the key a second click must resend anyway
let inFlight = null;         // {jeton, exercice, cle} of the submission in progress

// THE ETA COMES FROM THE SERVER (`eta`, in seconds): only it knows what each
// exercise costs and what is ahead of it. The page only puts it into French.
// An older API, or an `eta` of 0, returns nothing rather than inventing a
// number -- only the rank stays displayed.
function estimatedWait(seconds) {
  if (!(seconds > 0)) return "";
  if (seconds < 60) return ` (environ ${Math.ceil(seconds / 5) * 5} s)`;
  return ` (environ ${Math.ceil(seconds / 60)} min)`;
}

async function poll(id, tries, scope, submissionToken) {
  if (submissionToken !== currentSubmissionToken) return;
  const r = await fetch(API("r/" + id));
  if (submissionToken !== currentSubmissionToken) return;
  const body = await r.json().catch(() => ({state: "error"}));
  if (body.state === "done") {
    render(body, scope);
    // WE ONLY KEEP WHAT THE SERVER AGREES TO KEEP ITSELF.
    if (inFlight && inFlight.jeton === submissionToken && !body.rejouer
        && body.status !== "error") {
      alreadySubmitted[inFlight.exercice] = { cle: inFlight.cle, verdict: body };
    }
    // The API just derived this verdict's status: we REREAD the projections,
    // the page declares none of them.
    // THE VERDICT IS ALREADY ON SCREEN, and nothing that follows must be able
    // to spoil it: hence the `finally`. Without it, a private projection that
    // raised would leave both "Tester" buttons stuck on a perfectly correct
    // result.
    try {
      if (ctester.compte) {
        await Promise.all([ctester.compte.loadStates(),
                           ctester.compte.loadPractice()]);
      }
      // The API may have just granted a first solve's XP. We REQUEST the
      // projection again from the server -- the page computes none of it.
      // Nothing to refresh as long as the module has never been opened: it
      // will fetch fresh state on its first display.
      if (ctester.progres) await ctester.progres.rafraichir();
    } finally {
      setBusy(false);
    }
    return;
  }
  if (r.status === 404 || tries <= 0) {
    // LOSING A VERDICT IS A SERVICE FAILURE, not a judgment on the code.
    announceSystem("Le résultat de ce test s'est perdu. Ton code est enregistré — "
          + "relance simplement le test.", true);
    setBusy(false);
    return;
  }
  // "COMPILATION EN COURS" WAS WRONG HALF THE TIME: `running` covers
  // compilation, execution AND tests -- the worker does not report a
  // sub-state. Announcing a stage we do not know precisely shapes the wrong
  // mental model in the person who has the least of it.
  renderVerdict({
    cls: "wait",
    titre: body.state === "running"
      ? "Test en cours…"
      : `En file d'attente — ${body.position}${body.position === 1 ? "er" : "e"}`
        + estimatedWait(body.eta),
  });
  setTimeout(() => poll(id, tries - 1, scope, submissionToken), 2000);
}

// A QUOTA IS NOT A REFUSAL OF THE CODE. The API already returns
// `retry_after`; the page used to ignore it and display the raw message in
// red, where the verdict goes -- "my code was refused". We put it in the
// service channel, count it down on the button, and reopen on our own:
// re-clicking only used to be a way to get annoyed.
let countdown = null;

function waitForQuota(seconds) {
  clearTimeout(countdown);
  let remaining = Math.max(1, Math.round(seconds));
  (function tick() {
    if (remaining <= 0) {
      setBusy(false);
      clearSystem();
      return;
    }
    setBusy(true, "Nouveau test dans " + remaining + " s");
    announceSystem("Tu as lancé plusieurs tests coup sur coup. Le prochain part dans "
          + remaining + " s — ton code est enregistré, tu peux continuer à l'écrire.");
    remaining--;
    countdown = setTimeout(tick, 1000);
  })();
}

// `scope`: the displayed exercise's ids, or null for the whole lab.
async function submitCode(scope) {
  const tp = currentExercise();
  if (!tp) { announceSystem("Choisis un exercice dans le menu pour commencer."); return; }
  // WE DO NOT SEND A SUBMISSION WE KNOW WILL BE REFUSED: the server's 403
  // says "clé de session invalide ou expirée", which helps nobody.
  if (!key) {
    announceSystem("Il manque ta clé d'accès. Rouvre le lien de CTester depuis Moodle "
        + "pour pouvoir tester ton code. Tu peux écrire en attendant : "
        + "ton brouillon est enregistré.");
    return;
  }
  const body = {key, exercise_id: tp.id};
  if (tp.mode === "quiz") {
    if (!ctester.quiz) {
      announceSystem("Le quiz n'a pas pu être chargé. Recharge la page.", true);
      return;
    }
    body.answers = ctester.quiz.answers();
    // NOTHING TO TEST IS NOT A FAILURE. In red, at 2.1rem, where the verdict
    // goes, it used to scold someone who had just opened the exercise and
    // clicked to see what the button does.
    if (!Object.values(body.answers).some(v => v.trim())) {
      announceSystem("Saisis au moins une réponse avant de tester."); return;
    }
  } else {
    sources[activeFile] = $("code").value;
    body.files = sources;
    if (!Object.values(sources).some(v => v.trim())) {
      announceSystem("Il n'y a encore rien à tester : écris ou colle ton code d'abord.");
      return;
    }
  }
  // THE SAME CODE AS LAST TIME HAS NOTHING TO ASK AGAIN. No request goes out
  // at all, so neither cooldown, nor queue slot, nor wait.
  const submissionKey = JSON.stringify(body.answers || body.files);
  const known = alreadySubmitted[tp.id];
  if (known && known.cle === submissionKey && forcedResend !== submissionKey) {
    // THE SECOND CLICK RESENDS, and this escape hatch is not optional: a test
    // case fixed by the five-minute tick would make the kept verdict wrong,
    // and the page has no way to learn that. Without it, the button would
    // look broken.
    forcedResend = submissionKey;
    render(known.verdict, scope);
    announceSystem("Même code que ta dernière soumission — voici son verdict, sans "
          + "reprendre de place dans la file. Clique encore pour le renvoyer "
          + "au juge.");
    return;
  }
  forcedResend = null;
  const submissionToken = ++currentSubmissionToken;
  inFlight = { jeton: submissionToken, exercice: tp.id, cle: submissionKey };
  clearSystem();
  setBusy(true);
  renderVerdict({ cls: "wait", titre: "Envoi…" });
  try {
    const r = await fetch(API("submit?poste=" + encodeURIComponent(stationId())), {
      method: "POST",
      // Signing in is optional: with no token, the submission stays
      // anonymous. With one, the API can attach the job to the account and
      // record practice/status from its own verdict.
      headers: Object.assign({"Content-Type": "application/json"},
                             token ? {Authorization: "Bearer " + token} : {}),
      body: JSON.stringify(body)
    });
    let out = null;
    try { out = await r.json(); } catch (parseError) { out = null; }
    // THE QUOTA HAS ITS OWN PATH: `retry_after` was always sent by the API
    // and always discarded by the page.
    if (r.status === 429 && out && out.retry_after) {
      // The submission never actually left: the verdict goes back to idle
      // rather than staying on "Envoi…", which would be false.
      idleState();
      waitForQuota(out.retry_after);
      return;
    }
    if (!r.ok || !out) {
      announceSystem((out && out.error)
              || `Le serveur a répondu ${r.status} et n'a pas pris ta `
                 + `soumission. Ton code est enregistré — réessaie dans un instant.`,
              true);
      setBusy(false);
      return;
    }
    poll(out.id, 150, scope, submissionToken);
  } catch (e) {
    announceSystem("Le serveur ne répond pas. Ton code est enregistré sur cet "
          + "appareil ; réessaie dans un instant.", true);
    setBusy(false);
  }
}

// THE CLICK IS IGNORED DURING A TEST, and that is what replaces `disabled`:
// see `setBusy()`. The button stays focusable, so tabbing does not restart
// from the top of the page on every submission.
// THE PROMISE IS RETURNED, and that is not cosmetic: the test harness waits
// for the click to know the submission left. A guard in a block body would
// return `undefined`, and everything that follows would run before the
// fetch.
$("go").addEventListener("click", () => submitCode(null));
$("goex").addEventListener("click", () =>
  submitCode(ctester.quiz ? ctester.quiz.page() : null));

// --- Presence counter, for everyone -----------------------------------------
// One heartbeat every 60s to /live, which only touches an in-memory dict
// server-side (no database, no account). This is the ONLY request the
// anonymous path ever emits. ponytail: a randomly drawn window id kept for
// the life of the tab -- falsifiable, but it is a displayed number, not a
// lock. A failure of the counter is invisible: it just stays hidden.
let liveId = sessionGet("ctester.live");
if (!liveId) {
  liveId = (typeof crypto !== "undefined" && crypto.randomUUID)
    ? crypto.randomUUID()
    : String(Math.random()).slice(2) + Date.now();
  sessionSet("ctester.live", liveId);
}
async function heartbeat() {
  try {
    const r = await fetch(API("live?id=" + encodeURIComponent(liveId)));
    const d = await r.json();
    if (d && typeof d.n === "number") {
      $("live").textContent =
        d.n > 1 ? d.n + " personnes en ligne" : "1 personne en ligne";
      $("live").hidden = false;
    }
  } catch (e) { /* cosmetic: /live going down bothers nobody */ }
}
heartbeat();
setInterval(heartbeat, 60000);
