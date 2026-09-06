// The quiz: loaded when an exercise of this mode is opened, never before.
// Only one lab in five is a quiz, and these 90 lines serve nobody else. See
// the loader `charger()` in app.js.
//
// ONE WAY, NEVER A CYCLE: this file reads `window.ctester` and deposits its
// own entries into it; it only calls app.js through what that context gives
// it.
(function (ctester) {
const $ = ctester.$;

let quizPages = [];
let quizPage = 0;
let questionGroup = {};
let quizExercise = null;
let timer = null;

// SAME CONTRACT AS THE EDITOR: what was typed in is there on return. The
// store is app.js's own, so "Effacer mes brouillons" erases the answers too.
// One listener, set once: the module only loads once, but `loadQuiz` gets
// called again on the same node.
$("quiz").addEventListener("input", () => {
  clearTimeout(timer);
  timer = setTimeout(
    () => ctester.enregistrerBrouillon(quizExercise, answers()), 1500);
});

async function loadQuiz(id) {
  const box = $("quiz");
  box.textContent = "Chargement…";
  const data = await (await fetch(API("quiz/" + id + ".json"))).json();
  const draft = ctester.brouillon(id) || {};
  quizExercise = id;
  box.innerHTML = "";
  quizPages = [];
  questionGroup = {};
  let currentGroup = null;
  for (const q of data.questions) {
    questionGroup[q.id] = q.group;
    if (!currentGroup || currentGroup.titre !== q.group) {
      currentGroup = { titre: q.group, noeud: document.createElement("div") };
      quizPages.push(currentGroup);
      const head = document.createElement("div");
      head.className = "qgroup";
      head.textContent = q.group;
      currentGroup.noeud.append(head);
      box.append(currentGroup.noeud);
    }
    const row = document.createElement("div");
    row.className = "qrow";
    const label = document.createElement("span");
    label.textContent = q.label;
    const input = document.createElement("input");
    input.type = "text";
    input.spellcheck = false;
    input.autocomplete = "off";
    input.dataset.qid = q.id;
    input.value = draft[q.id] || "";
    row.append(label, input);
    currentGroup.noeud.append(row);
  }
  buildQuizNav();
  showPage(0);
}

function buildQuizNav() {
  const nav = $("quiznav");
  nav.innerHTML = "";
  nav.hidden = quizPages.length <= 1;
  if (nav.hidden) return;
  const prev = document.createElement("button");
  prev.type = "button";
  prev.className = "nav";
  prev.id = "qprev";
  prev.textContent = "‹ Précédent";
  prev.addEventListener("click", () => showPage(quizPage - 1));
  const pos = document.createElement("span");
  pos.className = "pos";
  pos.id = "qpos";
  const next = document.createElement("button");
  next.type = "button";
  next.className = "nav";
  next.id = "qnext";
  next.textContent = "Suivant ›";
  next.addEventListener("click", () => showPage(quizPage + 1));
  nav.append(prev, pos, next);
}

function showPage(i) {
  if (!quizPages.length) return;
  quizPage = Math.min(Math.max(i, 0), quizPages.length - 1);
  quizPages.forEach((p, n) => { p.noeud.hidden = n !== quizPage; });
  if ($("quiznav").hidden) return;
  $("qpos").textContent = `page ${quizPage + 1} sur ${quizPages.length}`;
  $("qprev").disabled = quizPage === 0;
  $("qnext").disabled = quizPage === quizPages.length - 1;
}

const answers = () => Object.fromEntries(
  [...$("quiz").querySelectorAll("input[data-qid]")].map(i => [i.dataset.qid, i.value])
);

// THE CURRENT PAGE is the current exercise: `buildQuizNav` already splits
// pages by group. "Tester l'exercice" therefore has nothing to re-split, it
// just asks for the displayed page's ids.
const currentPage = () => {
  const title = quizPages.length ? quizPages[quizPage].titre : "";
  return {
    titre: title,
    ids: Object.keys(questionGroup).filter(id => questionGroup[id] === title),
  };
};

ctester.quiz = {
  load: loadQuiz,
  answers: answers,
  page: currentPage,
  // `render` uses it to name the exercise of a wrong answer.
  groupeDe: (qid) => questionGroup[qid] || "",
};
})(window.ctester);
