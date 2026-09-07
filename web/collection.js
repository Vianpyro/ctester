// The collection: the cards a signed-in account has earned, and the ones it
// has not. Loaded ON CLICK, never before -- same contract as compte.js,
// progres.js and leaderboard.js, same reasons.
//
// A CARD IS A TRACE, NOT AN ADVANTAGE. Nothing here is drawn at random,
// nothing is bought, nothing expires, and holding a card grants no XP, no
// access and no standing. What it says is "you did this", which is the only
// kind of collectible that survives docs/gamification/student-motivations.md.
//
// A LOCKED CARD IS SHOWN, WITH ITS CONDITION, and that is the whole
// difference from a loot box: one can read what to do to get it, decide it is
// not worth it, and lose nothing.
//
// NOTHING IS COMPUTED HERE. Which cards are held, and how rare each one is,
// arrive decided from `GET /collection`. Rarity is an OBSERVED rate -- the
// share of practising accounts that hold it -- and the server withholds it
// entirely under a minimum cohort, because a percentage over four people
// describes those four people.
(function (ctester) {
const $ = ctester.$;

let projection = null;
let error = "";

async function load() {
  if (!ctester.compte) {
    projection = null;
    error = "Reconnecte-toi pour voir ta collection.";
    return;
  }
  const response = await ctester.compte.getJson("collection");
  if (!response || !Array.isArray(response.cards)) {
    projection = null;
    error = "Ta collection n'est pas disponible pour l'instant. L'exercice et "
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

// --- The drawings ------------------------------------------------------------
// INLINE SVG, BUILT NODE BY NODE, never `innerHTML`. These strings are ours
// and not a student's, so the risk is nil today -- but `rendreMarkdown` in
// forum.js holds the page's ONLY `innerHTML` on purpose, and adding a second
// one here would make that sentence false for whoever reads it next.
//
// ONE PATH PER PART, in the vocabulary of a schematic: this is the same
// drawing language as the blueprint frames, which is what makes the grid read
// as one system rather than as eight clip-art icons.
const SVG_NS = "http://www.w3.org/2000/svg";

function shape(tag, attributes) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const name in attributes) el.setAttribute(name, attributes[name]);
  return el;
}

function drawing(paths) {
  const svg = shape("svg", { viewBox: "0 0 96 64", width: "96", height: "64",
                             fill: "none", stroke: "currentColor",
                             "stroke-width": "1.5", "stroke-linecap": "round",
                             "aria-hidden": "true" });
  for (const p of paths) svg.append(shape(p.tag, p));
  return svg;
}

const path = (d) => ({ tag: "path", d: d });
const circle = (cx, cy, r) => ({ tag: "circle", cx: cx, cy: cy, r: r });

// THE FAMILY DECIDES THE DRAWING, not the card id: a new card in an existing
// family gets a sensible picture with no edit here. An unknown family falls
// back to the frame, which is honest -- better a plain card than a wrong part.
const DRAWINGS = {
  "E-01": [path("M6 32h18l6-12 8 24 8-24 8 24 6-12h18")],
  "M-04": [circle(48, 32, 22), circle(48, 32, 9), circle(48, 16.5, 3.5),
           circle(48, 47.5, 3.5), circle(32.5, 32, 3.5), circle(63.5, 32, 3.5)],
  "E-07": [{ tag: "rect", x: 14, y: 14, width: 68, height: 36 },
           path("M26 40V24m8 16V24m8 16V24"), path("M56 42l20-14"),
           circle(56, 42, 2.5)],
  "M-02": [circle(48, 32, 16), circle(48, 32, 5),
           path("M48 8v8m0 32v8M24 32h8m32 0h8M31 15l6 6m22 22l6 6m0-34l-6 6m-22 22l-6 6")],
  "P-03": [{ tag: "rect", x: 10, y: 20, width: 44, height: 24 },
           path("M54 32h30M78 26v12")],
  "E-12": [path("M8 32h24m56 0H64"), path("M32 18l32 14-32 14z"), path("M64 18v28")],
  "M-09": [path("M8 32h10m60 0h10"),
           path("M18 32l6-12 8 24 8-24 8 24 8-24 8 24 6-12")],
  "P-06": [circle(34, 32, 14), path("M34 32l10-9"), path("M54 22h30M54 32h30M54 42h18")],
};

// --- Rendering ----------------------------------------------------------------

function card(c) {
  const box = node("div", "card " + (c.held ? "held" : "locked"));
  const head = node("div", "entete");
  head.append(node("span", "code", c.id));
  // A RARITY OF `null` IS NOT A ZERO. It means "too few accounts to say", and
  // printing "0 %" there would be a made-up number about real people.
  head.append(node("span", "code", c.rarity === null || c.rarity === undefined
    ? "—" : c.rarity + " %"));
  box.append(head);
  const art = node("div", "dessin");
  if (DRAWINGS[c.id]) art.append(drawing(DRAWINGS[c.id]));
  box.append(art);
  box.append(node("div", "name", c.name));
  // THE CONDITION IS ALWAYS PRINTED, held or not: on a held card it says what
  // it was earned for, which is the whole point of a trace.
  box.append(node("div", "quoi", c.held ? c.condition : "verrouillée · " + c.condition));
  // The state in words, for a reader: the frame and the tint say it to
  // everyone else, and neither reads aloud.
  box.append(node("span", "horsecran", c.held ? " — obtenue" : " — pas encore obtenue"));
  return box;
}

function render() {
  const box = $("viewcollection");
  box.innerHTML = "";
  const head = node("h2", "", "Ma collection");
  head.id = "collectiontitle";
  head.tabIndex = -1;
  box.append(head);
  if (!projection) {
    // WE DO NOT INVENT AN EMPTY COLLECTION. A grid of eight locked cards
    // during an outage tells someone they have earned nothing, and that
    // would be false.
    box.append(node("p", "rate", error));
    return;
  }
  const held = projection.cards.filter(c => c.held).length;
  box.append(node("p", "aide", held + " pièce" + (held > 1 ? "s" : "") + " sur "
    + projection.cards.length + " · privée par défaut"));
  const grid = node("div", "cards");
  for (const c of projection.cards) grid.append(card(c));
  box.append(grid);
  box.append(node("p", "aide", "Une carte grise est encore verrouillée et dit à "
    + "quelle condition elle tombe — rien de caché derrière un tirage au sort, "
    + "rien qui s'achète, rien qui expire. Une carte ne donne aucun avantage : "
    + "c'est une trace de ce que tu as fait."));
  // The rarity's denominator, said out loud: "34 %" means nothing without
  // "of whom", and a number one cannot situate is decoration.
  box.append(node("p", "aide", projection.cohort
    ? "Le pourcentage est la part des comptes ayant pratiqué qui possèdent la "
      + "carte, mesurée — jamais une rareté décrétée."
    : "Les pourcentages apparaîtront quand assez de comptes auront pratiqué."));
}

// --- Entry points -------------------------------------------------------------

async function toggle() {
  if (ctester.vue() === "collection") { ctester.afficherVue(""); return; }
  await load();
  render();
  ctester.afficherVue("collection");
  const head = $("collectiontitle");
  if (head && head.focus) head.focus();
}

function forget() {
  projection = null;
  error = "";
  if (ctester.vue() === "collection") ctester.afficherVue("");
}

ctester.collection = {
  basculer: toggle,
  oublier: forget,
  projection: () => projection,
};
})(window.ctester);
