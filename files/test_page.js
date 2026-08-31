// Exécute VRAIMENT le JS de index.html, avec un DOM minimal en trompe-l'oeil.
// C'est le contrôle que `node --check` ne pouvait pas faire : une erreur de zone
// morte temporelle est une erreur d'exécution, pas de syntaxe.
const fs = require("fs");
const path = require("path");

const html = fs.readFileSync(process.argv[2], "utf8");
const js = html.match(/<script>([\s\S]*)<\/script>/)[1];

// --- DOM en carton -------------------------------------------------------
function el(id) {
  return {
    id, value: "", hidden: false, className: "", innerHTML: "", textContent: "",
    disabled: false, dataset: {}, files: [], children: [], listeners: {},
    addEventListener(ev, fn) { this.listeners[ev] = fn; },
    append(...kids) { this.children.push(...kids); },
    querySelectorAll() { return []; },
  };
}
const nodes = {};
global.document = {
  getElementById: (id) => (nodes[id] ||= el(id)),
  createElement: (tag) => el("<" + tag + ">"),
};
global.location = { search: "?k=cle-de-test" };
global.URLSearchParams = URLSearchParams;
global.setTimeout = () => {};

const calls = [];
global.fetch = async (url, opts) => {
  calls.push({ url, opts });
  if (url === "tps.json") {
    return { ok: true, status: 200, json: async () => ([
      { id: "tp1", mode: "quiz", label: "TP1 : encodage" },
      { id: "tp2-ex0", mode: "io", label: "TP2 : ex.0" },
    ]) };
  }
  if (url.startsWith("quiz/")) {
    return { ok: true, status: 200, json: async () => ({
      label: "TP1", questions: [
        { id: "q1", group: "G1", label: "23", type: "bin8" },
      ] }) };
  }
  if (url === "submit") return SUBMIT_RESPONSE;
  return { ok: true, status: 200, json: async () => ({ state: "queued", position: 1 }) };
};
let SUBMIT_RESPONSE;

// --- Chargement ----------------------------------------------------------
new Function(js)();

const sleep = () => new Promise((r) => setImmediate(r));
let failures = 0;
function check(cond, label) {
  console.log((cond ? "ok   " : "ÉCHEC ") + label);
  if (!cond) failures++;
}

(async () => {
  await sleep(); await sleep();           // laisse le fetch de tps.json se résoudre
  check(calls.some(c => c.url === "tps.json"), "le catalogue est demandé au chargement");

  // --- Le cas qui était cassé : une soumission de code ---
  nodes.tp.value = "tp2-ex0";
  nodes.code.value = "int main(void){return 0;}";
  SUBMIT_RESPONSE = { ok: true, status: 200, json: async () => ({ id: "a".repeat(32) }) };
  calls.length = 0;
  await nodes.go.listeners.click();
  await sleep(); await sleep();

  const post = calls.find(c => c.url === "submit");
  check(!!post, "le fetch de soumission part réellement");
  if (post) {
    const sent = JSON.parse(post.opts.body);
    check(sent.code === "int main(void){return 0;}", "le code est bien dans la charge utile");
    check(sent.tp === "tp2-ex0" && sent.key === "cle-de-test", "TP et clé transmis");
    check(!("answers" in sent), "pas de réponses de quiz sur un TP de code");
  }
  check(!/injoignable|ne répond pas/.test(nodes.out.children.map(c => c.textContent).join(" ")),
        "aucune erreur affichée sur le chemin heureux");

  // --- Une réponse non JSON (page de blocage Cloudflare, erreur nginx) ---
  SUBMIT_RESPONSE = { ok: false, status: 403,
                      json: async () => { throw new SyntaxError("Unexpected token <"); } };
  calls.length = 0;
  await nodes.go.listeners.click();
  await sleep(); await sleep();
  const shown = nodes.out.children.map(c => c.textContent).join(" ");
  check(/403/.test(shown), "un blocage HTML affiche son vrai statut : " + JSON.stringify(shown));

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

  // Priorité des branches : un // dans une chaîne n'ouvre pas un commentaire,
  // une apostrophe dans un commentaire n'ouvre pas une chaîne.
  const p = colorer('char *u = "http://x"; // l\'heure\nint apres;');
  check(/class="ts">"http:\/\/x"/.test(p), "le // d'une chaîne reste une chaîne");
  check(/class="tk">int</.test(p), "le code après un commentaire reste coloré");

  // Le texte doit survivre intact : on colore, on ne réécrit pas.
  const brut = 'int x = 3;\n\tfloat y;\n';
  const html = colorer(brut);
  const rendu = html.replace(/<[^>]*>/g, "")
                    .replace(/&lt;/g, "<").replace(/&gt;/g, ">")
                    .replace(/&amp;/g, "&");
  check(rendu === brut + "\n", "le texte coloré est identique à la source");

  // --- Mode quiz : des réponses, pas du code ---
  nodes.tp.value = "tp1";
  nodes.quiz.querySelectorAll = () => [{ dataset: { qid: "q1" }, value: "00010111" }];
  SUBMIT_RESPONSE = { ok: true, status: 200, json: async () => ({ id: "b".repeat(32) }) };
  calls.length = 0;
  await nodes.go.listeners.click();
  await sleep(); await sleep();
  const quizPost = calls.find(c => c.url === "submit");
  check(!!quizPost, "le fetch part aussi en mode quiz");
  if (quizPost) {
    const sent = JSON.parse(quizPost.opts.body);
    check(sent.answers && sent.answers.q1 === "00010111", "les réponses sont transmises");
    check(!("code" in sent), "pas de code sur un TP de quiz");
  }

  console.log(failures ? `\n${failures} ÉCHEC(S)` : "\nla page fonctionne");
  process.exit(failures ? 1 : 0);
})();
