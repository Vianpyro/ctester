// Exécute VRAIMENT le JS de index.html, avec un DOM minimal en trompe-l'oeil.
// C'est le contrôle que `node --check` ne peut pas faire : la seule panne que
// cette page ait connue en production était une ReferenceError de zone morte
// temporelle -- une erreur d'exécution, pas de syntaxe.
//
//   node test_page.js [app/index.html]
const fs = require("fs");

const html = fs.readFileSync(process.argv[2] || __dirname + "/app/index.html", "utf8");
const js = html.match(/<script>([\s\S]*)<\/script>/)[1];

// --- DOM en carton --------------------------------------------------------
function el(id) {
  const node = {
    id, value: "", hidden: false, className: "", textContent: "",
    disabled: false, tabIndex: 0, dataset: {}, files: [], children: [],
    listeners: {}, attrs: {}, selectionStart: 0, selectionEnd: 0,
    setAttribute(k, v) { this.attrs[k] = v; },
    getAttribute(k) { return this.attrs[k]; },
    addEventListener(ev, fn) { this.listeners[ev] = fn; },
    append(...kids) {
      this.children.push(...kids);
      // FIDÉLITÉ AU NAVIGATEUR, et elle est load-bearing : un <select> adopte
      // la première option comme valeur courante dès qu'on la lui ajoute. Sans
      // ça, le harnais testerait un menu qui ne sélectionne jamais rien et
      // laisserait passer un bug bien réel.
      const opts = this.children.filter(k => k.value);
      if (opts.length && !opts.some(k => k.value === this.value)) {
        this.value = opts[0].value;
      }
    },
    // Le sélecteur est ignoré : la page n'en utilise qu'un seul, et parser du
    // CSS pour un harnais serait un projet à part. On rend les descendants qui
    // portent un data-qid, ce que fait `input[data-qid]`.
    querySelectorAll() {
      const trouves = [];
      (function descendre(n) {
        for (const k of n.children) {
          if (k.dataset && k.dataset.qid) trouves.push(k);
          descendre(k);
        }
      })(this);
      return trouves;
    },
  };
  let html = "";
  Object.defineProperty(node, "innerHTML", {
    get: () => html,
    set(v) { html = v; if (v === "") node.children.length = 0; },
  });
  let ident = id;
  Object.defineProperty(node, "id", {
    get: () => ident,
    // Un élément créé dynamiquement puis nommé doit devenir trouvable par
    // getElementById, comme dans un vrai document : la pagination du quiz crée
    // ses boutons puis les récupère par identifiant.
    set(v) { ident = v; nodes[v] = node; },
  });
  return node;
}
const nodes = {};
global.document = {
  getElementById: (id) => (nodes[id] ||= el(id)),
  createElement: (tag) => el("<" + tag + ">"),
};
global.location = { search: "?k=cle-de-test" };
global.URLSearchParams = URLSearchParams;

// Les minuteurs sont CAPTURÉS, pas exécutés. La page en pose deux sortes : le
// sondage du verdict, qu'on ne veut surtout pas voir boucler dans un test, et
// le délai d'enregistrement du brouillon, qu'on veut déclencher à la main
// plutôt que d'attendre 1,5 seconde réelle.
const timers = [];
global.setTimeout = (fn) => timers.push(fn);
global.clearTimeout = () => {};
const declencherDernierMinuteur = () => timers[timers.length - 1]();

// Stockage en carton, avec un interrupteur de panne : navigation privée, quota
// plein, stockage désactivé par une politique d'école. C'est le cas qui ne doit
// JAMAIS afficher « enregistré ».
let stockageEnPanne = false;
const stockage = {};
global.localStorage = {
  getItem: (k) => (k in stockage ? stockage[k] : null),
  setItem: (k, v) => {
    if (stockageEnPanne) throw new Error("QuotaExceededError");
    stockage[k] = v;
  },
  removeItem: (k) => { delete stockage[k]; },
};

const UN_FICHIER = [{ name: "submission.c", template: "" }];
const CATALOGUE = [
  { id: "tp1", mode: "quiz", label: "TP1 : encodage binaire",
    group: "TP 1", short: "encodage binaire", files: [] },
  { id: "tp2-ex0", mode: "io", label: "TP2 : ex.0 âge",
    group: "TP 2", short: "ex.0 âge", files: UN_FICHIER },
  { id: "tp2-ex3", mode: "io", label: "TP2 : ex.3 loi d'Ohm",
    group: "TP 2", short: "ex.3 loi d'Ohm", files: UN_FICHIER },
  { id: "tp6-ex1", mode: "unity", label: "TP6 : ex.1 est_bissextile",
    group: "TP 6", short: "ex.1 est_bissextile",
    files: [{ name: "calendrier.h", template: "#define VRAI 1\n" },
            { name: "calendrier.c", template: "#include \"calendrier.h\"\n" }] },
];

const calls = [];
let SUBMIT_RESPONSE;
let POLL_RESPONSE = { state: "queued", position: 1 };
global.fetch = async (url, opts) => {
  calls.push({ url, opts });
  if (url === "tps.json") {
    return { ok: true, status: 200, json: async () => CATALOGUE };
  }
  if (url.startsWith("quiz/")) {
    return { ok: true, status: 200, json: async () => ({
      label: "TP1", questions: [
        { id: "q1", group: "Exercice 1 : binaire", label: "23", type: "bin8" },
        { id: "q2", group: "Exercice 1 : binaire", label: "167", type: "bin8" },
        { id: "q3", group: "Exercice 2 : hexadécimal", label: "23", type: "hex8" },
      ] }) };
  }
  if (url === "submit") return SUBMIT_RESPONSE;
  return { ok: true, status: 200, json: async () => POLL_RESPONSE };
};

// UNE VISITE PRÉCÉDENTE, déposée avant que la page ne démarre : un brouillon
// bien formé, et deux entrées empoisonnées. Ce qui sort du stockage n'est pas
// de la donnée de confiance, et seule la première doit atteindre l'éditeur.
stockage["ctester.brouillons"] = JSON.stringify({
  "tp2-ex3": { "submission.c": "// travail d'hier" },
  "tp2-ex0": { "submission.c": { pas: "une chaîne" } },
  "tp6-ex1": "pas un objet de fichiers",
});

new Function(js)();

const sleep = () => new Promise((r) => setImmediate(r));
let failures = 0;
function check(cond, label) {
  console.log((cond ? "ok   " : "ÉCHEC ") + label);
  if (!cond) failures++;
}
const shown = () => nodes.out.children.map(c => c.textContent).join(" ");
const contexte = () => nodes.now.children.map(c => c.textContent).join(" | ");

function choisir(groupe, id) {
  nodes.tp.value = groupe;
  nodes.tp.listeners.change();
  if (id) { nodes.ex.value = id; nodes.ex.listeners.change(); }
}

(async () => {
  await sleep(); await sleep();
  check(calls.some(c => c.url === "tps.json"), "le catalogue est demandé au chargement");

  // --- Le sélecteur à deux niveaux ---
  check(nodes.tp.children.map(o => o.value).join(",") === "TP 1,TP 2,TP 6",
        "le premier menu liste les TP, sans doublon");
  choisir("TP 2");
  check(nodes.ex.children.map(o => o.value).join(",") === "tp2-ex0,tp2-ex3",
        "le second menu ne montre que les exercices du TP choisi");
  check(nodes.ex.children[0].textContent === "ex.0 âge",
        "le second menu n'y répète pas le préfixe « TP2 : »");
  check(nodes.exwrap.hidden === false, "le second menu est visible quand il sert");
  check(/ex\.0/.test(contexte()), "la barre de contexte nomme l'exercice courant");
  check(/main\(\)/.test(contexte()), "et rappelle ce qu'on attend comme soumission");

  // --- Ce qu'une visite précédente a laissé dans le stockage ---
  choisir("TP 2", "tp2-ex3");
  check(nodes.code.value === "// travail d'hier",
        "le brouillon d'hier est retrouvé à l'ouverture de la page");
  check(nodes.purger.hidden === false,
        "et « effacer mes brouillons » apparaît puisqu'il y a quelque chose à effacer");
  choisir("TP 6", "tp6-ex1");
  check(nodes.code.value === "#define VRAI 1\n",
        "une entrée mal formée du stockage est ignorée : c'est le gabarit qui sert");

  choisir("TP 1");
  check(nodes.exwrap.hidden === true,
        "un TP sans exercices masque le second menu au lieu d'en offrir un seul");
  check(/réponses à saisir/.test(contexte()), "la pastille suit le mode du TP");

  // --- Le cas qui était cassé : une soumission de code ---
  choisir("TP 2", "tp2-ex3");
  nodes.code.value = "int main(void){return 0;}";
  SUBMIT_RESPONSE = { ok: true, status: 200, json: async () => ({ id: "a".repeat(32) }) };
  calls.length = 0;
  await nodes.go.listeners.click();
  await sleep(); await sleep();

  const post = calls.find(c => c.url === "submit");
  check(!!post, "le fetch de soumission part réellement");
  if (post) {
    const sent = JSON.parse(post.opts.body);
    check(sent.files["submission.c"] === "int main(void){return 0;}",
          "le code est bien dans la charge utile, sous son nom de fichier");
    check(sent.tp === "tp2-ex3" && sent.key === "cle-de-test",
          "l'exercice envoyé est celui du SECOND menu, pas le TP");
    check(!("answers" in sent), "pas de réponses de quiz sur un TP de code");
  }
  check(nodes.tabs.hidden === true,
        "un exercice à un seul fichier n'affiche pas de barre d'onglets");
  check(!/injoignable|ne répond pas/.test(shown()),
        "aucune erreur affichée sur le chemin heureux");

  // --- Une réponse non JSON (page de blocage Cloudflare, erreur nginx) ---
  SUBMIT_RESPONSE = { ok: false, status: 403,
                      json: async () => { throw new SyntaxError("Unexpected token <"); } };
  calls.length = 0;
  await nodes.go.listeners.click();
  await sleep(); await sleep();
  check(/403/.test(shown()), "un blocage HTML affiche son vrai statut");

  // --- Coloration syntaxique ---
  const colorer = (src) => {
    nodes.code.value = src;
    nodes.code.listeners.input();
    return nodes.hlcode.innerHTML;
  };

  const c = colorer('#include <stdio.h>\nint main(void) {\n  // salut & fin\n' +
                    '  printf("a > b & c");\n  return EXIT_SUCCESS;\n}\n');
  check(/class="tk">int</.test(c), "les mots-clés sont colorés");
  check(/class="tp">#include</.test(c), "les directives préprocesseur aussi");
  check(/class="tf">printf</.test(c), "les appels de fonction aussi");
  check(/class="tc">\/\/ salut &amp; fin</.test(c), "les commentaires aussi, échappés");
  check(/class="tu">EXIT_SUCCESS</.test(c), "les constantes en majuscules aussi");
  check(c.includes("&lt;stdio.h&gt;"), "les chevrons de #include sont échappés");

  // LE POINT QUI COMPTE : la sortie va dans innerHTML. Du code étudiant non
  // échappé s'exécuterait dans sa propre page.
  const x = colorer('printf("<script>alert(1)</script>");\n/* <img onerror=x> */');
  check(!/<script/i.test(x) && !/<img/i.test(x), "aucune balise brute ne survit");
  check(x.includes("&lt;script&gt;"), "le HTML de l'étudiant est échappé");

  const p = colorer('char *u = "http://x"; // l\'heure\nint apres;');
  check(/class="ts">"http:\/\/x"/.test(p), "le // d'une chaîne reste une chaîne");
  check(/class="tk">int</.test(p), "le code après un commentaire reste coloré");

  const brut = 'int x = 3;\n\tfloat y;\n';
  const rendu = colorer(brut).replace(/<[^>]*>/g, "")
                  .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
  check(rendu === brut + "\n", "le texte coloré est identique à la source");

  // --- Multi-fichiers : un module .h + .c ---
  choisir("TP 6", "tp6-ex1");
  check(nodes.tabs.hidden === false, "un module affiche sa barre d'onglets");
  check(nodes.tabs.children.map(o => o.textContent).join(",")
        === "calendrier.h,calendrier.c", "un onglet par fichier imposé par l'énoncé");
  check(nodes.code.value === "#define VRAI 1\n",
        "le premier onglet s'ouvre pré-rempli avec son gabarit");
  check(nodes.tabs.children[0].getAttribute("aria-selected") === "true" &&
        nodes.tabs.children[1].getAttribute("aria-selected") === "false",
        "l'onglet courant est annoncé aux lecteurs d'écran");

  // LE BUG QUI NE SE PARDONNE PAS : perdre le travail en changeant d'onglet.
  nodes.code.value = "#define VRAI 1\nint est_bissextile(int annee);\n";
  nodes.tabs.children[1].listeners.click();
  check(nodes.code.value === '#include "calendrier.h"\n',
        "changer d'onglet charge l'autre fichier");
  nodes.code.value = '#include "calendrier.h"\nint est_bissextile(int a){return 1;}';
  nodes.tabs.children[0].listeners.click();
  check(nodes.code.value === "#define VRAI 1\nint est_bissextile(int annee);\n",
        "et le premier fichier a bien été conservé");

  // Les flèches déplacent la sélection, comme l'attend un tablist ARIA.
  nodes.tabs.listeners.keydown({ key: "ArrowRight" });
  check(nodes.code.value.startsWith('#include "calendrier.h"'),
        "flèche droite passe à l'onglet suivant");

  SUBMIT_RESPONSE = { ok: true, status: 200, json: async () => ({ id: "c".repeat(32) }) };
  calls.length = 0;
  await nodes.go.listeners.click();
  await sleep(); await sleep();
  const modulePost = calls.find(c => c.url === "submit");
  check(!!modulePost, "le module part en une seule soumission");
  if (modulePost) {
    const sent = JSON.parse(modulePost.opts.body);
    check(Object.keys(sent.files).join(",") === "calendrier.h,calendrier.c",
          "les deux fichiers sont envoyés, sous leurs noms imposés");
    check(sent.files["calendrier.c"].includes("est_bissextile(int a)"),
          "y compris l'onglet ouvert au moment du clic");
  }

  // --- Navigation entre exercices, et les brouillons ---
  choisir("TP 2", "tp2-ex0");
  nodes.code.value = "// mon travail sur l'ex 0";
  nodes.next.listeners.click();
  check(nodes.ex.value === "tp2-ex3", "« suivant » avance d'un exercice");
  nodes.next.listeners.click();
  check(nodes.tp.value === "TP 6" && nodes.ex.value === "tp6-ex1",
        "« suivant » franchit la fin d'un TP");
  check(nodes.next.disabled === true, "le bouton se désactive au dernier exercice");
  nodes.prev.listeners.click();
  nodes.prev.listeners.click();
  check(nodes.ex.value === "tp2-ex0", "« précédent » revient sur ses pas");
  // LE PIÈGE QUE LES BROUILLONS FERMENT : sans eux, ce clic aurait effacé le
  // travail de l'étudiant, et le bouton « suivant » l'aurait rendu banal.
  check(nodes.code.value === "// mon travail sur l'ex 0",
        "le travail en cours survit à un aller-retour entre exercices");

  // --- L'enregistrement automatique, et ce qu'il promet ---
  nodes.purger.listeners.click();          // on repart d'un stockage vide
  check(!("ctester.brouillons" in stockage), "« effacer mes brouillons » vide le stockage");
  check(nodes.purger.hidden === true, "et le bouton se retire une fois qu'il n'y a plus rien");

  nodes.code.value = "int main(void){ return 0; }";
  nodes.code.listeners.input();
  check(!("ctester.brouillons" in stockage),
        "une frappe n'écrit pas tout de suite : l'enregistrement est différé");

  declencherDernierMinuteur();
  const garde = JSON.parse(stockage["ctester.brouillons"] || "{}");
  check(garde["tp2-ex0"] && garde["tp2-ex0"]["submission.c"] === "int main(void){ return 0; }",
        "passé le délai de silence, le brouillon est écrit");
  check(/^brouillon enregistré à \d\d:\d\d$/.test(nodes.brouillon.textContent),
        "et l'indicateur donne l'heure : " + nodes.brouillon.textContent);
  check(nodes.brouillon.className === "", "discret tant que tout va bien");

  // LE CAS QUI COMPTE VRAIMENT. Afficher « enregistré » ici ferait perdre son
  // travail à quelqu'un qui nous a crus.
  stockageEnPanne = true;
  nodes.code.value = "int main(void){ return 1; }";
  nodes.code.listeners.input();
  declencherDernierMinuteur();
  check(/NON enregistré/.test(nodes.brouillon.textContent),
        "un stockage qui refuse d'écrire se dit : " + nodes.brouillon.textContent);
  check(nodes.brouillon.className === "rate", "et se voit, en rouge");
  check(JSON.parse(stockage["ctester.brouillons"])["tp2-ex0"]["submission.c"]
        === "int main(void){ return 0; }",
        "le stockage garde alors la dernière version réellement écrite");
  stockageEnPanne = false;

  // --- Mode quiz : pagination puis soumission complète ---
  choisir("TP 1");
  await sleep(); await sleep();
  check(nodes.quiznav.hidden === false, "un quiz à plusieurs exercices est paginé");
  check(/page 1 sur 2/.test(nodes.qpos.textContent),
        "la position est annoncée : " + nodes.qpos.textContent);
  check(nodes.qprev.disabled === true, "pas de « précédent » sur la première page");
  const pages = nodes.quiz.children;
  check(pages.length === 2 && pages[0].hidden === false && pages[1].hidden === true,
        "seule la page courante est visible");

  // On répond sur la page 1, on passe à la page 2, on répond aussi.
  const champs = nodes.quiz.querySelectorAll();
  check(champs.length === 3, "les champs de toutes les pages restent dans le document");
  champs[0].value = "00010111";
  nodes.qnext.listeners.click();
  check(pages[1].hidden === false && nodes.qnext.disabled === true,
        "« suivant » affiche la page 2 et se désactive au bout");
  champs[2].value = "0x17";

  SUBMIT_RESPONSE = { ok: true, status: 200, json: async () => ({ id: "b".repeat(32) }) };
  calls.length = 0;
  await nodes.go.listeners.click();
  await sleep(); await sleep();
  const quizPost = calls.find(c => c.url === "submit");
  check(!!quizPost, "le fetch part aussi en mode quiz");
  if (quizPost) {
    const sent = JSON.parse(quizPost.opts.body);
    check(sent.tp === "tp1", "le quiz est soumis sous l'identifiant du TP");
    // LE POINT DE LA PAGINATION : masquer une page ne doit pas perdre ses
    // réponses. La soumission ramasse les trois champs, pas la page visible.
    check(sent.answers.q1 === "00010111" && sent.answers.q3 === "0x17",
          "les réponses des DEUX pages sont transmises");
    check(!("code" in sent), "pas de code sur un TP de quiz");
  }

  // --- Le verdict rend a l'etudiant ce qui lui appartient ---
  // On passe par le VRAI chemin -- soumission puis sondage -- parce que render()
  // vit dans la portee du script de la page et n'est pas joignable autrement.
  function afficheTout(n) {
    return (n.textContent || "") + " " +
           (n.children || []).map(afficheTout).join(" ");
  }
  async function verdictAffiche(v) {
    POLL_RESPONSE = Object.assign({ state: "done" }, v);
    SUBMIT_RESPONSE = { ok: true, status: 200,
                        json: async () => ({ id: "d".repeat(32) }) };
    choisir("TP 2", "tp2-ex0");
    nodes.code.value = "int main(void){return 0;}";
    await nodes.go.listeners.click();
    await sleep(); await sleep(); await sleep();
    return nodes.out.children.map(afficheTout).join(" | ");
  }

  // LE POINT LE PLUS IMPORTANT : les avertissements s'affichent AUSSI sur une
  // reussite. C'est la qu'ils servent, et il ne faut pas les faire passer pour
  // un echec.
  const gagne = await verdictAffiche({ status: "ok", kind: "io", passed: 3, total: 3,
                        cases: [], warnings: "sub.c:4: warning: unused variable" });
  check(/3 \/ 3/.test(gagne), "une reussite reste une reussite");
  check(/unused variable/.test(gagne),
        "les avertissements s'affichent meme quand tout passe");
  check(/pas une erreur/.test(gagne),
        "et sont explicitement presentes comme n'etant pas un echec");

  const rate = await verdictAffiche({ status: "ok", kind: "io", passed: 0, total: 1, cases: [
    { case: 1, stdin: "5\n", stdout: "resultat 1 234", reason: "valeurs absentes",
      nombres: [1, 234], stderr: "mise au point : i vaut 3" } ] });
  check(/nombres lus dans ta sortie : 1, 234/.test(rate),
        "les nombres que le juge a lus sont montres");
  check(/mise au point/.test(rate), "la sortie d'erreur du programme aussi");

  const quiz = await verdictAffiche({ status: "ok", kind: "quiz", passed: 0, total: 1,
                       wrong: [{ id: "q1", label: "23", given: "10111",
                                 hint: "l'enonce demande 8 bits" }] });
  check(/tu as répondu « 10111 »/.test(quiz), "le quiz rappelle la reponse saisie");

  // --- Tab indente, mais Echap+Tab laisse sortir ---
  choisir("TP 2", "tp2-ex0");
  nodes.code.value = "int main";
  nodes.code.selectionStart = nodes.code.selectionEnd = 8;
  let bloque = false;
  nodes.code.listeners.keydown({ key: "Tab", preventDefault: () => { bloque = true; } });
  check(bloque && nodes.code.value === "int main    ",
        "Tab indente au lieu de quitter le champ");

  bloque = false;
  nodes.code.listeners.keydown({ key: "Escape", preventDefault: () => {} });
  nodes.code.listeners.keydown({ key: "Tab", preventDefault: () => { bloque = true; } });
  check(!bloque, "Echap puis Tab laisse sortir : on n'enferme pas le clavier");

  console.log(failures ? `\n${failures} ÉCHEC(S)` : "\nla page fonctionne");
  process.exit(failures ? 1 : 0);
})();
