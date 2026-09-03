// Le quiz : chargé quand un exercice de ce mode est ouvert, jamais avant.
// Un seul TP sur cinq est un quiz, et ces 90 lignes ne servent à personne
// d'autre. Voir le chargeur `charger()` dans app.js.
//
// SENS UNIQUE, JAMAIS DE CYCLE : ce fichier lit `window.ctester` et y dépose
// ses entrées ; il n'appelle app.js que par ce que ce contexte lui donne.
(function (ctester) {
const $ = ctester.$;

let pagesQuiz = [];
let pageQuiz = 0;
let groupeDeQuestion = {};

async function loadQuiz(id) {
  const box = $("quiz");
  box.textContent = "Chargement…";
  const data = await (await fetch("quiz/" + id + ".json")).json();
  box.innerHTML = "";
  pagesQuiz = [];
  groupeDeQuestion = {};
  let courante = null;
  for (const q of data.questions) {
    groupeDeQuestion[q.id] = q.group;
    if (!courante || courante.titre !== q.group) {
      courante = { titre: q.group, noeud: document.createElement("div") };
      pagesQuiz.push(courante);
      const head = document.createElement("div");
      head.className = "qgroup";
      head.textContent = q.group;
      courante.noeud.append(head);
      box.append(courante.noeud);
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
    row.append(label, input);
    courante.noeud.append(row);
  }
  construireNavQuiz();
  montrerPage(0);
}

function construireNavQuiz() {
  const nav = $("quiznav");
  nav.innerHTML = "";
  nav.hidden = pagesQuiz.length <= 1;
  if (nav.hidden) return;
  const avant = document.createElement("button");
  avant.type = "button";
  avant.className = "nav";
  avant.id = "qprev";
  avant.textContent = "‹ Précédent";
  avant.addEventListener("click", () => montrerPage(pageQuiz - 1));
  const pos = document.createElement("span");
  pos.className = "pos";
  pos.id = "qpos";
  const apres = document.createElement("button");
  apres.type = "button";
  apres.className = "nav";
  apres.id = "qnext";
  apres.textContent = "Suivant ›";
  apres.addEventListener("click", () => montrerPage(pageQuiz + 1));
  nav.append(avant, pos, apres);
}

function montrerPage(i) {
  if (!pagesQuiz.length) return;
  pageQuiz = Math.min(Math.max(i, 0), pagesQuiz.length - 1);
  pagesQuiz.forEach((p, n) => { p.noeud.hidden = n !== pageQuiz; });
  if ($("quiznav").hidden) return;
  $("qpos").textContent = `page ${pageQuiz + 1} sur ${pagesQuiz.length}`;
  $("qprev").disabled = pageQuiz === 0;
  $("qnext").disabled = pageQuiz === pagesQuiz.length - 1;
}

const answers = () => Object.fromEntries(
  [...$("quiz").querySelectorAll("input[data-qid]")].map(i => [i.dataset.qid, i.value])
);

// La PAGE COURANTE, c'est l'exercice courant : `construireNavQuiz` découpe
// déjà les pages sur le groupe. « Tester l'exercice » n'a donc rien à
// redécouper, il demande les identifiants de la page affichée.
const pageCourante = () => {
  const titre = pagesQuiz.length ? pagesQuiz[pageQuiz].titre : "";
  return {
    titre: titre,
    ids: Object.keys(groupeDeQuestion).filter(id => groupeDeQuestion[id] === titre),
  };
};

ctester.quiz = {
  load: loadQuiz,
  answers: answers,
  page: pageCourante,
  // `render` s'en sert pour nommer l'exercice d'une réponse fausse.
  groupeDe: (qid) => groupeDeQuestion[qid] || "",
};
})(window.ctester);
