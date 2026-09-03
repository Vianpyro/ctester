// Exécute VRAIMENT le JS de index.html, avec un DOM minimal en trompe-l'oeil.
// C'est le contrôle que `node --check` ne peut pas faire : la seule panne que
// cette page ait connue en production était une ReferenceError de zone morte
// temporelle -- une erreur d'exécution, pas de syntaxe.
//
//   node test_page.js [app/]
//
// La page est en TROIS fichiers depuis qu'elle a ete decoupee, et chacun porte
// un contrat different : `html` les identifiants et l'ordre du document, `css`
// les regles `display:`, `js` le code qu'on execute vraiment.
const fs = require("fs");

const APP = process.argv[2] || __dirname + "/app";
const lire = (nom) => fs.readFileSync(APP + "/" + nom, "utf8");
const html = lire("index.html");
const css = lire("style.css");
const js = lire("app.js");

// --- DOM en carton --------------------------------------------------------
// CE QUE LE MARKUP MASQUE DEJA. `<div id="liste" hidden>` part masque dans un
// vrai navigateur ; un faux DOM qui le rend visible fait basculer a l'envers
// tout ce qui lit `.hidden` pour decider, et la vue liste ne s'ouvrait jamais.
const masquesAuDepart = new Set(
  [...html.matchAll(/<[^>]+>/g)]
    .filter((m) => /\shidden(\s|>|=)/.test(m[0]))
    .map((m) => (m[0].match(/\bid="([^"]+)"/) || [])[1])
    .filter(Boolean));

function el(id) {
  const node = {
    id, value: "", hidden: masquesAuDepart.has(id), className: "", textContent: "",
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
  // Un <script src> injecte : le navigateur va chercher le fichier et
  // declenche onload/onerror. Ici on l'evalue tout de suite, dans le meme
  // contexte global, puis on previent -- sans quoi la moitie de la page
  // (le quiz, le compte) ne serait jamais executee par ce harnais.
  let source = "";
  Object.defineProperty(node, "src", {
    get: () => source,
    set(v) {
      source = v;
      charges.push(v);
      let echec = chargementCasse;
      if (!echec) {
        try {
          new Function(lire(v))();
        } catch (e) {
          // UN MODULE QUI LEVE DOIT SE VOIR. Sans cette ligne il partirait
          // dans le chemin onerror, indistinguable d'une panne reseau
          // simulee, et le harnais dirait « la page fonctionne ».
          console.log("MODULE " + v + " a leve : " + e.message);
          echec = e;
        }
      }
      setImmediate(() => {
        if (echec && node.onerror) node.onerror(echec);
        else if (!echec && node.onload) node.onload();
      });
    },
  });
  let ident = id;
  Object.defineProperty(node, "id", {
    get: () => ident,
    // Un élément créé dynamiquement puis nommé doit devenir trouvable par
    // getElementById, comme dans un vrai document : la pagination du quiz crée
    // ses boutons puis les récupère par identifiant.
    set(v) { ident = v; nodes[v] = node; declares.add(v); },
  });
  return node;
}
const nodes = {};
// L'interrupteur du mode de panne neuf : un module qui n'arrive pas.
let chargementCasse = false;
// Ce que la page est allee chercher : sert a prouver ce qu'elle N'A PAS
// telecharge, ce qui est tout l'interet du chargement a la demande.
const charges = [];

// LES IDENTIFIANTS QUE LA PAGE DECLARE VRAIMENT. Sans cette liste, le faux DOM
// fabriquait a la demande n'importe quel noeud demande -- et un $("truc") qui
// n'existe pas dans le HTML passait ici en silence pour rendre null, donc lever,
// dans un vrai navigateur. C'est exactement la panne que ce fichier existe pour
// attraper : une erreur d'execution que `node --check` ne voit pas.
//
// Un element cree dynamiquement PUIS nomme reste legitime (la pagination du
// quiz le fait) : le setter d'id ci-dessus l'ajoute a l'ensemble.
const declares = new Set(
  [...html.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]));

global.document = {
  getElementById: (id) => {
    if (!declares.has(id)) {
      throw new Error("getElementById(\"" + id + "\") : aucun element de ce nom "
                    + "dans index.html -- un vrai navigateur rendrait null ici");
    }
    return (nodes[id] ||= el(id));
  },
  createElement: (tag) => el("<" + tag + ">"),
  // Les modules charges a la demande s'y accrochent.
  body: el("<body>"),
  // La page pose le thème sur la racine du document. Un objet suffit : le
  // harnais n'a pas à savoir ce qu'est un thème, seulement que l'écrire ne
  // lève pas.
  documentElement: { dataset: {} },
  createTextNode: (t) => ({ textContent: t, children: [] }),
};
global.window = global;
global.location = { search: "?k=cle-de-test" };
global.URLSearchParams = URLSearchParams;

// Les minuteurs sont CAPTURÉS, pas exécutés. La page en pose deux sortes : le
// sondage du verdict, qu'on ne veut surtout pas voir boucler dans un test, et
// le délai d'enregistrement du brouillon, qu'on veut déclencher à la main
// plutôt que d'attendre 1,5 seconde réelle.
const timers = [];
global.setTimeout = (fn) => timers.push(fn);
global.clearTimeout = () => {};
const fireLastTimer = () => timers[timers.length - 1]();

// Stockage en carton, avec un interrupteur de panne : navigation privée, quota
// plein, stockage désactivé par une politique d'école. C'est le cas qui ne doit
// JAMAIS afficher « enregistré ».
let storageBroken = false;
const storage = {};
global.localStorage = {
  getItem: (k) => (k in storage ? storage[k] : null),
  setItem: (k, v) => {
    if (storageBroken) throw new Error("QuotaExceededError");
    storage[k] = v;
  },
  removeItem: (k) => { delete storage[k]; },
};

// Le jeton de session vit ici, et il n'y en a pas : ce fichier éprouve le
// parcours ANONYME sur un déploiement où la connexion est pourtant offerte.
// C'est la combinaison qui doit rester identique à l'avant-connexion.
const session = {};
global.sessionStorage = {
  getItem: (k) => (k in session ? session[k] : null),
  setItem: (k, v) => { session[k] = v; },
  removeItem: (k) => { delete session[k]; },
};
// Ou la page envoie l'etudiant quand il accepte de se connecter.
const redirections = [];
global.history = { replaceState: () => {} };
global.location.assign = (url) => { redirections.push(url); };
global.location.origin = "https://ctester.example";
global.location.pathname = "/";

const UN_FICHIER = [{ name: "submission.c" }];
// LE DETAIL, SERVI A PART. `tps.json` ne porte plus que le menu et la
// liste blanche des noms de fichiers ; consigne et gabarits vivent ici.
const DETAILS = {
  "tp2-ex0": { statement: "", files: UN_FICHIER },
  "tp2-ex3": { statement: "Calcule U = R * I.", files: UN_FICHIER },
  "tp6-ex1": { statement: "", files: [{ name: "calendrier.h", template: "#define VRAI 1\n" }, { name: "calendrier.c", template: "#include \"calendrier.h\"\n" }] },
};
const CATALOGUE = [
  { id: "tp1", mode: "quiz", label: "TP1 : encodage binaire",
    group: "TP 1", short: "encodage binaire", files: [] },
  { id: "tp2-ex0", mode: "io", label: "TP2 : ex.0 âge",
    group: "TP 2", short: "ex.0 âge", files: UN_FICHIER },
  { id: "tp2-ex3", mode: "io", label: "TP2 : ex.3 loi d'Ohm",
    group: "TP 2", short: "ex.3 loi d'Ohm", files: UN_FICHIER,
    learning: { skills: ["variables", "arithmetic-operators"],
                context: "electrical", difficulty: "foundation" } },
  { id: "tp6-ex1", mode: "unity", label: "TP6 : ex.1 est_bissextile",
    group: "TP 6", short: "ex.1 est_bissextile",
    files: [{ name: "calendrier.h" }, { name: "calendrier.c" }] },
];

const calls = [];
// Un déploiement où la connexion EST configurée. Tout ce qui suit doit malgré
// tout se comporter comme avant tant que personne ne s'est connecté.
const OIDC_RESPONSE = { issuer: "https://auth.example", client_id: "ctester" };
let SUBMIT_RESPONSE;
let DECOUVERTE_CASSEE = false;
const JETON = "jeton-de-test";
const ETATS = { etats: [{ exercice_id: "tp2-ex0", statut: "valide" }] };
const PRATIQUE = { pratique: [
  { exercice_id: "tp2-ex3", tentatives: 3, reussites: 1 }] };
let POLL_RESPONSE = { state: "queued", position: 1 };
global.fetch = async (url, opts) => {
  calls.push({ url, opts });
  if (url === "tps.json") {
    return { ok: true, status: 200, json: async () => CATALOGUE };
  }
  if (url.startsWith("tp/")) {
    const detail = DETAILS[url.slice(3, -5)];
    return detail
      ? { ok: true, status: 200, json: async () => detail }
      : { ok: false, status: 404, json: async () => ({ error: "inconnu" }) };
  }
  if (url.startsWith("quiz/")) {
    return { ok: true, status: 200, json: async () => ({
      label: "TP1", questions: [
        { id: "q1", group: "Exercice 1 : binaire", label: "23", type: "bin8" },
        { id: "q2", group: "Exercice 1 : binaire", label: "167", type: "bin8" },
        { id: "q3", group: "Exercice 2 : hexadécimal", label: "23", type: "hex8" },
      ] }) };
  }
  if (url.includes("openid-configuration")) {
    if (DECOUVERTE_CASSEE) throw new Error("fournisseur injoignable");
    return { ok: true, status: 200, json: async () => ({
      authorization_endpoint: "https://auth.example/authorize",
      token_endpoint: "https://auth.example/token" }) };
  }
  if (url === "oidc.json") {
    return { ok: true, status: 200, json: async () => OIDC_RESPONSE };
  }
  if (url === "etats" || url === "pratique") {
    // LE JETON FAIT FOI. Une requete de compte sans en-tete doit repartir
    // vide : c'est ce qui distingue « pas connecte » de « rien a montrer ».
    const porteur = opts && opts.headers && opts.headers.Authorization;
    if (porteur !== "Bearer " + JETON) {
      return { ok: false, status: 401, json: async () => ({}) };
    }
    return { ok: true, status: 200, json: async () => (
      url === "etats" ? ETATS : PRATIQUE) };
  }
  if (url.startsWith("brouillon")) {
    return { ok: true, status: 200, json: async () => ({ sources: {} }) };
  }
  if (url === "submit") return SUBMIT_RESPONSE;
  return { ok: true, status: 200, json: async () => POLL_RESPONSE };
};

// UNE VISITE PRÉCÉDENTE, déposée avant que la page ne démarre : un brouillon
// bien formé, et deux entrées empoisonnées. Ce qui sort du stockage n'est pas
// de la donnée de confiance, et seule la première doit atteindre l'éditeur.
storage["ctester.drafts"] = JSON.stringify({
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

// CHANGER D'EXERCICE EST ASYNCHRONE depuis que le detail (consigne, gabarits)
// est charge a la demande : switchMode part chercher tp/<id>.json. Tout ce qui
// regarde l'editeur ou la consigne doit donc laisser passer les microtaches.
async function choisir(groupe, id) {
  nodes.tp.value = groupe;
  nodes.tp.listeners.change();
  if (id) { nodes.ex.value = id; nodes.ex.listeners.change(); }
  await attendre();
}
const attendre = async () => { await sleep(); await sleep(); };

(async () => {
  await sleep(); await sleep();
  check(calls.some(c => c.url === "tps.json"), "le catalogue est demandé au chargement");

  // --- LE DETAIL, CHARGE A LA DEMANDE ---
  // `tps.json` ne porte plus ni consigne ni gabarits : trois quarts de son
  // poids pour 72 exercices dont un seul est ouvert.
  check(calls.some(c => c.url === "tp/tp1.json"),
        "ouvrir un exercice demande son detail, a part");

  // --- CE QUI N'EST PAS TELECHARGE ---
  // Le deploiement OFFRE la connexion (oidc.json repond), et pourtant rien du
  // compte n'est descendu : personne ne s'est connecte. C'est la promesse de
  // tout ce decoupage, et le parcours anonyme est le parcours par defaut.
  check(!global.ctester.compte, "sans session, compte.js n'est pas charge");
  check(charges.indexOf("compte.js") < 0,
        "et il n'est meme pas demande au serveur");
  check(charges.indexOf("quiz.js") >= 0,
        "quiz.js, lui, arrive avec le premier exercice de ce mode");
  // ET UN DETAIL QUI N'ARRIVE PAS NE BLOQUE RIEN : publication en retard,
  // reseau coupe. Les NOMS de fichiers viennent du catalogue, donc on peut
  // encore coller son code et soumettre -- c'est tout ce qu'on promet ici.
  // `tp1` est l'exercice que la page ouvre seule, et DETAILS ne le porte pas
  // encore : c'est exactement ce cas qui vient de se jouer.
  check(/pas de consigne en ligne/.test(nodes.consignetexte.textContent),
        "un detail introuvable retombe sur le message de repli");
  DETAILS["tp1"] = { statement: "Convertis 23 en binaire.", files: [] };

  // ON SOUMET DANS LES DEUX MODES. L'éditeur et le quiz se relaient dans la
  // même rangée, et chacun se masque à son tour : un bouton « Tester » placé
  // DANS l'un des deux disparaît avec lui. Il doit donc venir après les deux.
  // Vérification sur le HTML et pas sur le DOM en carton, qui ne connaît pas
  // l'imbrication du document.
  // UNE REGLE `display:` L'EMPORTE SUR LE [hidden] NATIF, et ce piege a deja
  // mordu trois fois dans ce fichier (#travail, #tabs, #quiznav) : le script
  // pose bien l'attribut, le harnais le voit, et le navigateur affiche quand
  // meme. Rien dans un DOM en carton ne peut l'attraper -- il n'a pas de CSS --
  // donc on le lit dans style.css.
  {
    // LE SCAN PORTE SUR `js`, PAS SUR `html` : depuis le decoupage, aucun
    // `$("x").hidden` ne vit plus dans la page. Laisse sur `html`, ce controle
    // n'inspecterait plus aucun identifiant et passerait en silence.
    const masques = [...new Set([...js.matchAll(/\$\("(\w+)"\)\.hidden/g)]
                                .map((m) => m[1]))];
    // Pas de regex ici : la feuille ecrit invariablement `#id {`, et chercher
    // "display:" dans le bloc qui suit se lit mieux qu'une expression truffee
    // d'antislashs.
    const fautifs = masques.filter((id) => {
      const i = css.indexOf("#" + id + " {");
      if (i < 0) return false;
      const bloc = css.slice(i, css.indexOf("}", i));
      return bloc.includes("display:") && !css.includes("#" + id + "[hidden]");
    });
    check(fautifs.length === 0,
          "tout ce que le script masque et qui porte un display: a sa regle "
          + "[hidden]" + (fautifs.length ? " -- MANQUE : " + fautifs.join(", ") : ""));
  }

  check(html.indexOf('id="go"') > html.indexOf('id="quizwrap"') &&
        html.indexOf('id="go"') > html.indexOf('id="editor"'),
        "« Tester » vient après les deux volets, donc en masquer un ne l'emporte pas");

  // --- Le sélecteur à deux niveaux ---
  check(nodes.tp.children.map(o => o.value).join(",") === "TP 1,TP 2,TP 6",
        "le premier menu liste les TP, sans doublon");
  await choisir("TP 2");
  check(nodes.ex.children.map(o => o.value).join(",") === "tp2-ex0,tp2-ex3",
        "le second menu ne montre que les exercices du TP choisi");
  check(nodes.ex.children[0].textContent === "ex.0 âge",
        "le second menu n'y répète pas le préfixe « TP2 : »");
  check(nodes.exwrap.hidden === false, "le second menu est visible quand il sert");
  check(/ex\.0/.test(contexte()), "la barre de contexte nomme l'exercice courant");
  check(/main\(\)/.test(contexte()), "et rappelle ce qu'on attend comme soumission");

  calls.length = 0;
  await choisir("TP 1");
  check(nodes.consignetexte.textContent === "Convertis 23 en binaire.",
        "un repli n'est pas mis en cache : le detail revenu est repris");
  calls.length = 0;
  await choisir("TP 2");
  await choisir("TP 1");
  check(!calls.some(c => c.url === "tp/tp1.json"),
        "mais un detail obtenu n'est plus redemande : il est garde en memoire");

  // --- Ce qu'une visite précédente a laissé dans le stockage ---
  await choisir("TP 2", "tp2-ex3");
  check(nodes.consignetexte.textContent === "Calcule U = R * I.",
        "la consigne affichee vient du detail, plus du catalogue");
  check(nodes.now.children.some(c => c.textContent.includes(
          "objectif : variables, opérateurs") && c.textContent.includes("électrique")),
        "l'exercice affiche la compétence et son contexte, sans les confondre");
  check(nodes.code.value === "// travail d'hier",
        "le brouillon d'hier est retrouvé à l'ouverture de la page");
  check(nodes.purger.hidden === false,
        "et « effacer mes brouillons » apparaît puisqu'il y a quelque chose à effacer");
  await choisir("TP 6", "tp6-ex1");
  check(nodes.code.value === "#define VRAI 1\n",
        "une entrée mal formée du stockage est ignorée : c'est le gabarit qui sert");

  await choisir("TP 1");
  check(nodes.exwrap.hidden === true,
        "un TP sans exercices masque le second menu au lieu d'en offrir un seul");
  check(/réponses à saisir/.test(contexte()), "la pastille suit le mode du TP");
  // LES TROIS MODES, et surtout unity : promettre « avec son main() » sur un
  // module envoie l'étudiant dans une erreur d'édition de liens.
  await choisir("TP 6", "tp6-ex1");
  check(/sans main\(\)/.test(contexte()),
        "un module unity annonce qu'il n'attend PAS de main() : " + contexte());

  // --- Le cas qui était cassé : une soumission de code ---
  await choisir("TP 2", "tp2-ex3");
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
    check(!("Authorization" in post.opts.headers),
          "une soumission anonyme ne porte pas de jeton");
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
  await choisir("TP 6", "tp6-ex1");
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
  await choisir("TP 2", "tp2-ex0");
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
  // Le menu bouge tout de suite, l'editeur attend son detail.
  await attendre();
  // LE PIÈGE QUE LES BROUILLONS FERMENT : sans eux, ce clic aurait effacé le
  // travail de l'étudiant, et le bouton « suivant » l'aurait rendu banal.
  check(nodes.code.value === "// mon travail sur l'ex 0",
        "le travail en cours survit à un aller-retour entre exercices");

  // --- L'enregistrement automatique, et ce qu'il promet ---
  nodes.purger.listeners.click();          // on repart d’un stockage vide
  check(!("ctester.drafts" in storage), "« effacer mes brouillons » vide le stockage");
  check(nodes.purger.hidden === true, "et le bouton se retire une fois qu'il n'y a plus rien");

  nodes.code.value = "int main(void){ return 0; }";
  nodes.code.listeners.input();
  check(!("ctester.drafts" in storage),
        "une frappe n'écrit pas tout de suite : l'enregistrement est différé");

  fireLastTimer();
  const kept = JSON.parse(storage["ctester.drafts"] || "{}");
  check(kept["tp2-ex0"] && kept["tp2-ex0"]["submission.c"] === "int main(void){ return 0; }",
        "passé le délai de silence, le brouillon est écrit");
  check(/^brouillon enregistré à \d\d:\d\d$/.test(nodes.brouillon.textContent),
        "et l'indicateur donne l'heure : " + nodes.brouillon.textContent);
  check(nodes.brouillon.className === "", "discret tant que tout va bien");

  // LE CAS QUI COMPTE VRAIMENT. Afficher « enregistré » ici ferait perdre son
  // travail à quelqu'un qui nous a crus.
  storageBroken = true;
  nodes.code.value = "int main(void){ return 1; }";
  nodes.code.listeners.input();
  fireLastTimer();
  check(/NON enregistré/.test(nodes.brouillon.textContent),
        "un stockage qui refuse d'écrire se dit : " + nodes.brouillon.textContent);
  check(nodes.brouillon.className === "rate", "et se voit, en rouge");
  check(JSON.parse(storage["ctester.drafts"])["tp2-ex0"]["submission.c"]
        === "int main(void){ return 0; }",
        "le stockage garde alors la dernière version réellement écrite");
  storageBroken = false;

  // --- Mode quiz : pagination puis soumission complète ---
  await choisir("TP 1");
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
    await choisir("TP 2", "tp2-ex0");
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
  await choisir("TP 2", "tp2-ex0");
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

  // --- La connexion est offerte, mais personne ne s'est connecté ---
  // TOUT CE FICHIER tourne dans cet état : les 70 vérifications ci-dessus sont
  // donc, littéralement, la preuve de non-régression du parcours anonyme sur un
  // déploiement où la connexion existe.
  check(nodes.connexion.hidden === false, "« Se connecter » est proposé");
  check(nodes.mesexos.hidden === true && nodes.deconnexion.hidden === true &&
        nodes.oublier.hidden === true,
        "mais rien de ce qui suppose un compte n'apparaît");
  // Le harnais ne lit pas les attributs du HTML : ce qui prouve que la vue
  // liste est restée fermée, c'est qu'elle n'a jamais été construite.
  check(!nodes.liste || !nodes.liste.children.length,
        "et la vue liste n'est même pas construite");

  // LE POINT QUI COMPTE : pas un seul en-tête d'autorisation n'est parti, et
  // aucune écriture d'état non plus. Un anonyme ne parle jamais à la base.
  const entetes = calls.filter(c => c.opts && c.opts.headers &&
                                    c.opts.headers.Authorization);
  check(entetes.length === 0, "aucune requête ne porte de jeton");
  check(!calls.some(c => c.url === "etats" || c.url === "etat" ||
                         String(c.url).startsWith("brouillon")),
        "et rien n'est écrit ni lu côté compte");

  // Le consentement s'affiche AVANT la redirection, et se referme.
  nodes.connexion.listeners.click();
  check(nodes.consentement.hidden === false,
        "le premier clic montre ce qui sera conservé, il ne redirige pas");
  nodes.consentnon.listeners.click();
  check(nodes.consentement.hidden === true, "et « Annuler » referme sans rien faire");

  // --- LE MODE DE PANNE NEUF : un module qui n'arrive jamais ---
  // Reseau coupe en pleine seance, exactement le public que ce decoupage vise.
  // Ce qui ne doit PAS arriver : un clic qui ne fait rien et ne dit rien.
  chargementCasse = new Error("reseau coupe");
  nodes.connexion.listeners.click();
  await nodes.consentok.listeners.click();
  await attendre();
  check(/Impossible de charger/.test(shown()),
        "un module qui n'arrive pas le dit au lieu de se taire : " + shown());
  check(!global.ctester.compte, "et rien ne se declare a moitie");

  // ET ON PEUT RETENTER. Une coupure d'une seconde ne doit pas condamner la
  // connexion pour toute la visite : c'est pour ca que l'echec n'est pas garde
  // par le chargeur.
  nodes.connexion.listeners.click();
  await nodes.consentok.listeners.click();
  await attendre();
  check(charges.filter((n) => n === "compte.js").length === 2,
        "un second essai redemande vraiment le fichier");
  chargementCasse = false;

  // --- LE PARCOURS CONNECTE ---
  // Tout ce qui precede eprouve l'anonyme, qui reste le parcours par defaut.
  // Sans ce bloc, `ctester.token` a pu rester fige a null pendant toute une
  // visite sans qu'aucun test ne bronche : les etats et la pratique tombaient
  // en silence, et « Mes exercices » annoncait « a faire » sur un exercice
  // reussi. C'est arrive.
  // UN CLIC QUI NE FAIT RIEN ET NE DIT RIEN est la pire des issues : c'est
  // exactement ce qu'un `startSignIn()` lance sans `await` produisait quand il
  // levait, et ca a coute une session de deboguage cote utilisateur.
  DECOUVERTE_CASSEE = true;
  nodes.connexion.listeners.click();
  await nodes.consentok.listeners.click();
  await attendre();
  check(/connexion n'a pas pu démarrer/.test(shown()),
        "une connexion qui echoue le dit : " + shown());
  check(redirections.length === 0, "et n'envoie evidemment personne nulle part");
  DECOUVERTE_CASSEE = false;

  calls.length = 0;
  nodes.connexion.listeners.click();
  await nodes.consentok.listeners.click();
  await attendre(); await attendre();
  check(!!global.ctester.compte, "accepter le consentement charge compte.js");
  // Le defi PKCE passe par crypto.subtle : une vraie operation de la plateforme,
  // pas une microtache. Elle demande une poignee de tours de boucle, d'ou
  // l'attente bornee -- qui sort des qu'elle a rendu.
  for (let n = 0; n < 60 && !redirections.length; n++) await attendre();
  check(redirections.length === 1, "et part vraiment vers le fournisseur");
  check(!!session["ctester.pkce"], "en ayant garde son verificateur PKCE");
  const pkce = JSON.parse(session["ctester.pkce"] || "{}");
  check(redirections[0].includes("state=" + pkce.state),
        "le `state` envoye est celui qu'on a garde : sans lui, un lien portant "
        + "le code de quelqu'un d'autre finirait la connexion sous ce compte");
  check(redirections[0].includes("code_challenge_method=S256"),
        "et le defi PKCE part avec");
  check(redirections[0].startsWith("https://auth.example/authorize?"),
        "vers le point d'autorisation annonce par la decouverte : "
        + redirections[0].slice(0, 60));

  // LE CONTEXTE DOIT ETRE VIVANT. `Object.assign` copie la VALEUR d'un getter
  // et pas le getter : c'est exactement comme ca que le jeton s'est fige.
  global.ctester.setToken(JETON);
  check(global.ctester.token() === JETON,
        "le contexte rend le jeton COURANT, pas celui du chargement");
  check(!!global.ctester.oidc(), "et la configuration OIDC vraiment lue");

  calls.length = 0;
  await global.ctester.compte.loadStates();
  await global.ctester.compte.loadPractice();
  const portees = calls.filter(c => c.url === "etats" || c.url === "pratique");
  check(portees.length === 2 && portees.every(
          c => c.opts.headers.Authorization === "Bearer " + JETON),
        "les projections privees partent avec le jeton");

  global.ctester.compte.basculerListe();
  // Le texte d'une ligne est reparti sur plusieurs niveaux (la progression met
  // son compte dans un <b> puis un noeud texte), d'ou la descente.
  const texteDe = (n) => (n.children.length
    ? n.children.map(texteDe).join(" ") : n.textContent || "");
  const lignes = nodes.liste.children.map(texteDe);
  check(/1 \/ 4/.test(lignes[0] || ""),
        "la progression compte les exercices valides : " + lignes[0]);
  check(lignes.some(l => /3 tentatives — réussie/.test(l)),
        "et un exercice reussi le dit, au lieu de « a faire » : "
        + lignes.join(" // "));
  check(lignes.some(l => /à faire/.test(l)),
        "les autres restent a faire");

  // Se deconnecter remet tout a zero, jusqu'au bandeau.
  global.ctester.compte.signOut();
  check(global.ctester.token() === null, "se deconnecter oublie le jeton");
  check(nodes.mesexos.hidden === true && nodes.connexion.hidden === false,
        "et le bandeau repropose la connexion");

  console.log(failures ? `\n${failures} ÉCHEC(S)` : "\nla page fonctionne");
  process.exit(failures ? 1 : 0);
})();
