// Exécute VRAIMENT le JS de index.html, avec un DOM minimal en trompe-l'oeil.
// C'est le contrôle que `node --check` ne peut pas faire : la seule panne que
// cette page ait connue en production était une ReferenceError de zone morte
// temporelle -- une erreur d'exécution, pas de syntaxe.
//
//   node test_page.js [web/]
//
// Ce harnais lit trois fichiers, chacun sous un contrat different : `html` les
// identifiants et l'ordre du document, `css` les regles `display:`, `js` le
// code qu'on execute vraiment (les modules a la demande arrivent par `charger`).
// UN FUSEAU QUI N'EST PAS UTC, expres : l'affichage des dates du forum se
// traduit dans celui du lecteur, et sous UTC ce controle ne prouverait rien.
process.env.TZ = "America/Toronto";
const fs = require("fs");

const APP = process.argv[2] || __dirname + "/web";
const lire = (nom) => fs.readFileSync(APP + "/" + nom, "utf8");
const html = lire("index.html");
const css = lire("style.css");
const js = lire("app.js");

// UN VRAI DOM POUR L'ASSAINISSEUR, ET C'EST NON NEGOCIABLE. DOMPurify refuse
// de travailler sans DOM : `isSupported` passe a faux et `sanitize()` rend
// alors son entree TELLE QUELLE. Un harnais qui l'utiliserait dans cet etat
// ecrirait « aucune injection ne passe » sans avoir rien assaini -- le pire des
// controles de securite, celui qui rassure. D'ou jsdom (dependance de TEST
// seulement, voir package.json ; l'application, elle, n'a aucune dependance
// npm), et d'ou l'echec bruyant s'il manque.
let JSDOM = null;
try {
  ({ JSDOM } = require("jsdom"));
} catch (e) {
  console.error("jsdom manque : lance `npm ci` une fois, puis recommence.\n"
    + "Il donne un vrai DOM a DOMPurify ; sans lui les controles XSS de ce "
    + "fichier ne prouveraient rien du tout.");
  process.exit(1);
}

const appRevision = (html.match(/<script src="app\.js\?v=([^"]+)"/) || [])[1];
if (!appRevision || !js.includes('const ASSET_REVISION = "' + appRevision + '"')) {
  throw new Error("index.html et app.js doivent partager la révision des assets");
}

// TWO FUNCTIONS OF THE SAME NAME DO NOT WARN EACH OTHER: the last one wins,
// and the caller silently gets the other. That is the bug that already cost
// a debugging session (`activer` vs `activerModule`), and it recurred while
// splitting up "Mes progres" -- a leftover `exportRow` survived its
// replacement. Five lines here, and it can no longer pass unnoticed.
for (const file of ["app.js", "quiz.js", "compte.js", "progres.js",
                    "forum.js", "exporter.js", "leaderboard.js",
                    "collection.js", "team.js", "scratch.js"]) {
  const names = [...lire(file).matchAll(/^function (\w+)\s*\(/gm)]
    .map((m) => m[1]);
  const duplicates = names.filter((n, i) => names.indexOf(n) !== i);
  if (duplicates.length) {
    throw new Error(file + " declares twice: " + [...new Set(duplicates)]
      + " -- the last one wins, silently");
  }
}

// --- DOM en carton --------------------------------------------------------
// CE QUE LE MARKUP MASQUE DEJA. `<section id="vueprogres" hidden>` part masque
// dans un vrai navigateur ; un faux DOM qui le rend visible fait basculer a
// l'envers tout ce qui lit `.hidden` pour decider.
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
    // Un vrai element en a un : la vue « Mes progrès » y déplace le focus en
    // s'ouvrant, et un harnais qui ne le connait pas ferait lever la page.
    focus() { focusé = this.id; },
    getAttribute(k) { return this.attrs[k]; },
    addEventListener(ev, fn) { this.listeners[ev] = fn; },
    // UN <a download> QU'ON CLIQUE, c'est un fichier qui part sur le disque.
    // Ici on retient ce qui serait parti : le CONTENU du main.c exporte est
    // tout ce qu'on veut eprouver, et c'est la seule facon de l'atteindre sans
    // navigateur. Les autres elements gardent le comportement attendu --
    // declencher leur ecouteur de clic.
    click() {
      if (this.download) {
        telechargements.push({ nom: this.download,
                               texte: (blobs[this.href] || {}).texte || "" });
      }
      if (this.listeners.click) this.listeners.click();
    },
    remove() {
      if (this.parent) {
        this.parent.children = this.parent.children.filter((k) => k !== this);
      }
    },
    append(...kids) {
      for (const k of kids) if (k && typeof k === "object") k.parent = this;
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
      const fichier = v.split("?", 1)[0];
      let echec = chargementCasse;
      if (!echec) {
        try {
          new Function(lire(fichier))();
          // DOMPurify vient de s'attacher SANS DOM : dans un navigateur il en
          // trouve un, ici il faut lui en tendre un. `DOMPurify(window)` rend
          // une instance neuve -- c'est l'API documentee du paquet, pas un
          // contournement du harnais.
          if (/purify/.test(fichier) && typeof global.DOMPurify === "function") {
            global.DOMPurify = global.DOMPurify(new JSDOM("").window);
          }
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
// Le dernier element a avoir recu le focus. Changer d'ecran sans l'emmener
// laisse la tabulation au debut de la page et n'annonce rien a un lecteur.
let focusé = null;
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

// LISTENERS ATTACHED TO THE DOCUMENT ITSELF. The Ctrl+K shortcut sets one:
// without this half of the fake DOM, the page would throw on load -- exactly
// the class of bug this file exists to catch, but on the wrong side of the
// fence.
const documentListeners = {};

global.document = {
  addEventListener: (name, fn) => { (documentListeners[name] ||= []).push(fn); },
  // SVG GOES THROUGH `createElementNS`: the collection draws its parts as
  // nodes, never as `innerHTML`. The fake DOM does not distinguish
  // namespaces -- it does not have to, it renders nothing.
  createElementNS: (ns, tag) => el("<" + tag + ">"),
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
// UN HOTE INCONNU DE `config.js`, expres : le harnais joue le mode local,
// celui où `app/main.py` sert encore la page et ou les appels restent relatifs.
// Les deux autres branches sont eprouvees a la fin du fichier.
global.location = { search: "?k=cle-de-test", hostname: "ctester.example" };
global.URLSearchParams = URLSearchParams;

// Les minuteurs sont CAPTURÉS, pas exécutés. La page en pose deux sortes : le
// sondage du verdict, qu'on ne veut surtout pas voir boucler dans un test, et
// le délai d'enregistrement du brouillon, qu'on veut déclencher à la main
// plutôt que d'attendre 1,5 seconde réelle.
const timers = [];
global.setTimeout = (fn) => timers.push(fn);
global.clearTimeout = () => {};
// Le battement du compteur de presence pose un setInterval : capture, jamais
// execute. L'appel immediat de `battement()` au chargement suffit a prouver
// que la requete part et que le chiffre s'affiche.
global.setInterval = () => 0;
global.clearInterval = () => {};
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
// LE TELECHARGEMENT, EN CARTON. Node n'a ni Blob navigable ni
// `URL.createObjectURL` : on retient le texte qu'on leur donne. Deux methodes
// posees SUR l'URL de Node plutot qu'un objet neuf -- remplacer la classe
// casserait tout ce qui voudrait construire une vraie URL un jour.
const telechargements = [];
const blobs = {};
let blobSuivant = 0;
global.Blob = function (parts, options) {
  this.type = options && options.type;
  this.texte = parts.join("");
};
URL.createObjectURL = (blob) => {
  const url = "blob:ctester/" + (++blobSuivant);
  blobs[url] = blob;
  return url;
};
URL.revokeObjectURL = (url) => { delete blobs[url]; };

// Ou la page envoie l'etudiant quand il accepte de se connecter.
const redirections = [];
global.history = { replaceState: () => {} };
global.location.assign = (url) => { redirections.push(url); };
global.location.origin = "https://ctester.example";
global.location.pathname = "/";

const UN_FICHIER = [{ name: "submission.c" }];
// LE DETAIL, SERVI A PART. `/catalog.json` ne porte que le menu et la liste
// blanche des noms de fichiers ; consigne et gabarits vivent ici.
const DETAILS = {
  "dev-a": { statement: "Écris main().", files: [{ name: "main.c", template: "" }] },
  "dev-b": { statement: "Écris la lib.", files: [{ name: "lib.c", template: "" }] },
  "tp2-ex0": { statement: "", files: UN_FICHIER },
  "tp2-ex3": { statement: "Calcule U = R * I.", files: UN_FICHIER },
  "tp7-ex1": { statement: "", files: [{ name: "calendrier.h", template: "#define VRAI 1\n" }, { name: "calendrier.c", template: "#include \"calendrier.h\"\n" }] },
};
// TROIS PREMIERS CHARGEMENTS DIFFÉRENTS, DONC TROIS PROCESSUS. La page ne lit
// le catalogue qu'une fois, au chargement : un catalogue absent et un lien
// profond verrouillé ne sont pas des états dans lesquels on peut entrer après
// coup. Le mode par défaut ("") est celui de la production ; les deux autres
// sont relancés dans un sous-processus à la fin de ce fichier.
const MODE = process.env.CTESTER_MODE || "";
if (MODE === "verrou") global.location.search = "?tp=tp12-ex1";
// SANS CLE D'ACCES : le lien de Moodle porte `?k=`, mais un signet, une
// adresse tapee de tete ou un lien partage entre etudiants ne l'ont pas.
if (MODE === "sanscle") global.location.search = "";

// LE CATALOGUE v2 TEL QUE `publish_content.projection()` l'écrit. Il porte
// TOUS les exercices, ouverts ou non -- montrer n'est pas donner -- et
// `tp2-ex3` appartient à DEUX collections, ce que la forme v1 ne savait pas
// dire.
const DEMAIN = new Date(Date.now() + 30 * 86400e3).toISOString();
const CATALOG_V2 = {
  schema_version: 1,
  skills: ["variables", "arithmetic-operators"],
  exercises: [
    { id: "tp1", title: "encodage binaire", mode: "quiz", access: "available",
      release: { state: "available" }, skills: [], files: [] },
    { id: "tp2-ex0", title: "ex.0 âge", mode: "io", access: "available",
      release: { state: "available" }, skills: [], files: UN_FICHIER },
    { id: "tp2-ex3", title: "ex.3 loi d'Ohm", mode: "io", access: "available",
      release: { state: "available" }, files: UN_FICHIER,
      skills: ["variables", "arithmetic-operators"],
      contexts: ["electrical"], difficulty: "foundation" },
    // UNE VÉRIFICATION, dans le TP qu'elle vérifie. Elle est en mode « io »
    // exprès : c'est le seul mode exportable, donc le seul où l'oubli du
    // filtre se verrait dans un main.c de remise.
    { id: "verif-tp2", title: "vérification du TP 2", mode: "io",
      access: "available", release: { state: "available" }, verification: true,
      skills: ["variables"], files: UN_FICHIER },
    { id: "tp7-ex1", title: "ex.1 est_bissextile", mode: "unity",
      access: "available", release: { state: "available" }, skills: [],
      files: [{ name: "calendrier.h" }, { name: "calendrier.c" }] },
    // PAS ENCORE OUVERT, et il figure quand même au menu : la v1 le faisait
    // disparaître, ce qui ressemblait à une panne la veille du cours.
    { id: "tp12-ex1", title: "ex.1 tri", mode: "io", access: "scheduled",
      release: { state: "scheduled", available_from: DEMAIN },
      skills: [], files: UN_FICHIER },
    // LE DEVOIR D'ÉQUIPE. Ses exercices portent `assignment`, et c'est ce
    // seul champ qui fait ouvrir un espace partagé plutôt que l'éditeur
    // individuel -- tous les autres exercices ci-dessus ne le portent pas, et
    // doivent continuer de se comporter exactement comme avant.
    { id: "dev-a", title: "partie A", mode: "io", access: "available",
      release: { state: "available" }, skills: [], assignment: "devoir",
      files: [{ name: "main.c" }] },
    { id: "dev-b", title: "partie B", mode: "io", access: "available",
      release: { state: "available" }, skills: [], assignment: "devoir",
      files: [{ name: "lib.c" }] },
  ],
  assignments: [
    { id: "devoir", title: "Devoir — Analyseur GPS", description: "",
      items: ["dev-a", "dev-b"], team: { min: 3, max: 4 },
      deadline: "2026-12-05T23:59:00-05:00",
      release: { state: "available" }, access: "available",
      handin: { root: "Devoir", files: [
        { name: "main.c", exercise_id: "dev-a", file: "main.c" },
        { name: "matrac_lib.c", exercise_id: "dev-b", file: "lib.c" }] } },
  ],
  collections: [
    { id: "tp1", title: "TP 1", description: "", items: ["tp1"],
      release: { state: "available" }, access: "available" },
    { id: "tp2", title: "TP 2", description: "",
      items: ["tp2-ex0", "tp2-ex3", "verif-tp2"],
      release: { state: "available" }, access: "available" },
    { id: "tp6", title: "TP 6", description: "", items: ["tp7-ex1"],
      release: { state: "available" }, access: "available" },
    { id: "tp10", title: "TP 10", description: "", items: ["tp12-ex1"],
      release: { state: "available" }, access: "available" },
    { id: "revisions", title: "Révisions", description: "",
      items: ["tp2-ex3"], release: { state: "available" }, access: "available" },
    { id: "devoir", title: "Devoir", description: "", items: ["dev-a", "dev-b"],
      release: { state: "available" }, access: "available" },
  ],
};

const calls = [];
// Un déploiement où la connexion EST configurée, ET où le forum est activé
// (donc où des modérateurs sont configurés côté serveur). Tout ce qui suit doit
// malgré tout se comporter comme avant tant que personne ne s'est connecté :
// c'est la combinaison la plus exigeante pour la promesse « l'anonyme ne
// télécharge rien ».
// Le bloc-notes de la Console, tel que le compte le garde d'une machine a
// l'autre. Ecrit par le PUT du module, relu par le GET.
let BLOC_NOTES = "";
const OIDC_RESPONSE = { issuer: "https://auth.example", client_id: "ctester",
                        forum: true, scratch: true };
let SUBMIT_RESPONSE;
let DECOUVERTE_CASSEE = false;
const JETON = "jeton-de-test";
// LE THÈME DU COMPTE, cote serveur. Une chaine vide veut dire « ce compte n'a
// rien choisi » -- ce qui n'est pas la meme chose qu'une panne, et la page ne
// doit pas ecraser le theme de l'appareil dans ce cas.
let THEME_SERVEUR = "";
const ETATS = { states: [{ exercise_id: "tp2-ex0", status: "solved" }] };
const PRATIQUE = { practice: [
  { exercise_id: "tp2-ex3", attempts: 3, successes: 1 }] };
let POLL_RESPONSE = { state: "queued", position: 1 };
let PROGRES_CASSE = false;
// Les brouillons que le COMPTE porte, par-dela cet appareil : c'est ce qui
// permet a l'export d'assembler un exercice travaille au labo depuis la maison.
let BROUILLONS_SERVEUR = {};

// --- Le forum, cote serveur, en carton -------------------------------------
// Un modele minuscule mais VIVANT : ce qu'on publie se relit, ce qu'on masque
// disparait pour un etudiant, ce qu'on signale remonte au moderateur. Un stub
// qui repondrait toujours la meme chose ne prouverait pas que la page relit le
// serveur au lieu de tenir son propre etat.
let FORUM_CASSE = false;
let FORUM_MODERATEUR = false;
const FORUM_MAX = 400;
// UN TEXTE HOSTILE, ecrit par un autre etudiant. C'est la donnee la moins
// digne de confiance de toute la page : si elle passe par innerHTML, elle
// s'execute chez celui qui lit le fil.
// LES MESSAGES SONT STOCKÉS SOUS L'EXERCICE NU, et le faux serveur traduit la
// clé de fil (`@chat:tp2-ex3`) vers elle : le chat et le forum d'un exercice
// partagent la table côté serveur, donc les partager ici garde le harnais
// aussi proche de la production que possible.
const FORUM = {
  "tp2-ex3": [{ id: "m-autre", ex: "tp2-ex3", author: "Rotor cuivré",
                mine: false, hidden: false, created_at: "2026-09-03T22:30Z",
                reportable_name: false, reply_to: null,
                upvotes: 0, downvotes: 0, my_vote: 0,
                text: "<img src=x onerror=alert(1)> j'ai la meme erreur" },
              { id: "m-nomme", ex: "tp2-ex3", author: "Bob B", mine: false,
                hidden: false, created_at: "2026-09-03T22:35Z", group: 4,
                reportable_name: true, reply_to: null,
                upvotes: 0, downvotes: 0, my_vote: 0, text: "moi aussi" }],
  "tp2-ex0": [],
};
// LA CLÉ DE FIL -> LE MAGASIN. `@chat:general` a le sien, comme sur le serveur.
const filNu = (cle) => String(cle || "").replace(/^@chat:/, "");
const FORUM_SIGNALES = new Map();   // identifiant de message -> combien de fois
// LE PROFIL DE CE COMPTE. `suggestion` est le `preferred_username` de Rauthy :
// une PROPOSITION, qui ne doit rien afficher tant qu'on n'a pas enregistre.
// `alias` PART À NULL, EXPRÈS : c'est l'état de tout compte qui n'a jamais
// ouvert le classement, c'est-à-dire l'état où le bouton était introuvable.
const PROFIL = { display_name: null, group_number: null, display_name_public: false,
                 group_number_public: false, max_display_name: 24, group_numbers: [4, 6],
                 alias: null, suggestion: "vveremme" };
const forumEnvois = [];
let forumCompteur = 0;
// UNE COMPETENCE HOSTILE : les identifiants viennent du depot de tests, et un
// libelle inconnu s'affiche tel quel. S'il finit dans du HTML, il s'execute.
const PROGRES = {
  policy: "pilote-1",
  xp: 45,
  level: { rank: 2, since: 30, next: 80, remaining: 35 },
  exercises: { total: 4, practiced: 2, solved: 1 },
  skills: [
    { id: "variables", total: 2, practiced: 2, solved: 1 },
    { id: "<img src=x onerror=alert(1)>", total: 1, practiced: 1, solved: 0 },
  ],
  achievements: [{ id: "premiere-reussite", title: "Premier exercice réussi",
             description: "Tu as fait passer tous les tests d'un exercice.",
             unlocked_at: "2026-09-01" }],
  mastery: {
    bands: [
      { id: "verifie", title: "Vérifié", description: "Toutes réussies." },
      { id: "en-progression", title: "En progression", description: "Il en reste." },
      { id: "a-consolider", title: "À consolider", description: "Reviens pratiquer." },
      { id: "non-verifie", title: "Pas encore vérifié", description: "Rien de tenté." },
    ],
    skills: [
      { id: "variables", total: 2, attempted: 1, passed: 1, band: "en-progression" },
      { id: "<img src=x onerror=alert(1)>", total: 1, attempted: 0, passed: 0,
        band: "non-verifie" },
    ],
  },
  next: { exercise_id: "tp2-ex3", skill: "variables" },
  transactions: [{ exercise_id: "tp2-ex0", amount: 15,
                   reason: "première réussite", granted_at: "2026-09-01" }],
};
// --- L'espace d'équipe, côté serveur, en carton ----------------------------
// LE DOCUMENT PARTAGÉ EST TENU ICI, comme Postgres le tiendrait : ce que la
// page écrit se relit, et ce qu'elle n'a pas écrit n'apparaît pas. Le bandeau
// et l'éditeur doivent lire le serveur, pas leur propre mémoire.
const EQUIPE = {
  assignment: { id: "devoir", title: "Devoir — Analyseur GPS", description: "",
                items: ["dev-a", "dev-b"], team: { min: 3, max: 4 },
                deadline: "2026-12-05T23:59:00-05:00", deadline_passed: false,
                access: "available",
                handin: [{ name: "main.c", exercise_id: "dev-a", file: "main.c" },
                         { name: "matrac_lib.c", exercise_id: "dev-b",
                           file: "lib.c" }] },
  team: { id: "e1", label: "Équipe 1", group_number: 4, members: [
    { id: "m1", name: "Coéquipier 1", color: "#e0533d", you: true },
    { id: "m2", name: "Bob B", color: "#2f8fd8", you: false },
    { id: "m3", name: "Coéquipier 3", color: "#7d57c1", you: false }] },
  submission: {},
};
// (`EQUIPE_MUETTE`, `MON_EQUIPE` et `DEVOIR_OUVERT` sont déclarés avec le
// serveur de choix d'équipe plus bas : c'est lui qui les lit.)
const DOCUMENTS = { "dev-a": { "main.c": "int main(void){return 0;}\n" } };
const REVISIONS = [{ id: "r1", author: "m2", created_at: "2026-09-07T14:32Z",
                     bytes: 640 }];
const equipeEnvois = [];

function equipeRepond(url, opts) {
  const porteur = opts && opts.headers && opts.headers.Authorization;
  if (porteur !== "Bearer " + JETON) return rendErreur(401, "connexion requise");
  const methode = (opts && opts.method) || "GET";
  const corps = opts && opts.body ? JSON.parse(opts.body) : null;
  const chemin = String(url).split("?")[0];
  const ex = decodeURIComponent(String(url).split("ex=")[1] || "");
  if (chemin.startsWith("team/") && FORMATION[chemin.slice(5)]) {
    return FORMATION[chemin.slice(5)](corps);
  }
  if (chemin === "team/context") {
    // L'ESPACE DE TRAVAIL SUPPOSE UNE ÉQUIPE : ce bouchon-là sert aux
    // contrôles du bandeau et de l'éditeur partagé, qui n'ont pas à rejouer
    // le choix d'équipe pour y arriver.
    if (CONTEXTE_REFUSE) {
      return rendErreur(403, "tu n'es dans aucune équipe pour ce devoir, et "
                             + "les équipes sont figées depuis son ouverture "
                             + "— vois avec ton enseignant");
    }
    return rendJson(EQUIPE);
  }
  if (chemin === "team/document" && methode === "GET") {
    return rendJson({ exercise_id: ex, sources: DOCUMENTS[ex] || {} });
  }
  if (chemin === "team/document") {
    equipeEnvois.push({ url: chemin, corps });
    DOCUMENTS[corps.exercise_id] = corps.files;
    return rendJson({ ok: true });
  }
  if (chemin === "team/revisions") return rendJson({ exercise_id: ex, revisions: REVISIONS });
  if (chemin === "team/handin.zip") {
    // L'ARCHIVE EST CONSTRUITE PAR LE SERVEUR : la page ne fait que la
    // recevoir, et c'est ce qu'on vérifie -- elle n'envoie AUCUN fichier.
    return { ok: true, status: 200,
             blob: async () => new Blob(["PK-archive"], { type: "application/zip" }) };
  }
  if (chemin === "team/handin") {
    equipeEnvois.push({ url: chemin, corps });
    EQUIPE.submission = { submitted_by: "moi", submitted_at: "2026-09-07T15:00Z" };
    return rendJson({ ok: true, submission: EQUIPE.submission,
                      files: ["Devoir/main.c", "Devoir/matrac_lib.c"] });
  }
  return rendErreur(404, "inconnu");
}

// --- Le choix d'équipe, côté serveur, en carton mais VIVANT ----------------
// LES ÉQUIPES PRÉEXISTENT, NUMÉROTÉES PAR GROUPE, et on prend une place libre
// -- le geste de Moodle, avec les mêmes numéros. Ce modèle-ci tient l'état
// pour de vrai : un bouchon qui répondrait toujours la même chose ne
// prouverait pas que la page relit le serveur au lieu de tenir sa propre idée
// de qui est où.
let MON_EQUIPE = null;          // le numéro de MON équipe, ou null
let EQUIPE_MUETTE = false;      // la route qui n'existe pas encore
let DEVOIR_OUVERT = false;      // une fois ouvert, les équipes sont figées
// L'ESPACE DE TRAVAIL REFUSÉ : ce que `/team/context` répond à quelqu'un qui
// n'a pas d'équipe sur un devoir OUVERT. C'est le cas où le bandeau doit
// expliquer plutôt que de disparaître.
let CONTEXTE_REFUSE = false;
// Le remplissage des équipes du groupe, hors moi. L'équipe 2 est complète
// exprès : c'est le refus qu'on veut voir dessiné.
const REMPLISSAGE = { 1: 1, 2: 4, 3: 0, 4: 0, 5: 0, 6: 0 };
const MAX = 4;

const vueListe = () => ({
  assignment_id: "devoir", group_number: 4, mine: MON_EQUIPE,
  teams: Object.keys(REMPLISSAGE).map((n) => {
    const numero = Number(n);
    const membres = REMPLISSAGE[numero] + (MON_EQUIPE === numero ? 1 : 0);
    return { number: numero, name: "Équipe " + numero, members: membres,
             max: MAX, full: membres >= MAX };
  }),
});

const vueMienne = () => MON_EQUIPE === null ? [] : [{
  assignment_id: "devoir", assignment_title: "Devoir — Analyseur GPS",
  access: DEVOIR_OUVERT ? "available" : "scheduled",
  available_from: "2099-10-16T00:00:00-04:00",
  deadline: "2099-12-05T23:59:00-05:00",
  joinable: !DEVOIR_OUVERT,
  number: MON_EQUIPE, label: "Équipe " + MON_EQUIPE, group_number: 4,
  members: [{ id: "m1", name: "Coéquipier 1", color: "#e0533d",
              you: true }],
}];

const FORMATION = {
  mine: () => {
    if (EQUIPE_MUETTE) return rendErreur(404, "inconnu");
    return rendJson({ teams: vueMienne() });
  },
  available: () => {
    // LES ÉQUIPES SE FIGENT À L'OUVERTURE DU DEVOIR : la même date que celle
    // qui ouvre le document, prise dans l'autre sens.
    if (DEVOIR_OUVERT) {
      return rendErreur(409, "les équipes sont figées : le devoir est ouvert");
    }
    return rendJson(vueListe());
  },
  join: (corps) => {
    equipeEnvois.push({ url: "team/join", corps });
    if (DEVOIR_OUVERT) return rendErreur(409, "les équipes sont figées");
    if (MON_EQUIPE !== null) {
      return rendErreur(409, "tu es déjà dans une équipe : quitte-la d'abord");
    }
    if (!(corps.number in REMPLISSAGE)) {
      return rendErreur(404, "cette équipe n'existe pas (il y en a 6)");
    }
    if (REMPLISSAGE[corps.number] >= MAX) {
      return rendErreur(409, "cette équipe est complète (4 places)");
    }
    MON_EQUIPE = corps.number;
    return rendJson(vueListe());
  },
  leave: (corps) => {
    equipeEnvois.push({ url: "team/leave", corps });
    if (DEVOIR_OUVERT) return rendErreur(409, "les équipes sont figées");
    if (MON_EQUIPE === null) return rendErreur(404, "aucune équipe");
    MON_EQUIPE = null;
    return rendJson(vueListe());
  },
};

// LA SOCKET, EN CARTON MAIS SYMÉTRIQUE : ce que la page envoie est retenu, et
// le harnais peut lui pousser une trame comme le ferait un coéquipier. C'est
// la seule façon d'éprouver que le CRDT est vraiment branché sur l'éditeur --
// un bouchon muet prouverait seulement qu'on ouvre une socket.
const sockets = [];
global.WebSocket = function (url) {
  this.url = url;
  this.readyState = 1;
  this.envoyes = [];
  this.send = (texte) => { this.envoyes.push(JSON.parse(texte)); };
  this.close = () => { this.readyState = 3; };
  sockets.push(this);
  // `onopen` part au tour suivant, comme un vrai navigateur.
  setImmediate(() => { if (this.onopen) this.onopen(); });
};
const derniereSocket = () => sockets[sockets.length - 1];
// COMBIEN DE SALLES DE CHAT SONT TENUES EN MÊME TEMPS. Le dock et la vue
// large lisent le MÊME fil : deux sockets pour un lecteur doubleraient la
// charge que `FORUM_LIVE_MAX` borne côté serveur, et mettraient deux
// compteurs sur la même personne.
const socketsOuvertes = () => sockets.filter(
  (s) => s.readyState === 1 && /forum\/live/.test(String(s.url))).length;
const recevoir = (trame) => {
  const socket = derniereSocket();
  if (socket && socket.onmessage) socket.onmessage({ data: JSON.stringify(trame) });
};

global.fetch = async (url, opts) => {
  calls.push({ url, opts });
  if (String(url).split("?")[0].startsWith("team/")) return equipeRepond(url, opts);
  if (url === "catalog.json") {
    // RIEN DE PUBLIÉ = 404, et depuis la phase 8 il n'y a plus de repli : la
    // page doit le DIRE plutôt que dessiner un menu vide, qui ressemblerait à
    // un semestre qui n'a pas commencé.
    return MODE === "absent"
      ? { ok: false, status: 404, json: async () => ({ error: "catalogue absent" }) }
      : { ok: true, status: 200, json: async () => CATALOG_V2 };
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
  if (url === "live" || String(url).startsWith("live?")) {
    return { ok: true, status: 200, json: async () => ({ n: 3 }) };
  }
  if (url === "oidc.json") {
    return { ok: true, status: 200, json: async () => OIDC_RESPONSE };
  }
  if (url === "etats" || url === "pratique" || url === "progres") {
    // LE JETON FAIT FOI. Une requete de compte sans en-tete doit repartir
    // vide : c'est ce qui distingue « pas connecte » de « rien a montrer ».
    const porteur = opts && opts.headers && opts.headers.Authorization;
    if (porteur !== "Bearer " + JETON) {
      return { ok: false, status: 401, json: async () => ({}) };
    }
    if (url === "progres" && PROGRES_CASSE) {
      return { ok: false, status: 503,
               json: async () => ({ error: "la base ne répond pas" }) };
    }
    return { ok: true, status: 200, json: async () => (
      url === "etats" ? ETATS : url === "pratique" ? PRATIQUE : PROGRES) };
  }
  if (url === "scratch/draft") {
    // MEME PORTE QUE LES AUTRES ROUTES DE COMPTE : le jeton fait foi.
    const porteur = opts && opts.headers && opts.headers.Authorization;
    if (porteur !== "Bearer " + JETON) {
      return { ok: false, status: 401, json: async () => ({}) };
    }
    if (opts && opts.method === "PUT") {
      BLOC_NOTES = JSON.parse(opts.body).code;
      return rendJson({ ok: true });
    }
    return rendJson({ code: BLOC_NOTES });
  }
  if (url === "preferences") {
    // MEME PORTE QUE LES AUTRES ROUTES DE COMPTE : le jeton fait foi.
    const porteur = opts && opts.headers && opts.headers.Authorization;
    if (porteur !== "Bearer " + JETON) {
      return { ok: false, status: 401, json: async () => ({}) };
    }
    if (opts && opts.method === "PUT") {
      THEME_SERVEUR = JSON.parse(opts.body).theme;
      return { ok: true, status: 200, json: async () => ({ ok: true }) };
    }
    return { ok: true, status: 200, json: async () => ({ theme: THEME_SERVEUR }) };
  }
  if (url.startsWith("brouillon")) {
    // LE BROUILLON QUE LE COMPTE A, ET QUE CET APPAREIL N'A PAS. Vide par
    // defaut : c'est l'etat normal, et le remplir en permanence ferait passer
    // l'export pour bon alors qu'il lirait le stockage local.
    const ex = decodeURIComponent(String(url).split("ex=")[1] || "");
    return { ok: true, status: 200,
             json: async () => ({ sources: BROUILLONS_SERVEUR[ex] || {} }) };
  }
  // LE TIRAGE DU NOM MASQUÉ, comme le serveur : il ÉCRIT sur le profil, y
  // compris quand il n'y en avait pas -- c'est exactement l'état où le bouton
  // était introuvable, donc l'état que ce harnais doit reproduire.
  if (String(url) === "leaderboard/alias") {
    PROFIL.alias = PROFIL.alias === "Rotor cuivré" ? "Piston lisse" : "Rotor cuivré";
    return rendJson({ alias: PROFIL.alias });
  }
  if (String(url).startsWith("forum")) return forumRepond(url, opts);
  if (url.split("?")[0] === "submit") return SUBMIT_RESPONSE;
  return { ok: true, status: 200, json: async () => POLL_RESPONSE };
};

// Le serveur du forum, en carton mais VIVANT : ce qu'on publie se relit, ce
// qu'on masque disparait pour un etudiant, ce qu'on signale remonte au
// moderateur. Un bouchon qui repondrait toujours la meme chose ne prouverait
// pas que la page relit le serveur au lieu de tenir son propre etat.
const rendJson = (v) => ({ ok: true, status: 200, json: async () => v });
const rendErreur = (code, quoi) =>
  ({ ok: false, status: code, json: async () => ({ error: quoi }) });

function forumRepond(url, opts) {
  const porteur = opts && opts.headers && opts.headers.Authorization;
  // LE JETON FAIT FOI, comme sur les autres routes de compte.
  if (porteur !== "Bearer " + JETON) return rendErreur(401, "connexion requise");
  if (FORUM_CASSE) return rendErreur(503, "la base ne répond pas");
  const methode = (opts && opts.method) || "GET";
  const corps = opts && opts.body ? JSON.parse(opts.body) : null;
  const tous = () => Object.keys(FORUM).flatMap((ex) => FORUM[ex]);

  if (String(url).startsWith("forum/moderation")) {
    if (!FORUM_MODERATEUR) return rendErreur(403, "réservé à l'enseignant");
    if (methode === "GET") {
      return rendJson({ reports: tous()
        .filter((m) => FORUM_SIGNALES.has(m.id))
        .map((m) => ({ id: m.id, exercise_id: m.ex, text: m.text,
                       hidden: m.hidden, created_at: m.created_at,
                       report_count: FORUM_SIGNALES.get(m.id) })),
        reported_names: [] });
    }
    forumEnvois.push({ url, corps });
    const cible = tous().find((m) => m.id === corps.id);
    if (!cible) return rendErreur(404, "message introuvable");
    cible.hidden = corps.action === "hide";
    return rendJson({ ok: true });
  }
  // LE PROFIL : le nom qu'on s'est donne, le groupe, et ce qui est affiche.
  if (url === "forum/profil") {
    if (methode === "GET") return rendJson(Object.assign({}, PROFIL));
    forumEnvois.push({ url, corps });
    Object.assign(PROFIL, {
      display_name: corps.display_name || null,
      group_number: corps.group_number === "" ? null : Number(corps.group_number),
      display_name_public: !!corps.display_name_public && !!corps.display_name,
      group_number_public: !!corps.group_number_public,
      suggestion: "",
    });
    // Le fil reflete le nom choisi, comme le ferait le serveur.
    for (const m of tous()) {
      if (!m.mine) continue;
      m.author = PROFIL.display_name_public ? PROFIL.display_name : "Vous";
    }
    return rendJson({ ok: true });
  }
  if (url === "forum/signalement") {
    forumEnvois.push({ url, corps });
    FORUM_SIGNALES.set(corps.id, (FORUM_SIGNALES.get(corps.id) || 0) + 1);
    return rendJson({ ok: true });
  }
  if (methode === "POST") {
    forumEnvois.push({ url, corps });
    if (corps.text.length > FORUM_MAX) {
      return rendErreur(400, "message trop long (maximum " + FORUM_MAX
                             + " caractères)");
    }
    forumCompteur++;
    const cle = filNu(corps.exercise_id);
    (FORUM[cle] || (FORUM[cle] = [])).push({
      id: "m" + forumCompteur, ex: cle, author: "Vous (Rotor cuivré)",
      mine: true, hidden: false,
      created_at: "2026-09-03 10:0" + forumCompteur,
      reply_to: corps.reply_to || null,
      upvotes: 0, downvotes: 0, my_vote: 0,
      text: corps.text });
    return rendJson({ ok: true });
  }
  if (methode === "DELETE") {
    forumEnvois.push({ url, corps: null });
    const id = decodeURIComponent(String(url).split("id=")[1] || "");
    for (const ex of Object.keys(FORUM)) {
      FORUM[ex] = FORUM[ex].filter((m) => m.id !== id || !m.mine);
    }

    return rendJson({ ok: true });
  }
  const cle = decodeURIComponent(String(url).split("ex=")[1] || "");
  return rendJson({
    exercise_id: cle,
    chat: cle.startsWith("@chat:"),
    moderator: FORUM_MODERATEUR,
    max: FORUM_MAX,
    messages: (FORUM[filNu(cle)] || []).filter(
      (m) => FORUM_MODERATEUR || !m.hidden),
  });
}

// UNE VISITE PRÉCÉDENTE, déposée avant que la page ne démarre : un brouillon
// bien formé, et deux entrées empoisonnées. Ce qui sort du stockage n'est pas
// de la donnée de confiance, et seule la première doit atteindre l'éditeur.
storage["ctester.drafts"] = JSON.stringify({
  "tp2-ex3": { "submission.c": "// travail d'hier" },
  "tp2-ex0": { "submission.c": { pas: "une chaîne" } },
  "tp7-ex1": "pas un objet de fichiers",
});

// `config.js` D'ABORD, comme en fin de <body> : il pose `window.API`, dont
// depend chaque appel du noyau. L'oublier ferait tomber la page sur une
// ReferenceError au premier fetch, et pas une ligne plus tot.
new Function(lire("config.js"))();
new Function(js)();

const sleep = () => new Promise((r) => setImmediate(r));
let failures = 0;
function check(cond, label) {
  console.log((cond ? "ok   " : "ÉCHEC ") + label);
  if (!cond) failures++;
}

// CHAQUE SCÉNARIO SOUMET UN CODE DIFFÉRENT, et ce n'est pas cosmétique : la
// page ne renvoie plus au juge un code identique au précédent, elle réaffiche
// le verdict qu'elle tient. Un harnais qui rejouerait le même texte en
// changeant seulement la réponse du serveur éprouverait ce raccourci-là, pas
// le rendu des verdicts qu'il vise.
let variante = 0;
const codeUnique = () => `int main(void){return ${++variante};}`;
// CE QUE L'ÉTUDIANT LIT, DANS LES DEUX CANAUX. Le verdict (#out) parle de son
// code, le bandeau (#systeme) parle du service ; les assertions ci-dessous
// portent sur CE QU'IL EST DIT, pas sur le noeud qui le porte. En profondeur
// depuis que le verdict a des sous-blocs (étapes, explication, action suivante).
const profond = (n) => (n.textContent || "") + " "
  + (n.children || []).map(profond).join(" ");
const shown = () => profond(nodes.out) + " " + profond(nodes.systeme);
const contexte = () => nodes.now.children.map(c => c.textContent).join(" | ");

// CHANGER D'EXERCICE EST ASYNCHRONE depuis que le detail (consigne, gabarits)
// est charge a la demande : switchMode part chercher tp/<id>.json. Tout ce qui
// regarde l'editeur ou la consigne doit donc laisser passer les microtaches.
const collectionsMenu = () => nodes.exliste.children;
const titreCollection = (col) => col.children[0].children[0].textContent;
const cadenasCollection = (col) =>
  (col.children[0].children[1] || {}).textContent || "";
const lignesDe = (groupe) => {
  const col = collectionsMenu().find((c) => titreCollection(c) === groupe);
  return col ? col.children.filter((k) => k.dataset && k.dataset.id) : [];
};
const libelle = (ligne) => ligne.children.map((c) => c.textContent).join(" ");

async function choisir(groupe, id) {
  const lignes = lignesDe(groupe);
  const cible = id ? lignes.find((l) => l.dataset.id === id) : lignes[0];
  if (!cible) throw new Error("aucune ligne de menu pour " + groupe + "/" + id);
  cible.click();
  await attendre();
}
const attendre = async () => { await sleep(); await sleep(); };

(async () => {
  await sleep(); await sleep();

  // DEUX PREMIERS CHARGEMENTS QUI NE SONT PAS CELUI-CI. Chacun tourne dans son
  // propre processus (voir la fin du fichier) et ne rejoue pas la suite : ce
  // qu'on éprouve ici, c'est ce que la page fait AVANT que quiconque clique.
  if (MODE === "absent") {
    check(calls.some(c => c.url === "catalog.json"),
          "absent : le catalogue est demandé au chargement");
    check(!calls.some(c => String(c.url).startsWith("tp/")),
          "absent : et rien d'autre ne part -- pas de repli à essayer");
    check(/[Rr]echarge la page/.test(shown()),
          "absent : la page le dit : " + shown());
    check(global.ctester.catalogue().length === 0,
          "absent : et n'annonce aucun exercice, plutôt qu'un menu vide");
    console.log(failures ? `\n${failures} ÉCHEC(S)` : "\nun catalogue absent se voit");
    process.exit(failures ? 1 : 0);
  }
  if (MODE === "sanscle") {
    // ON LE DIT AU CHARGEMENT, PAS APRES QUE L'ETUDIANT A ECRIT SON CODE. Et on
    // le dit en francais d'etudiant : le 403 du serveur repond « cle de session
    // invalide ou expiree », qui ne veut rien dire et ne dit pas quoi faire.
    check(/clé d'accès/.test(nodes.systeme.textContent),
          "sans clé : la page le dit au chargement : " + nodes.systeme.textContent);
    check(/Moodle/.test(nodes.systeme.textContent),
          "sans clé : et dit OU aller la chercher");
    check(nodes.systeme.hidden === false, "sans clé : le bandeau est visible");
    // NON BLOQUANT : ecrire et enregistrer marchent parfaitement sans cle, et
    // c'est ce que le message promet.
    check(nodes.out.children.some(c => /En attente/.test(c.textContent || "")),
          "sans clé : le verdict reste au repos, ce n'est pas une panne");
    await choisir("TP 2", "tp2-ex0");
    nodes.code.value = "int main(void){return 0;}";
    nodes.code.listeners.input();
    fireLastTimer();
    check(!!storage["ctester.drafts"],
          "sans clé : le brouillon s'enregistre quand même");
    // ET ON N'ENVOIE RIEN QU'ON SAIT REFUSE.
    calls.length = 0;
    await nodes.go.listeners.click();
    await sleep();
    check(!calls.some(c => String(c.url).startsWith("submit")),
          "sans clé : aucune soumission n'est envoyée dans le vide");
    check(/clé d'accès/.test(nodes.systeme.textContent),
          "sans clé : et le bouton redit quoi faire plutôt que de rester muet");
    console.log(failures ? `\n${failures} ÉCHEC(S)`
                         : "\nla clé manquante se dit tôt");
    process.exit(failures ? 1 : 0);
  }
  if (MODE === "verrou") {
    // `?tp=tp12-ex1` VISE UN EXERCICE VERROUILLÉ. Le serveur refuse déjà de le
    // servir ; ce que la page doit faire, c'est le dire -- pas rester muette,
    // et pas non plus ressembler à un lien mort.
    check(nodes.menuex.open === true,
          "verrou : un lien profond verrouillé ouvre le menu");
    const col = collectionsMenu().find((c) => titreCollection(c) === "TP 10");
    check(!!col && col.open === true,
          "verrou : et déplie la collection de l'exercice visé");
    check(/ouvre le /.test(libelle(lignesDe("TP 10")[0])),
          "verrou : sur son cadenas et sa date");
    check(global.ctester.exerciceChoisi() === "tp1",
          "verrou : l'exercice affiché reste le premier exercice ouvert");
    check(!calls.some(c => c.url === "tp/tp12-ex1.json"),
          "verrou : son détail n'est jamais demandé");
    console.log(failures ? `\n${failures} ÉCHEC(S)` : "\nle lien verrouillé tient");
    process.exit(failures ? 1 : 0);
  }

  check(calls.some(c => c.url === "catalog.json"),
        "le catalogue est demandé au chargement");
  check(calls.filter(c => c.url === "catalog.json").length === 1,
        "une seule fois : il n'y a plus de repli à essayer");

  // --- LE DETAIL, CHARGE A LA DEMANDE ---
  // Le catalogue ne porte ni consigne ni gabarits : trois quarts de son poids
  // pour 73 exercices dont un seul est ouvert.
  check(calls.some(c => c.url === "tp/tp1.json"),
        "ouvrir un exercice demande son detail, a part");

  // --- CE QUI N'EST PAS TELECHARGE ---
  // Le deploiement OFFRE la connexion (oidc.json repond), et pourtant rien du
  // compte n'est descendu : personne ne s'est connecte. C'est la promesse de
  // tout ce decoupage, et le parcours anonyme est le parcours par defaut.
  check(!global.ctester.compte, "sans session, compte.js n'est pas charge");
  check(!charges.some(n => n.startsWith("compte.js?")),
        "et il n'est meme pas demande au serveur");
  check(!global.ctester.progres && !charges.some(n => n.startsWith("progres.js?")),
        "progres.js non plus : la progression n'existe qu'avec un compte");
  // LE DEPLOIEMENT OFFRE POURTANT LE FORUM (`oidc.forum` vaut true) : ni le
  // module, ni ses DEUX bibliotheques de rendu ne descendent. C'est 74 Ko que
  // l'etudiant anonyme -- le parcours par defaut -- ne paie jamais.
  check(!global.ctester.forum && !charges.some(n => n.startsWith("forum.js?")),
        "forum.js non plus, alors meme que le deploiement l'offre");
  check(!charges.some(n => /vendor\//.test(n)),
        "et aucune bibliotheque de rendu n'est telechargee sans compte");
  // NI L'ESPACE D'EQUIPE, NI SES 92 Ko DE CRDT. Le devoir est publie, ouvert,
  // et au menu -- et l'anonyme n'en telecharge pas un octet. C'est la meme
  // promesse que pour le forum, et elle vaut d'autant plus ici : Yjs est le
  // plus gros fichier de tout le site.
  check(!global.ctester.team && !charges.some(n => n.startsWith("team.js?")),
        "team.js non plus, alors meme que le devoir est ouvert");
  // NI LA CONSOLE. Elle ouvre une WebSocket et depense un conteneur sur le
  // Dell : c'est la fonctionnalite qu'un visiteur de passage doit le moins
  // pouvoir declencher, et son bouton n'existe meme pas sans compte.
  check(!global.ctester.scratch
        && !charges.some(n => n.startsWith("scratch.js?")),
        "scratch.js non plus : la Console n'existe pas sans compte");
  check(nodes.scratch.hidden === true,
        "et son bouton reste cache pour l'anonyme");
  check(charges.some(n => n.startsWith("quiz.js?")),
        "quiz.js, lui, arrive avec le premier exercice de ce mode");
  // LE COMPTEUR DE PRESENCE est la seule chose que l'anonyme demande au
  // serveur, et il s'affiche pour tout le monde. `/live` ne porte pas de jeton
  // et ne touche aucune donnee de compte -- voir le bloc anonyme plus bas.
  check(calls.some(c => String(c.url).startsWith("live")) &&
        /en ligne/.test(nodes.live.textContent) && nodes.live.hidden === false,
        "le compteur de presence s'affiche, meme sans compte : "
        + nodes.live.textContent);

  // --- LE THEME, SANS COMPTE : local, et MUET -------------------------------
  // Le bouton existe pour tout le monde, connecte ou non. Sans session il ne
  // doit toucher que cet appareil : une requete partie d'ici serait une requete
  // du parcours anonyme, ce que tout ce decoupage promet de ne jamais faire.
  const avantTheme = calls.length;
  const themeDepart = document.documentElement.dataset.theme;
  nodes.theme.listeners.click();
  check(document.documentElement.dataset.theme !== themeDepart,
        "le bouton de theme bascule l'affichage");
  check(storage["ctester.theme"] === document.documentElement.dataset.theme,
        "et le retient sur cet appareil, pour eviter le flash a la prochaine visite");
  check(calls.length === avantTheme,
        "sans compte, changer de theme n'emet AUCUNE requete");
  // ET UN DETAIL QUI N'ARRIVE PAS NE BLOQUE RIEN : publication en retard,
  // reseau coupe. Les NOMS de fichiers viennent du catalogue, donc on peut
  // encore coller son code et soumettre -- c'est tout ce qu'on promet ici.
  // `tp1` est l'exercice que la page ouvre seule, et DETAILS ne le porte pas
  // encore : c'est exactement ce cas qui vient de se jouer.
  // ET LES DEUX CAS NE SE DISENT PAS PAREIL. « pas de consigne en ligne » est une
  // propriete de l'exercice ; « pas pu etre chargee » est une panne passagere.
  // Les confondre faisait croire a un manque de contenu, donc on ne reessayait
  // jamais -- alors qu'un simple nouvel essai aurait suffi.
  check(/n'a pas pu être chargée/.test(nodes.consignetexte.textContent),
        "une consigne qui n'arrive pas se dit comme une panne, pas comme un vide : "
        + nodes.consignetexte.textContent.slice(0, 50));
  check(nodes.consignetexte.children.some(c => /Réessayer/.test(c.textContent || "")),
        "avec un bouton pour reessayer, plutot qu'une invitation a recharger la page");
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

  // LA COLONNE DE DROITE NE SE DIMENSIONNE PAS PAR POSITION, et c'est un bug
  // deja paye : `#droite` etait une grille dont la 2e ligne valait `1fr`, ce
  // qui convenait tant que l'editeur etait le 2e enfant. `#bandelabo`, ajoute
  // ensuite en 2e position, a herite du `1fr` -- trois puces d'exercice
  // occupaient la moitie de l'ecran. Et `#editor`/`#quizwrap` s'excluent en
  // `display: none`, donc les lignes se decalent selon le mode.
  //
  // ON N'EPROUVE PAS LA MISE EN PAGE (le DOM en carton n'en a pas), on eprouve
  // que chaque enfant DISE sa taille : ajouter un enfant sans regle `flex:`
  // fait echouer ici, la ou le navigateur ne dirait rien.
  {
    const bloc = css.slice(css.indexOf("#droite {"),
                           css.indexOf("}", css.indexOf("#droite {")));
    check(bloc.includes("flex-direction: column") && !bloc.includes("grid-template-rows"),
          "#droite est une colonne flex, pas un gabarit de lignes positionnel");
    const debut = html.indexOf('<div id="droite">');
    // Borne sur la fermeture a DEUX espaces : les enfants directs sont a
    // quatre, tout ce qui est plus profond ne matche pas la regex.
    const dedans = html.slice(debut, html.indexOf("\n  </div>", debut));
    const enfants = [...dedans.matchAll(/^ {4}<[a-z]+ ([^>]*)>/gm)].map((m) => {
      const id = /id="(\w+)"/.exec(m[1]);
      const classe = /class="([^"]+)"/.exec(m[1]);
      return { id: id ? id[1] : "?",
               // `#now` tient sa taille de `.phead` : un selecteur vaut
               // l'autre, ce qu'on refuse c'est qu'AUCUN ne la donne.
               selecteurs: ["#" + (id ? id[1] : "?")]
                 .concat(classe ? classe[1].trim().split(/ +/).map((c) => "." + c) : []) };
    });
    // ANCRE EN DEBUT DE LIGNE : sans elle, `.phead` tomberait sur
    // « .field label, .phead { » qui est un autre bloc, et le controle
    // repondrait sur la mauvaise regle.
    const taille = (sel) => {
      const i = css.indexOf("\n" + sel + " {");
      return i >= 0 && css.slice(i, css.indexOf("}", i)).includes("flex:");
    };
    const sansTaille = enfants.filter((e) => !e.selecteurs.some(taille))
                              .map((e) => e.id);
    check(enfants.length >= 5 && sansTaille.length === 0,
          "chaque enfant de #droite declare sa propre taille flex ("
          + enfants.length + " vus)"
          + (sansTaille.length ? " -- MANQUE : " + sansTaille.join(", ") : ""));
  }

  check(html.indexOf('id="go"') > html.indexOf('id="quizwrap"') &&
        html.indexOf('id="go"') > html.indexOf('id="editor"'),
        "« Tester » vient après les deux volets, donc en masquer un ne l'emporte pas");

  // --- LE MENU DU CATALOGUE : collections repliables, cadenas et dates ---
  check(collectionsMenu().map(titreCollection).join(",")
        === "TP 1,TP 2,TP 6,TP 10,Révisions,Devoir",
        "le menu liste les collections, dans l'ordre du catalogue");
  // LE DEVOIR EST UNE COLLECTION DE PLUS DANS LE MENU, et c'est voulu : le
  // menu répond « où sont les exercices », pas « qu'est-ce que je remets ».
  // Ce qu'un devoir ajoute vit dans son propre bandeau, pas ici.
  check(lignesDe("Devoir").map(l => l.dataset.id).join(",") === "dev-a,dev-b",
        "le devoir apparaît au menu comme n'importe quelle collection");
  const texteBandeau = () => nodes.now.children
    .map(c => c.textContent || "").join(" ");
  check(lignesDe("TP 2").map(l => l.dataset.id).join(",")
        === "tp2-ex0,tp2-ex3,verif-tp2",
        "chaque collection porte ses exercices");
  // MARQUÉE AU MENU, ET EN TOUTES LETTRES. Une vérification doit être
  // reconnaissable AVANT d'être ouverte : elle ne se pratique pas, elle se
  // passe. Une couleur seule ne le dirait pas.
  // ET UNE FOIS OUVERTE, le bandeau le redit -- avec « sans XP », qui est la
  // question qu'on se pose en arrivant dessus. La consigne se replie ; ce
  // bandeau, non.
  await choisir("TP 2", "verif-tp2");
  check(/vérification — sans XP/.test(texteBandeau()),
        "l'exercice ouvert dit qu'il est une vérification : " + texteBandeau());
  await choisir("TP 2", "tp2-ex3");
  check(!/vérification/.test(texteBandeau()),
        "et un exercice de pratique ne le dit pas : " + texteBandeau());

  const etiquettes = lignesDe("TP 2")
    .map(l => l.children.map(c => c.textContent || "").join(" "));
  check(/vérification/.test(etiquettes[2]) && !/vérification/.test(etiquettes[0]),
        "et une vérification est étiquetée, les exercices de pratique non : "
        + etiquettes.join(" // "));
  check(lignesDe("TP 2")[0].children[0].textContent === "ex.0 âge",
        "et le titre de l'exercice, sans préfixe de TP");

  // UN EXERCICE PAS ENCORE OUVERT RESTE AU MENU, désactivé, avec sa date. Le
  // faire disparaître -- ce que faisait la v1 -- ressemblait à une panne du
  // site la veille du cours.
  const verrouille = lignesDe("TP 10")[0];
  check(verrouille.getAttribute("aria-disabled") === "true"
        && !verrouille.listeners.click,
        "un exercice verrouillé est au menu, mais ne s'ouvre pas");
  // ET IL RESTE ATTEIGNABLE AU CLAVIER. `disabled` le sortait de l'ordre de
  // tabulation : la date d'ouverture n'existait que pour la souris, alors
  // qu'elle est toute la raison de laisser l'exercice affiche.
  check(verrouille.disabled !== true,
        "et il reste atteignable au clavier, pour qu'on entende sa date");
  check(/\ud83d\udd12/.test(libelle(verrouille))
        && /ouvre le /.test(libelle(verrouille)),
        "il porte un cadenas ET une date : « pas encore ouvert » ne suffit pas");
  check(!global.ctester.catalogue().some(t => t.id === "tp12-ex1"),
        "et il ne compte nulle part ailleurs : ni progression, ni export");

  // UN EXERCICE PEUT ÊTRE DANS DEUX COLLECTIONS -- c'est ce qu'un parcours
  // transversal veut dire -- sans compter deux fois pour autant.
  check(lignesDe("Révisions").map(l => l.dataset.id).join(",") === "tp2-ex3",
        "un exercice partagé s'affiche dans ses deux collections");
  check(global.ctester.catalogue().filter(t => t.id === "tp2-ex3").length === 1,
        "mais n'apparaît qu'une fois dans le catalogue des exercices ouverts");

  await choisir("TP 2");
  const deplie = collectionsMenu().filter(c => c.open).map(titreCollection);
  check(deplie.join(",") === "TP 2",
        "seule la collection où l'on travaille est dépliée");
  check(nodes.excourant.textContent === "ex.0 âge",
        "le bouton du menu nomme l'exercice ouvert");
  check(lignesDe("TP 2")[0].className.includes("on")
        && !lignesDe("TP 2")[1].className.includes("on"),
        "et la ligne courante est marquée dans la liste");
  check(nodes.menuex.open === false, "choisir un exercice referme le menu");
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
  await choisir("TP 6", "tp7-ex1");
  check(nodes.code.value === "#define VRAI 1\n",
        "une entrée mal formée du stockage est ignorée : c'est le gabarit qui sert");

  await choisir("TP 1");
  check(lignesDe("TP 1").length === 1 && !lignesDe("TP 1")[0].disabled,
        "une collection d'un seul exercice le montre quand meme : il n'y a plus "
        + "de second menu a masquer");
  check(/réponses à saisir/.test(contexte()), "la pastille suit le mode du TP");
  // LES TROIS MODES, et surtout unity : promettre « avec son main() » sur un
  // module envoie l'étudiant dans une erreur d'édition de liens.
  await choisir("TP 6", "tp7-ex1");
  check(/sans main\(\)/.test(contexte()),
        "un module unity annonce qu'il n'attend PAS de main() : " + contexte());

  // --- Le cas qui était cassé : une soumission de code ---
  await choisir("TP 2", "tp2-ex3");
  const premierCode = codeUnique();
  nodes.code.value = premierCode;
  SUBMIT_RESPONSE = { ok: true, status: 200, json: async () => ({ id: "a".repeat(32) }) };
  calls.length = 0;
  await nodes.go.listeners.click();
  await sleep(); await sleep();

  const post = calls.find(c => c.url.split("?")[0] === "submit");
  // Le jeton de poste sépare deux anonymes derrière une même IP NATée : sans
  // lui, le premier labo (personne n'est connecté) partage un seul quota.
  check(/[?&]poste=[^&]+/.test(post.url),
        "la soumission porte son jeton de poste", post.url);
  check(!!post, "le fetch de soumission part réellement");
  if (post) {
    const sent = JSON.parse(post.opts.body);
    check(sent.files["submission.c"] === premierCode,
          "le code est bien dans la charge utile, sous son nom de fichier");
    check(sent.exercise_id === "tp2-ex3" && sent.key === "cle-de-test",
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
  await choisir("TP 6", "tp7-ex1");
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
  const modulePost = calls.find(c => c.url.split("?")[0] === "submit");
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
  check(global.ctester.exerciceChoisi() === "tp2-ex3",
        "« suivant » avance d'un exercice");
  nodes.next.listeners.click();
  check(global.ctester.exerciceChoisi() === "verif-tp2",
        "« suivant » passe par la vérification du TP, elle est au menu comme "
        + "le reste");
  nodes.next.listeners.click();
  check(global.ctester.exerciceChoisi() === "tp7-ex1",
        "« suivant » franchit la fin d'un TP");
  // LES FLÈCHES NE MARCHENT QUE SUR CE QUI EST OUVERT : `tp12-ex1` est publié,
  // verrouillé, et suit `tp7-ex1` dans le catalogue. Le rang de la fin, c'est
  // le dernier exercice OUVERT, sinon « suivant » mènerait à un 404.
  nodes.next.listeners.click();
  await attendre();
  nodes.next.listeners.click();
  await attendre();
  check(global.ctester.exerciceChoisi() === "dev-b",
        "« suivant » traverse aussi les exercices d'un devoir");
  check(nodes.next.disabled === true, "le bouton se désactive au dernier exercice ouvert");
  nodes.prev.listeners.click();
  nodes.prev.listeners.click();
  nodes.prev.listeners.click();
  nodes.prev.listeners.click();
  nodes.prev.listeners.click();
  check(global.ctester.exerciceChoisi() === "tp2-ex0",
        "« précédent » revient sur ses pas");
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
  // L'INDICATEUR DIT OU, PAS SEULEMENT QUAND. « enregistre a 14:32 » ne repond
  // pas a la question que l'etudiant se pose en quittant le labo, qui est
  // « est-ce que je retrouve mon code chez moi ? ».
  check(/^enregistré sur cet appareil · \d\d:\d\d$/.test(nodes.sauvegarde.textContent),
        "l'indicateur dit ou le brouillon est parti : " + nodes.sauvegarde.textContent);
  check(nodes.sauvegarde.className === "", "discret tant que tout va bien");

  // --- LA BANDE DU LABORATOIRE ----------------------------------------------
  // La navigation qu'on fait vingt fois par seance -- passer de l'ex.2 a l'ex.3
  // du meme labo -- passait par un menu global qui couvre l'ecran, pour une
  // cible situee a un cran.
  await choisir("TP 2", "tp2-ex0");
  await sleep();
  const puces = () => nodes.bandelabo.children;
  check(nodes.bandelabo.hidden === false, "un labo à plusieurs exercices a sa bande");
  check(puces().length > 1, "avec une puce par exercice ouvert du labo");
  const ici = puces().find(p => p.getAttribute("aria-current") === "true");
  check(!!ici, "l'exercice courant est marqué par aria-current, pas par la seule couleur");
  // L'ETIQUETTE EST COURTE : `short` porte deja le titre qualifie (« TP2 : ex.3
  // loi d'Ohm »), et onze puces de trente caracteres remplissent trois lignes.
  // `textContent` DIRECT : dans ce faux DOM, `append` n'agrege pas le texte
  // des enfants -- c'est donc l'etiquette seule, et c'est ce qu'on veut ici.
  check(/^ex\.\d+/.test(ici.textContent),
        "l'étiquette est courte : " + ici.textContent);
  const nomComplet = global.ctester.catalogue()
    .find(t => t.id === global.ctester.exerciceChoisi()).short;
  check((ici.getAttribute("title") || "").indexOf(nomComplet) === 0,
        "le nom entier reste au survol : " + ici.getAttribute("title"));

  // UN CLIC Y CHANGE D'EXERCICE, sans passer par le menu.
  const ailleurs = puces().find(p => p.getAttribute("aria-current") !== "true");
  ailleurs.listeners.click();
  await sleep(); await sleep();
  check(global.ctester.exerciceChoisi() !== "tp2-ex0",
        "un clic sur la bande change d'exercice : " + global.ctester.exerciceChoisi());

  // LE STATUT, LÀ OÙ ON CHOISIT.
  global.ctester.poserStatuts({ "tp2-ex0": "solved" });
  // `reussi`, NO LONGER `valide`: the redesign gives the strip's items the
  // tile vocabulary shared with "Mes progres" (five states, five borders).
  // The contract itself has not moved -- the mark AND the word.
  const marquee = puces().find(p => /reussi/.test(p.className));
  check(!!marquee, "un exercice validé porte sa marque dans la bande");
  check(/réussi/.test(profond(marquee)),
        "et le MOT, pas seulement la coche : " + profond(marquee).trim());
  const ligneMenu = lignesDe("TP 2").find(l => /réussi/.test(libelle(l)));
  check(!!ligneMenu, "et le menu du catalogue le montre aussi");
  global.ctester.poserStatuts({});

  // LE CAS QUI COMPTE VRAIMENT. Afficher « enregistré » ici ferait perdre son
  // travail à quelqu'un qui nous a crus.
  storageBroken = true;
  nodes.code.value = "int main(void){ return 1; }";
  nodes.code.listeners.input();
  fireLastTimer();
  check(/NON enregistré/.test(nodes.sauvegarde.textContent),
        "un stockage qui refuse d'écrire se dit : " + nodes.sauvegarde.textContent);
  check(nodes.sauvegarde.className === "rate", "et se voit, en rouge");
  check(JSON.parse(storage["ctester.drafts"])["tp2-ex0"]["submission.c"]
        === "int main(void){ return 0; }",
        "le stockage garde alors la dernière version réellement écrite");
  storageBroken = false;

  // --- UN FICHIER IMPORTÉ EST DU TRAVAIL, ET IL SE PERDAIT --------------------
  // `saveDraft` ne partait que sur l'evenement `input`, et `input` NE SE
  // DECLENCHE PAS quand un script ecrit dans un <textarea> : le fichier importe
  // n'existait que dans le DOM. Un rechargement l'emportait sans un mot. C'est
  // la perte de code la plus facile a provoquer de toute la page.
  await choisir("TP 2", "tp2-ex0");
  nodes.file.files = [{ name: "submission.c", text: async () => "int main(void){ return 42; }" }];
  await nodes.file.listeners.change({ target: nodes.file });
  await sleep();
  check(nodes.code.value === "int main(void){ return 42; }",
        "le fichier importé arrive bien dans l'éditeur");
  const apresImport = JSON.parse(storage["ctester.drafts"] || "{}");
  check(apresImport["tp2-ex0"]
        && apresImport["tp2-ex0"]["submission.c"] === "int main(void){ return 42; }",
        "et il est ENREGISTRÉ tout de suite, sans attendre une frappe");

  // L'ONGLET VISÉ EST CELUI QUI PORTE LE NOM DU FICHIER. Importer `calendrier.c`
  // par-dessus `calendrier.h` parce que c'est l'onglet ouvert est un ecrasement
  // silencieux, au moment ou l'etudiant regarde ailleurs.
  await choisir("TP 6", "tp7-ex1");
  await sleep();
  if (nodes.tabs.children.length > 1) {
    const noms = nodes.tabs.children.map(o => o.dataset.name);
    const autre = noms[1];
    nodes.tabs.children[0].listeners.click();
    nodes.file.files = [{ name: autre, text: async () => "/* contenu du second */" }];
    await nodes.file.listeners.change({ target: nodes.file });
    await sleep();
    const ecrits = JSON.parse(storage["ctester.drafts"] || "{}")["tp7-ex1"] || {};
    check(ecrits[autre] === "/* contenu du second */",
          "l'import atterrit dans l'onglet qui porte son nom : " + autre);
    check(ecrits[noms[0]] !== "/* contenu du second */",
          "et n'écrase pas l'onglet qui était simplement ouvert");
  }


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

  // LE BROUILLON DU QUIZ : même magasin que l'éditeur, sinon changer de TP
  // efface 40 réponses en silence.
  nodes.quiz.listeners.input();
  fireLastTimer();
  check(JSON.parse(storage["ctester.drafts"]).tp1.q3 === "0x17",
        "les réponses saisies partent au brouillon");

  SUBMIT_RESPONSE = { ok: true, status: 200, json: async () => ({ id: "b".repeat(32) }) };
  calls.length = 0;
  await nodes.go.listeners.click();
  await sleep(); await sleep();
  const quizPost = calls.find(c => c.url.split("?")[0] === "submit");
  check(!!quizPost, "le fetch part aussi en mode quiz");
  if (quizPost) {
    const sent = JSON.parse(quizPost.opts.body);
    check(sent.exercise_id === "tp1", "le quiz est soumis sous son identifiant d'exercice");
    // LE POINT DE LA PAGINATION : masquer une page ne doit pas perdre ses
    // réponses. La soumission ramasse les trois champs, pas la page visible.
    check(sent.answers.q1 === "00010111" && sent.answers.q3 === "0x17",
          "les réponses des DEUX pages sont transmises");
    check(!("code" in sent), "pas de code sur un TP de quiz");
  }

  // --- « Tester l'exercice » : meme soumission, verdict restreint a la page ---
  // Le juge corrige toujours les trois questions -- c'est lui qui a le corrige,
  // et « valide » se derive de ce verdict complet. Seule la LECTURE se
  // restreint a l'exercice affiche, sans quoi un exercice juste s'annoncerait
  // « 1 / 40 » sous une page de rouge portant sur ce qu'on n'a pas encore vu.
  const tousLesNoeuds = (n) => n.children.flatMap(k => [k, ...tousLesNoeuds(k)]);
  const texteQuiz = (n) => (n.textContent || "") + " "
                         + n.children.map(texteQuiz).join(" ");
  check(nodes.goex.hidden === false, "le bouton par exercice n'existe qu'en quiz");
  POLL_RESPONSE = { state: "done", status: "ok", kind: "quiz", passed: 1, total: 3,
    wrong: [{ id: "q1", label: "23", given: "10111", hint: "l'énoncé demande 8 bits" },
            { id: "q2", label: "167", given: "", hint: "non répondu" }] };
  SUBMIT_RESPONSE = { ok: true, status: 200,
                      json: async () => ({ id: "e".repeat(32) }) };
  await nodes.goex.listeners.click();      // page 2 : Exercice 2, la seule juste
  await sleep(); await sleep(); await sleep();
  check(/1 \/ 1/.test(texteQuiz(nodes.out)) && nodes.out.className === "ok",
        "l'exercice affiche est note seul : " + texteQuiz(nodes.out).slice(0, 48));

  nodes.qprev.listeners.click();
  await nodes.goex.listeners.click();
  await sleep(); await sleep(); await sleep();
  const vuExercice = texteQuiz(nodes.out);
  check(/0 \/ 2/.test(vuExercice) && /Exercice 1/.test(vuExercice),
        "l'exercice precedent aussi : " + vuExercice.slice(0, 48));
  check(!/hexadécimal/.test(vuExercice),
        "et aucune question d'un autre exercice n'est listee");
  const neutres = tousLesNoeuds(nodes.out).filter(n => n.className === "rien");
  check(neutres.length === 1 && /167/.test(neutres[0].textContent),
        "seule la question non repondue passe en neutre, pas la reponse fausse");

  // ALLER-RETOUR COMPLET : on quitte le quiz, on y revient, les reponses sont
  // la. C'est tout ce que le brouillon promet.
  await choisir("TP 2", "tp2-ex0");
  await choisir("TP 1");
  await attendre();
  const revenus = nodes.quiz.querySelectorAll();
  check(revenus.length === 3 && revenus[0].value === "00010111"
        && revenus[2].value === "0x17",
        "revenir sur le quiz retrouve les reponses saisies");

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
    nodes.code.value = codeUnique();
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
  check(/Les nombres que le juge y a lus :\s*1, 234/.test(rate),
        "les nombres que le juge a lus sont montres");
  // LE CONTRAT DE CORRECTION, ECRIT. Le juge accepte n'importe quel texte
  // autour des valeurs attendues, et personne ne le disait a l'etudiant : il
  // passait du temps a deviner un format qui n'a jamais ete impose.
  check(/le texte autour est libre/i.test(rate),
        "et la regle de comparaison est dite, sans reveler la valeur attendue");
  check(!/valeur attendue est|attendu : /i.test(rate),
        "sans jamais donner la valeur attendue elle-meme");
  // LES ENTREES SONT DES VALEURS SUCCESSIVES, pas un bloc avec des \\n : « stdin »
  // ne veut rien dire pour quelqu'un qui apprend scanf ce mois-ci.
  check(/reçoit :\s*5/.test(rate),
        "les entrees sont presentees comme ce que le programme recoit : " + rate.slice(0, 70));
  check(/mise au point/.test(rate), "la sortie d'erreur du programme aussi");

  const quiz = await verdictAffiche({ status: "ok", kind: "quiz", passed: 0, total: 1,
                       wrong: [{ id: "q1", label: "23", given: "10111",
                                 hint: "l'enonce demande 8 bits" }] });
  check(/tu as répondu « 10111 »/.test(quiz), "le quiz rappelle la reponse saisie");

  // --- LES TROIS ÉTAPES, ET SURTOUT CELLE QUI N'A PAS ÉTÉ ATTEINTE ---------
  // Un débutant ne distingue pas compilation, exécution et logique -- c'est
  // ecrit dans le persona. Le serveur, lui, sait toujours laquelle a casse, et
  // la page jetait cette information : tout arrivait comme une seule ligne
  // rouge. Ce qui est eprouve ici, c'est que chaque etat NOMME son etape, dit
  // ce qui n'a PAS tourne, et finit par une action.
  const compile = await verdictAffiche({ status: "compile_error",
                    message: "Ton fichier ne compile pas.",
                    gcc: "sub.c:4:12: error: expected ';'" });
  check(/Compilation.*échouée/s.test(compile),
        "une erreur de compilation nomme l'etape qui a casse");
  check(/Exécution.*pas atteinte/s.test(compile),
        "et dit que le programme n'a PAS tourne : " + compile.slice(0, 60));
  check(/expected/.test(compile), "la sortie du compilateur reste montree");

  // LA PREMIERE ERREUR, PAS LA DERNIERE. En C un `;` oublie en produit six,
  // dont cinq n'existent pas -- et ce qu'un debutant lit, c'est le BAS de la
  // sortie, donc la plus derivee, celle qui ne correspond a rien dans son code.
  const cascade = await verdictAffiche({ status: "compile_error",
    message: "Ton fichier ne compile pas.",
    gcc: ["sub.c:4:12: error: expected ';' before '}' token",
          "    4 |     int x = 1",
          "      |            ^",
          "sub.c:9:3: error: 'x' undeclared here",
          "sub.c:12:1: error: expected declaration or statement at end of input"].join("\n") });
  const isole = nodes.out.children.find(c => c.className === "gcc");
  check(!!isole, "la sortie du compilateur est mise en forme, pas jetee brute");
  const enTete = isole && isole.children[0];
  check(enTete && /expected ';'/.test(enTete.textContent),
        "la PREMIERE erreur est isolee : " + (enTete ? enTete.textContent.split("\n")[0] : ""));
  check(enTete && !/undeclared/.test(enTete.textContent),
        "et les erreurs derivees n'y sont pas");
  check(enTete && /\^/.test(enTete.textContent),
        "l'extrait de source et le curseur ^ suivent, ils montrent l'endroit");
  check(/Voir toute la sortie/.test(cascade) && /undeclared/.test(cascade),
        "mais RIEN n'est cache : le reste est replie, pas supprime");
  check(/PREMIÈRE erreur/.test(compile),
        "et l'action suivante vise la premiere erreur, pas la derniere");

  const lien = await verdictAffiche({ status: "link_error",
                  message: "Ton code compile, mais l'édition de liens a échoué." });
  check(/ne s'assemble pas avec les tests/.test(lien),
        "l'echec d'assemblage a son propre titre, court");
  check(/édition de liens/.test(lien),
        "et l'explication du serveur est reprise telle quelle, en corps de texte");
  // L'ACTION AJOUTE, ELLE NE REPETE PAS : le message du serveur dit deja QUOI
  // verifier, l'action dit COMMENT s'y prendre.
  check(/caractère par caractère/.test(lien),
        "et l'action suivante dit comment s'y prendre, pas ce que le serveur a deja dit");

  const boucle = await verdictAffiche({ status: "timeout",
                    message: "Le programme a été interrompu." });
  check(/Compilation.*réussie/s.test(boucle),
        "un timeout dit que la compilation, elle, a REUSSI");
  check(/Exécution.*échouée/s.test(boucle), "et que c'est l'execution qui a casse");
  check(/ne s'est pas arrêté/.test(boucle), "en langage d'etudiant, pas de systeme");

  const memoire = await verdictAffiche({ status: "memory_error", message: "Débordement." });
  check(/Exécution.*échouée/s.test(memoire) && /Tests.*pas atteints/s.test(memoire),
        "un debordement memoire n'a pas atteint les tests");

  const inclus = await verdictAffiche({ status: "forbidden_include",
                    message: "unistd.h n'est pas autorisé." });
  check(/Compilation.*échouée/s.test(inclus) && /Retire cette ligne/.test(inclus),
        "un include interdit est refuse avant tout, et dit quoi faire");

  // UNE PANNE DU JUGE N'EST PAS UN VERDICT. `error` couvre deux choses tres
  // differentes cote serveur, et celle-ci ne parle pas du code de l'etudiant :
  // elle n'a rien a faire dans l'emplacement du verdict.
  nodes.systeme.textContent = "";
  const interne = await verdictAffiche({ status: "error",
                    message: "Erreur interne du juge. Réessaie." });
  check(!/Erreur interne/.test(interne),
        "une panne du juge ne s'affiche pas comme un verdict : " + interne.slice(0, 50));
  check(/Erreur interne/.test(nodes.systeme.textContent),
        "elle part dans le bandeau du service, avec ce qui n'est pas perdu");

  // --- UNE RÉUSSITE MÈNE QUELQUE PART ---------------------------------------
  // Le moment ou l'etudiant est le plus disponible etait precisement celui ou
  // la page ne lui proposait rien.
  POLL_RESPONSE = { state: "done", status: "ok", kind: "io", passed: 2, total: 2, cases: [] };
  SUBMIT_RESPONSE = { ok: true, status: 200, json: async () => ({ id: "e".repeat(32) }) };
  await choisir("TP 2", "tp2-ex0");
  nodes.code.value = codeUnique();
  await nodes.go.listeners.click();
  await sleep(); await sleep(); await sleep();
  const apres = nodes.out.children.find(c => c.className === "suite");
  check(!!apres, "une reussite complete propose une action suivante");
  const bouton = apres && apres.children.find(c => /Ouvrir/.test(c.textContent || ""));
  check(!!bouton,
        "et c'est un BOUTON, pas une phrase : " + (apres ? afficheTout(apres) : ""));
  if (bouton) {
    bouton.listeners.click();
    await sleep(); await sleep();
    check(nodes.excourant.textContent !== "tp2-ex0",
          "qui ouvre vraiment l'exercice suivant : " + nodes.excourant.textContent);
  }

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
  // TOUT CE FICHIER tourne dans cet état : toutes les vérifications ci-dessus
  // sont donc, littéralement, la preuve de non-régression du parcours anonyme
  // sur un déploiement où la connexion existe.
  check(nodes.connexion.hidden === false, "« Se connecter » est proposé");
  check(nodes.mesprogres.hidden === true && nodes.deconnexion.hidden === true &&
        nodes.oublier.hidden === true && nodes.discussions.hidden === true,
        "mais rien de ce qui suppose un compte n'apparaît");
  // Le harnais ne lit pas les attributs du HTML : ce qui prouve que la vue des
  // progres est restee fermee, c'est qu'elle n'a jamais ete construite.
  check(!nodes.vueprogres || !nodes.vueprogres.children.length,
        "et la vue des progrès n'est même pas construite");

  // LE POINT QUI COMPTE : pas un seul en-tête d'autorisation n'est parti, et
  // aucune écriture d'état non plus. Un anonyme ne parle jamais à la base.
  const entetes = calls.filter(c => c.opts && c.opts.headers &&
                                    c.opts.headers.Authorization);
  check(entetes.length === 0, "aucune requête ne porte de jeton");
  check(!calls.some(c => c.url === "etats" || c.url === "etat" ||
                         c.url === "pratique" || c.url === "progres" ||
                         String(c.url).startsWith("brouillon") ||
                         String(c.url).startsWith("forum")),
        "et rien n'est écrit ni lu côté compte, forum compris");

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
  check(charges.filter((n) => n.startsWith("compte.js?")).length === 2,
        "un second essai redemande vraiment le fichier");
  chargementCasse = false;

  // --- LE PARCOURS CONNECTE ---
  // Tout ce qui precede eprouve l'anonyme, qui reste le parcours par defaut.
  // Sans ce bloc, `ctester.token` a pu rester fige a null pendant toute une
  // visite sans qu'aucun test ne bronche : les etats et la pratique tombaient
  // en silence, et « Mes exercices » annoncait « a faire » sur un exercice
  // reussi. C'est arrive.
  // TROIS CAS, DANS CET ORDRE : les deux echecs d'abord, parce que la
  // decouverte OIDC est memoisee des qu'elle a reussi une fois et qu'on ne
  // pourrait plus la faire echouer ensuite.
  //
  // UN CLIC QUI NE FAIT RIEN ET NE DIT RIEN est la pire des issues : c'est ce
  // qu'un `startSignIn()` lance sans `await` produisait quand il levait.
  const cliquerConnexion = async () => {
    nodes.connexion.listeners.click();
    await nodes.consentok.listeners.click();
    await attendre();
  };

  DECOUVERTE_CASSEE = true;
  await cliquerConnexion();
  check(!!global.ctester.compte, "accepter le consentement charge compte.js");
  check(/connexion n'a pas pu démarrer/.test(shown()),
        "un fournisseur injoignable le dit : " + shown());
  check(redirections.length === 0, "et n'envoie evidemment personne nulle part");
  DECOUVERTE_CASSEE = false;

  // LA CONFIG ABSENTE. compte.js peut etre evalue avant que oidc.json soit
  // revenu -- ou n'etre jamais revenu, un bloqueur de publicite suffit. Lue au
  // chargement du module, elle restait `null` pour toute la visite et le bouton
  // levait « reading 'issuer' of null » dans une promesse que personne ne
  // lisait. C'est arrive.
  const vraieConfig = global.ctester.oidc;
  global.ctester.oidc = () => null;
  await cliquerConnexion();
  check(/configuration de connexion n'est pas disponible/.test(shown()),
        "sans configuration, la connexion le dit clairement : " + shown());
  check(redirections.length === 0, "et n'envoie toujours personne nulle part");

  // ET ELLE REPART DES QUE LA CONFIG EST LA : la lecture se fait a l'appel, pas
  // au chargement du module. C'est tout le correctif.
  global.ctester.oidc = vraieConfig;
  nodes.connexion.listeners.click();
  await nodes.consentok.listeners.click();
  // Le defi PKCE passe par crypto.subtle : une vraie operation de la
  // plateforme, pas une microtache. Elle demande une poignee de tours de
  // boucle, d'ou l'attente bornee -- qui sort des qu'elle a rendu.
  for (let n = 0; n < 60 && !redirections.length; n++) await attendre();
  check(redirections.length === 1,
        "une config revenue entre-temps suffit a faire repartir la connexion");
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

  // --- LE THEME SUIT LE COMPTE, PAS L'APPAREIL -----------------------------
  // C'est la raison d'etre de la route : le labo puis le portable, le meme
  // ecran. L'appareil est en sombre, le compte a choisi clair -- c'est le
  // compte qui gagne au demarrage de la session.
  document.documentElement.dataset.theme = "dark";
  storage["ctester.theme"] = "dark";
  THEME_SERVEUR = "light";
  await global.ctester.compte.chargerTheme();
  check(document.documentElement.dataset.theme === "light",
        "le theme du compte est applique en ouvrant la session");
  check(storage["ctester.theme"] === "light",
        "et recopie localement : la PROCHAINE visite part du bon theme avant "
        + "le premier rendu, ce que seul le stockage local peut faire");

  // UN CLIC LE PUBLIE. Sans ca le reglage resterait sur cet appareil et la
  // route ne servirait a rien.
  calls.length = 0;
  nodes.theme.listeners.click();
  await attendre();
  const envoiTheme = calls.find(c => c.url === "preferences");
  check(!!envoiTheme && envoiTheme.opts.method === "PUT",
        "changer de theme connecte l'ecrit sur le compte");
  check(envoiTheme && envoiTheme.opts.headers.Authorization === "Bearer " + JETON,
        "avec le jeton, comme toute ecriture de compte");
  check(THEME_SERVEUR === "dark",
        "et c'est bien le theme choisi qui arrive au serveur : " + THEME_SERVEUR);

  // UN COMPTE SANS CHOIX N'EST PAS UN COMPTE EN SOMBRE. Rien n'est enregistre :
  // on garde ce que l'appareil affiche, et on le lui envoie pour qu'il en ait
  // un. Ecraser par un defaut ferait sauter le reglage de quelqu'un chaque
  // fois que la base est neuve.
  THEME_SERVEUR = "";
  document.documentElement.dataset.theme = "light";
  await global.ctester.compte.chargerTheme();
  check(document.documentElement.dataset.theme === "light",
        "un compte sans theme enregistre laisse l'appareil decider");
  check(THEME_SERVEUR === "light",
        "et prend son theme courant comme premier choix du compte");

  calls.length = 0;
  await global.ctester.compte.loadStates();
  await global.ctester.compte.loadPractice();
  const portees = calls.filter(c => c.url === "etats" || c.url === "pratique");
  check(portees.length === 2 && portees.every(
          c => c.opts.headers.Authorization === "Bearer " + JETON),
        "les projections privees partent avec le jeton");

  // Le texte d'une ligne est reparti sur plusieurs niveaux, d'ou la descente.
  const texteDe = (n) => (n.children.length
    ? n.children.map(texteDe).join(" ") : n.textContent || "");

  // --- « MES PROGRÈS » : LA VUE PRIVÉE -------------------------------------
  // Tout ce qui suit n'existe QUE connecté. Le bloc anonyme plus haut prouve
  // l'inverse : ni fichier, ni requête, ni en-tête.
  await choisir("TP 2", "tp2-ex0");
  nodes.code.value = "// le travail en cours";
  check(nodes.mesprogres.hidden === false,
        "« Mes progrès » apparaît une fois connecté");
  check(!charges.some(n => n.startsWith("progres.js?")),
        "mais son fichier n'est toujours pas descendu");

  calls.length = 0;
  await nodes.mesprogres.listeners.click();
  await attendre();
  check(charges.some(n => n.startsWith("progres.js?")),
        "le clic va le chercher, comme compte.js");
  const appelProgres = calls.find(c => c.url === "progres");
  check(appelProgres &&
        appelProgres.opts.headers.Authorization === "Bearer " + JETON,
        "et la projection privée part avec le jeton, jamais sans");
  check(nodes.travail.hidden === true && nodes.vueprogres.hidden === false,
        "la vue remplace l'exercice");
  check(nodes.mesprogres.textContent === "Retour à l'exercice",
        "le bouton dit comment revenir");
  check(focusé === "progrestitre",
        "le focus suit l'écran : sans ça, la tabulation repart du haut et un "
        + "lecteur d'écran n'annonce rien");

  // "MES EXERCICES" MERGED INTO "MES PROGRES", then the flat list became A
  // GRID OF TILES PER LAB (redesign 1b): ninety sentences where the eye found
  // no landmark became one row per lab. WHAT IS EXERCISED HERE HAS NOT
  // CHANGED: a solved exercise says so, the others stay "to do", and the
  // ATTEMPT COUNT survives -- it only moved into the tile's title, the one
  // place a tile can keep what it does not draw.
  const tiles = tousLesNoeuds(nodes.vueprogres)
    .filter((n) => /\btile\b/.test(n.className || ""));
  check(tiles.length >= 4, "the grid places one tile per exercise: " + tiles.length);
  const titleOf = (t) => t.getAttribute("title") || "";
  check(tiles.some((t) => /reussi/.test(t.className) && /réussi/.test(titleOf(t))),
        "a solved exercise says so, instead of \"to do\": "
        + tiles.map(titleOf).join(" // "));
  // TWO SOURCES SAY "SOLVED", and either is enough: `/etats` carries
  // tp2-ex0, `/pratique` carries a success on tp2-ex3. The flat list already
  // read both, the grid must keep doing so.
  const practiced = tiles.find((t) => /3 tentatives/.test(titleOf(t)));
  check(!!practiced, "and the attempt count was not lost along the way: "
        + tiles.map(titleOf).join(" // "));
  check(!!practiced && /reussi/.test(practiced.className),
        "a success seen via `/pratique` counts like the others: "
        + (practiced && practiced.className));
  check(tiles.some((t) => /à faire/.test(t.getAttribute("title") || "")),
        "the others stay to do");
  // THE COUNT PER LAB, which existed nowhere before: one had to read ninety
  // rows to know where a lab stood.
  check(/1 sur \d+ réussi/.test(texteDe(nodes.vueprogres)),
        "and every lab says where it stands");


  const vu = texteDe(nodes.vueprogres);
  // L'ORDRE EST LE MESSAGE. Ce qui reste à faire d'abord, le compteur ensuite :
  // l'inverse ferait d'un site d'exercices un site de points.
  check(vu.indexOf("Action suivante") >= 0 &&
        vu.indexOf("Action suivante") < vu.indexOf("Niveau et XP"),
        "l'action suivante vient AVANT le niveau et l'XP");
  check(/2 exercices pratiqués sur 4 publiés, dont 1 réussi/.test(vu),
        "ce qui est pratiqué est écrit en toutes lettres");
  check(/2 exercices pratiqués sur 2, dont 1 réussi/.test(vu),
        "et chaque compétence porte ses valeurs, pas seulement une barre");
  check(/Niveau 2 — 45 XP/.test(vu) && /Encore 35 XP avant le niveau 3/.test(vu),
        "le niveau et le solde viennent du serveur : " + vu.slice(0, 40));
  check(/ne sont ni une note ni une maîtrise vérifiée/.test(vu),
        "l'XP dit ce qu'il n'est pas, à l'écran");
  check(/Ce n'est pas une maîtrise vérifiée/.test(vu),
        "et « pratiquée » ne se présente jamais comme une maîtrise");

  // LA MAÎTRISE EST UNE SECTION DE PLUS, pas une requalification de la
  // pratique : les deux doivent coexister, et la neuve passer devant.
  check(vu.indexOf("Maîtrise vérifiée") >= 0 &&
        vu.indexOf("Maîtrise vérifiée") < vu.indexOf("Ce que tu as pratiqué"),
        "« Maîtrise vérifiée » vient avant « Ce que tu as pratiqué »");
  check(/En progression/.test(vu) && /1 vérification réussie sur 2, 1 tentée/.test(vu),
        "la bande arrive du serveur, avec son compte en toutes lettres : " + vu);
  // LA LÉGENDE EXPLIQUE LES QUATRE MOTS. Sans elle, « à consolider » se lit
  // comme un reproche plutôt que comme une indication d'où revenir.
  check(/Pas encore vérifié/.test(vu) && /Reviens pratiquer/.test(vu),
        "et la légende des bandes est affichée, pas seulement celle utilisée");
  check(/ne rapporte aucun XP/.test(vu) && /pas une note/.test(vu),
        "la vue dit ce qu'une vérification n'est pas, comme l'XP le fait");
  check(/Premier exercice réussi/.test(vu) &&
        /fait passer tous les tests/.test(vu) && /obtenu le 2026-09-01/.test(vu),
        "un succès porte titre, description ET date -- pas une couleur seule");
  check(/continue avec « TP2 : ex.3 loi d'Ohm »/.test(vu),
        "la recommandation nomme l'exercice et la compétence : " + vu.slice(0, 60));

  // AUCUNE INJECTION. Les identifiants de compétence viennent du dépôt de
  // tests ; s'ils passaient par innerHTML, une balise s'exécuterait dans la
  // page de l'étudiant. Même règle que la coloration syntaxique plus haut.
  check(nodes.vueprogres.innerHTML === "",
        "rien n'est posé par innerHTML : tout passe par textContent");
  check(vu.includes("<img src=x onerror=alert(1)>"),
        "et une donnée hostile s'affiche comme du texte, pas comme une balise");

  // REVENIR À L'EXERCICE SANS RIEN PERDRE. Le brouillon est sauvé, mais le
  // texte à l'écran ne doit pas non plus repartir de zéro : on n'a fait que
  // changer d'écran.
  await nodes.mesprogres.listeners.click();
  await attendre();
  check(nodes.travail.hidden === false && nodes.vueprogres.hidden === true,
        "le même bouton ramène à l'exercice");
  check(nodes.code.value === "// le travail en cours",
        "et le travail en cours est intact : " + nodes.code.value);

  // La recommandation est un VRAI bouton, donc atteignable au clavier.
  await nodes.mesprogres.listeners.click();
  await attendre();
  const ouvrir = tousLesNoeuds(nodes.vueprogres)
    .find(n => /^Ouvrir /.test(n.textContent || ""));
  check(!!ouvrir && ouvrir.id === "<button>",
        "la recommandation est un bouton, pas un lien décoratif");
  ouvrir.listeners.click();
  await attendre();
  check(global.ctester.exerciceChoisi() === "tp2-ex3"
        && nodes.vueprogres.hidden === true,
        "il ouvre l'exercice recommandé et referme la vue");

  // --- LE MÊME CODE NE REPART PAS AU JUGE ----------------------------------
  // Une place de file, un cooldown et une attente pour un verdict déjà à
  // l'écran. La page réaffiche au lieu d'envoyer -- et elle n'affirme rien au
  // serveur en le faisant, elle décide seulement de ne pas le déranger.
  POLL_RESPONSE = { state: "done", status: "ok", kind: "io",
                    passed: 2, total: 2, cases: [] };
  SUBMIT_RESPONSE = { ok: true, status: 200,
                      json: async () => ({ id: "e".repeat(32) }) };
  const memeCode = codeUnique();
  nodes.code.value = memeCode;
  await nodes.go.listeners.click();
  await attendre(); await attendre(); await attendre();
  check(/2 \/ 2/.test(texteQuiz(nodes.out)), "premier envoi : le verdict arrive");

  calls.length = 0;
  await nodes.go.listeners.click();
  await attendre();
  check(!calls.some(c => c.url.split("?")[0] === "submit"),
        "le même code ne reprend pas de place dans la file");
  check(/2 \/ 2/.test(texteQuiz(nodes.out)),
        "et son verdict reste à l'écran plutôt que de disparaître");
  check(/Même code/.test(shown()) && /Clique encore/.test(shown()),
        "la page dit pourquoi, et comment renvoyer quand même : " + shown());

  // L'ÉCHAPPATOIRE N'EST PAS OPTIONNELLE : un cas de test corrigé par le tick
  // de cinq minutes rend le verdict gardé faux, et la page ne peut pas
  // l'apprendre. Sans elle, c'est le bouton qui aurait l'air cassé.
  calls.length = 0;
  await nodes.go.listeners.click();
  await attendre(); await attendre();
  check(calls.some(c => c.url.split("?")[0] === "submit"),
        "un second clic renvoie quand même au juge");

  // ET CE QUE LE SERVEUR REFUSE DE GARDER, LA PAGE NE LE GARDE PAS NON PLUS.
  // `rejouer` couvre le timeout, la panne du juge, et l'exercice dont le
  // PROGRAMME est aléatoire -- que la page n'a aucun moyen de reconnaître.
  POLL_RESPONSE = { state: "done", status: "ok", kind: "io", rejouer: true,
                    passed: 1, total: 2, cases: [] };
  nodes.code.value = codeUnique();
  await nodes.go.listeners.click();
  await attendre(); await attendre(); await attendre();
  calls.length = 0;
  await nodes.go.listeners.click();
  await attendre(); await attendre();
  check(calls.some(c => c.url.split("?")[0] === "submit"),
        "un verdict marqué `rejouer` est toujours renvoyé au juge");

  // APRÈS UN VERDICT, la projection est redemandée AU SERVEUR. C'est lui qui
  // vient peut-être d'accorder l'XP d'une première réussite ; la page n'en
  // calcule aucune part, elle la relit.
  POLL_RESPONSE = { state: "done", status: "ok", kind: "io",
                    passed: 1, total: 1, cases: [] };
  SUBMIT_RESPONSE = { ok: true, status: 200,
                      json: async () => ({ id: "f".repeat(32) }) };
  nodes.code.value = codeUnique();
  calls.length = 0;
  await nodes.go.listeners.click();
  await attendre(); await attendre(); await attendre();
  check(calls.some(c => c.url === "progres"),
        "après un verdict, la projection privée est redemandée");
  check(/1 \/ 1/.test(texteQuiz(nodes.out)) && nodes.out.className === "ok",
        "sans rien changer à l'affichage du résultat : " + shown().slice(0, 30));

  // LA PROGRESSION INDISPONIBLE NE DOIT RIEN EMPORTER. Base en panne, API de
  // progression cassée : l'exercice, lui, reste utilisable. Et surtout, on
  // n'invente pas un solde à zéro -- ce serait annoncer que tout a disparu.
  PROGRES_CASSE = true;
  await nodes.mesprogres.listeners.click();   // ouvrir, sur une panne
  await attendre();
  const casse = texteDe(nodes.vueprogres);
  check(/ne sont pas disponibles/.test(casse),
        "une panne se dit clairement : " + casse.slice(0, 60));
  check(!/XP/.test(casse) && !/Niveau/.test(casse),
        "et aucun chiffre n'est inventé");
  await nodes.mesprogres.listeners.click();   // retour à l'exercice
  await attendre();
  check(nodes.travail.hidden === false,
        "et on revient à l'exercice comme si de rien n'était");
  calls.length = 0;
  nodes.code.value = codeUnique();
  await nodes.go.listeners.click();
  await attendre(); await attendre();
  check(calls.some(c => c.url.split("?")[0] === "submit"),
        "et l'exercice reste soumettable pendant ce temps-là");
  PROGRES_CASSE = false;

  // --- « DISCUSSIONS » : LE FORUM ------------------------------------------
  // Tout ce qui suit n'existe QUE connecté, et QUE sur un déploiement qui a des
  // modérateurs configurés. Le bloc anonyme plus haut prouve l'inverse : ni
  // fichier, ni requête, ni en-tête.
  await choisir("TP 2", "tp2-ex3");
  nodes.code.value = "// mon code en cours";
  check(nodes.discussions.hidden === false,
        "« Chat » apparaît une fois connecté");
  check(nodes.discussions.textContent === "Chat",
        "et il porte le mot que les étudiants connaissent, pas « Discussions »");
  check(!charges.some(n => n.startsWith("forum.js?")),
        "mais son fichier n'est toujours pas descendu");

  calls.length = 0;
  await nodes.discussions.listeners.click();
  await attendre(); await attendre();
  check(charges.some(n => n.startsWith("forum.js?")),
        "le clic va le chercher, comme compte.js et progres.js");
  check(charges.some(n => /marked-\d/.test(n)) &&
        charges.some(n => /purify-\d/.test(n)),
        "et les deux bibliothèques de rendu arrivent AVEC la vue, épinglées : "
        + charges.filter(n => /vendor/.test(n)).join(" "));
  const appelFil = calls.find(c => String(c.url).startsWith("forum?ex="));
  check(appelFil && appelFil.opts.headers.Authorization === "Bearer " + JETON,
        "le fil part avec le jeton, jamais sans");

  // --- LE DOCK : LE CHAT À CÔTÉ DU CODE, PAS À LA PLACE --------------------
  // C'EST LE CŒUR DE LA REFONTE, et le contrôle qui le tient. Le bouton de la
  // barre ouvrait un CINQUIÈME ÉCRAN qui remplaçait l'exercice : demander de
  // l'aide obligeait à quitter son code au moment précis où il faut le
  // regarder. Sans ce test, quelqu'un le remettra en vue plein écran « pour
  // que ce soit plus lisible ».
  check(nodes.travail.hidden === false && nodes.chatdock.hidden === false,
        "le chat s'ouvre À CÔTÉ de l'éditeur : l'exercice reste à l'écran");
  check(nodes.vueforum.hidden === true,
        "et ce n'est PAS la vue plein écran qui s'est ouverte");
  check(nodes.travail.className === "avecchat",
        "la grille passe à trois colonnes : l'éditeur se réduit, il n'est pas recouvert");

  const dansDock = (t) => tousLesNoeuds(nodes.chatdock)
    .find((x) => (x.textContent || "") === t);
  // LES DEUX CANAUX, ET SEULEMENT DEUX. L'encart « Où écrire » en offrait
  // trois, dont deux portaient le mot « chat » pour deux choses différentes.
  const listeCanaux = tousLesNoeuds(nodes.chatdock)
    .find((x) => x.className === "canaux");
  check(!!listeCanaux, "le dock porte une LISTE de canaux, pas trois boutons en vrac");
  const canaux = tousLesNoeuds(listeCanaux)
    .filter((x) => /^# /.test(x.textContent || ""));
  check(canaux.length === 2, "deux canaux, pas trois espaces à départager : "
        + canaux.map((c) => c.textContent).join(" "));
  check(canaux.some((c) => c.textContent === "# général"),
        "« # général », nommé comme dans Discord et Teams");
  check(canaux.some((c) => /ex\.3/.test(c.textContent)),
        "et le canal de l'exercice OUVERT, qu'on n'a pas eu à choisir : "
        + canaux.map((c) => c.textContent).join(" "));
  const actif = canaux.find((c) => c.getAttribute("aria-current") === "true");
  check(!!actif && /ex\.3/.test(actif.textContent),
        "le canal actif est dit à la machine aussi, pas seulement à l'œil");
  check(!tousLesNoeuds(nodes.chatdock)
          .some((x) => /Où écrire|Forum de l'exercice/.test(x.textContent || "")),
        "et le mot « forum » a disparu de l'écran de l'étudiant");

  // Fermer, rouvrir : l'état se retient, sinon on le rouvre vingt fois par
  // séance et on cesse de s'en servir.
  await nodes.discussions.listeners.click();
  await attendre();
  check(nodes.chatdock.hidden === true && nodes.travail.className === "",
        "le second clic referme le dock et rend sa colonne à l'éditeur");
  check(global.localStorage.getItem("ctester.chat.ouvert") !== "1",
        "et la fermeture est retenue");
  await nodes.discussions.listeners.click();
  await attendre(); await attendre();
  check(nodes.chatdock.hidden === false
        && global.localStorage.getItem("ctester.chat.ouvert") === "1",
        "rouvrir le retient aussi : au rechargement, le chat est encore là");

  // « EN GRAND » EST LA SEULE PORTE VERS LA VUE LARGE. Deux boutons dans la
  // barre pour deux tailles de la même chose, c'étaient deux mots à apprendre
  // pour une seule idée.
  const enGrand = dansDock("⤢");
  check(!!enGrand, "le dock porte le bouton « en grand »");
  await enGrand.listeners.click();
  await attendre(); await attendre();
  check(nodes.travail.hidden === true && nodes.vueforum.hidden === false &&
        nodes.vueprogres.hidden === true,
        "la vue remplace l'exercice, et elle est seule à l'écran");
  check(nodes.discussions.textContent === "Retour à l'exercice",
        "le bouton dit comment revenir");
  check(focusé === "forumtitre",
        "le focus suit l'écran : sinon la tabulation repart du haut");

  // LE CORPS D'UN MESSAGE N'EST PAS DU `textContent` : c'est le seul endroit du
  // client qui passe par `innerHTML`, et il reçoit la sortie de l'assainisseur.
  // Un lecteur du DOM en carton qui ne regarderait que `textContent` ne verrait
  // donc AUCUN message -- et déclarerait le fil vide sans broncher.
  const contenuDe = (n) => (n.textContent || "") + " " + (n.innerHTML || "")
                         + " " + n.children.map(contenuDe).join(" ");
  const vuDuForum = () => contenuDe(nodes.vueforum);

  const vuForum = vuDuForum();
  check(/Pas de solution complète/.test(vuForum) &&
        /Pas de capture d'écran/.test(vuForum) &&
        /Signale-la plutôt que d'y répondre/.test(vuForum),
        "la charte est dans la vue, en toutes lettres");
  check(/Modération humaine/.test(vuForum) && /rien n'est vérifié/.test(vuForum),
        "et la modération n'est jamais présentée comme automatique");
  // L'ANONYME EST MASQUÉ, PAS INDISTINCT. « Participant » pour tout le monde
  // rendait une conversation illisible -- on ne savait pas qui répondait à
  // qui. Le repli est maintenant l'alias, tiré d'un vocabulaire FERMÉ, donc
  // suivable sans être identifiant et sans rien à modérer.
  check(/j'ai la meme erreur/.test(vuForum) && /Rotor cuivré/.test(vuForum),
        "le fil montre le message d'un autre, signé de son nom masqué");
  check(!/\bParticipant\b/.test(vuForum),
        "et plus « Participant », qui ne distinguait personne de personne");
  check(/&lt;img src=x onerror=alert\(1\)&gt;/.test(vuForum),
        "dont le HTML est ÉCHAPPÉ à l'affichage, pas interprété");
  check(!/sub-/.test(vuForum), "et aucun identifiant de compte n'apparaît");

  // --- MON IDENTITÉ : un RÉGLAGE, dans le menu Compte et pas dans le fil ----
  check(nodes.identite.hidden === false,
        "« Mon identité » est offert dans le menu Compte, comme Discussions");
  check(!/MON IDENTITÉ|Nom affiché/.test(vuForum),
        "et le formulaire n'encombre pas la colonne où on vient lire le fil");
  check(/Compte . Mon identité/.test(vuForum),
        "mais la vue dit où le trouver, sinon personne ne le découvre");
  check(!forumEnvois.some((e) => e.url === "forum/profil"),
        "ouvrir les discussions n'écrit rien dans le profil");

  // Le noeud est cree a la demande par le faux DOM : on le demande comme la
  // page le ferait, pas via `nodes` qui ne connait que ce qui a deja servi.
  const panneau = document.getElementById("identitepanneau");
  check(panneau.hidden === true, "le panneau part fermé");
  await nodes.identite.listeners.click();
  await sleep(); await sleep(); await sleep();
  check(panneau.hidden === false,
        "le menu Compte l'ouvre, sans changer de vue");
  check(nodes.forumpseudo.value === "vveremme",
        "le nom de connexion PRÉ-REMPLIT le champ : " + nodes.forumpseudo.value);
  check(focusé === "forumpseudo", "et le focus part dedans : " + focusé);
  check(nodes.forumvoirnom.checked === false
        && nodes.forumvoirgroupe.checked === false,
        "rien n'est coché -- l'anonymat est l'état de départ, et le nom de "
        + "connexion de quelqu'un ne se publie pas tout seul");
  check(/Bob B/.test(vuForum) && /groupe 04/.test(vuForum),
        "un nom choisi par un autre s'affiche, avec son groupe sur deux chiffres");

  // --- LE NOM MASQUÉ DOIT ÊTRE ATTEIGNABLE ---------------------------------
  // C'EST LE CONTRÔLE QUI AURAIT ATTRAPÉ LE DÉFAUT. Le bloc était dessiné
  // sous `if (profil.alias)`, alors que la SEULE chose qui écrit un alias est
  // le bouton dedans : il était donc caché exactement pour les comptes qui
  // n'avaient pas de nom. Bénin tant que l'alias n'était qu'une décoration de
  // classement ; bloquant depuis qu'il est la façon dont on apparaît dans le
  // chat. Sans ce test, quelqu'un remettra la garde « pour ne pas afficher un
  // champ vide ».
  const contenuPanneau = contenuDe(panneau);
  check(/Mon nom masqué/.test(contenuPanneau),
        "le bloc du nom masqué est dessiné MÊME SANS alias : " + contenuPanneau.slice(0, 200));
  const tirer = tousLesNoeuds(panneau)
    .find((n) => /Tirer un nom|Un autre nom/.test(n.textContent || ""));
  check(!!tirer, "et son bouton est là, seul chemin pour en obtenir un");
  calls.length = 0;
  await tirer.listeners.click();
  await sleep(); await sleep(); await sleep();
  check(calls.some((c) => String(c.url) === "leaderboard/alias"),
        "le bouton tire bien un nom côté serveur");
  // `chargerProfil()` relit le profil, les équipes ET la liste : plusieurs
  // allers-retours avant que le panneau ne soit redessiné.
  await sleep(); await sleep(); await sleep(); await sleep(); await sleep();
  // ET L'APERÇU NE PROMET PAS « PARTICIPANT » : l'encart dit « voilà
  // exactement ce que les autres verront », donc il doit montrer le nom
  // masqué, pas un mot que personne ne lira.
  check(/Rotor cuivré/.test(contenuDe(panneau)),
        "l'aperçu montre le nom masqué : " + contenuDe(panneau).slice(-400));
  check(/y compris sur tes messages déjà publiés/.test(contenuDe(panneau)),
        "et le caractère rétroactif du changement est écrit avant le clic");

  // --- CHOISIR SON ÉQUIPE, DANS « Mon identité » ---------------------------
  // LES ÉQUIPES PRÉEXISTENT, NUMÉROTÉES PAR GROUPE, et on prend une place
  // libre -- le geste de Moodle, avec les MÊMES numéros. C'est ici parce que
  // le devoir ouvre en octobre et que les équipes se choisissent avant : un
  // écran qui n'existerait qu'une fois le devoir ouvert ferait choisir les
  // équipes le matin de la remise.
  //
  // PAS DE CACHE À VIDER : `ouvrirIdentite()` relit le profil, les équipes ET
  // la liste à chaque ouverture. Fermer puis rouvrir suffit à reposer la
  // question, et c'est ce qu'un étudiant fait quand il ne comprend pas.
  const rouvrir = async () => {
    await nodes.identite.listeners.click();   // ferme
    await nodes.identite.listeners.click();   // rouvre, et relit
    await sleep(); await sleep(); await sleep();
    return profond(panneau);
  };
  // UNE LIGNE D'ÉQUIPE SE RECONNAÎT À SA CLASSE, pas à son texte : `.on`
  // s'ajoute sur la sienne, et chercher par texte attraperait aussi le
  // paragraphe d'aide qui nomme les équipes.
  const ligneEquipe = (nom) => tousLesNoeuds(panneau).find(
    (n) => String(n.className || "").indexOf("equipeligne") === 0
           && (n.children || []).some((k) => k.textContent === nom));
  const boutonDe = (nom, mot) => ((ligneEquipe(nom) || {}).children || [])
    .find((k) => (k.textContent || "").indexOf(mot) === 0);

  const liste = profond(panneau);
  check(/Choisis ton équipe, la même que sur Moodle/.test(liste),
        "l'écran dit d'où vient la numérotation : " + liste);
  check(/Vous serez 3 à 4/.test(liste),
        "et la taille vient du DEVOIR, pas de l'application");
  check(/Équipe 1 1 \/ 4/.test(liste.replace(/\s+/g, " ")),
        "chaque équipe montre son remplissage, comme sur Moodle : "
        + liste.replace(/\s+/g, " ").slice(0, 200));
  check(/Équipe 6/.test(liste) && !/Équipe 7/.test(liste),
        "il y a exactement les `count` équipes du contenu : au-delà, elles "
        + "n'existent pas non plus dans Moodle");
  // LA LISTE NE DIT PAS QUI EST OÙ : « 3/4 » suffit à choisir, et publier les
  // compositions ferait de ce choix un tri social sur une page.
  check(!/Coéquipier/.test(liste) && !/sub-/.test(liste),
        "et elle ne nomme personne : " + liste);
  // UNE ÉQUIPE COMPLÈTE N'A PAS DE BOUTON : un bouton grisé invite à cliquer
  // pour voir, et la réponse est toujours non.
  check(!boutonDe("Équipe 2", "Rejoindre") && /complète/.test(liste),
        "l'équipe pleine se dit complète, sans bouton à cliquer pour rien");

  // 1. REJOINDRE : la place est prise, et la liste se met à jour du SERVEUR.
  await boutonDe("Équipe 3", "Rejoindre").listeners.click();
  await sleep(); await sleep(); await sleep();
  const rejointe = profond(panneau);
  check(/la tienne/.test(rejointe) && /Équipe 3/.test(rejointe),
        "l'équipe choisie est marquée : " + rejointe);
  check(/ouvre le/.test(rejointe),
        "et la date d'ouverture est là -- sans elle, une équipe sur un devoir "
        + "fermé n'a l'air de rien");
  check(equipeEnvois.some((e) => e.url === "team/join"
                                 && e.corps.number === 3),
        "la requête porte le NUMÉRO, pas une poignée : le serveur y ajoute le "
        + "groupe : " + JSON.stringify(equipeEnvois.slice(-1)));

  // 2. EN CHANGER, tant que le devoir est fermé.
  await boutonDe("Équipe 3", "Quitter").listeners.click();
  await sleep(); await sleep(); await sleep();
  check(!/la tienne/.test(profond(panneau)), "quitter libère la place");
  await boutonDe("Équipe 5", "Rejoindre").listeners.click();
  await sleep(); await sleep(); await sleep();
  check(/Équipe 5/.test(profond(panneau)) && /la tienne/.test(profond(panneau)),
        "et on en reprend une autre");

  // 3. L'OUVERTURE DU DEVOIR FIGE TOUT, et l'écran le dit plutôt que de
  //    laisser des boutons qui répondront non.
  DEVOIR_OUVERT = true;
  const figee = await rouvrir();
  check(/figée/.test(figee), "une fois le devoir ouvert, l'équipe est figée : "
        + figee);
  check(/vois avec ton enseignant/.test(figee),
        "et l'écran dit à qui parler si elle est fausse");
  check(!/Rejoindre/.test(figee),
        "plus aucun bouton pour changer : la liste n'est plus dessinée");
  DEVOIR_OUVERT = false;
  await rouvrir();

  // 4. LES DEUX AUTRES ÉTATS SE DISENT AUSSI. Le jour où l'API tournait
  //    encore sans `/team/mine`, ce panneau se taisait exactement comme s'il
  //    n'y avait pas d'équipe -- une page qui répond « tout va bien » à
  //    « suis-je bien inscrit ? ».
  EQUIPE_MUETTE = true;
  const enPanne = await rouvrir();
  check(/n'a pas pu être lue/.test(enPanne),
        "une lecture qui échoue ne se lit PAS « aucune équipe » : " + enPanne);
  check(/ce n'est pas toi, c'est le service/.test(enPanne),
        "et le dit dans ces termes-là");
  EQUIPE_MUETTE = false;
  await rouvrir();

  const dansPanneau = (texte) => tousLesNoeuds(panneau)
    .find((n) => n.textContent === texte);
  nodes.forumpseudo.value = "Léa";
  nodes.forumgroupe.value = "4";
  nodes.forumvoirnom.checked = true;
  await dansPanneau("Enregistrer").listeners.click();
  await sleep(); await sleep(); await sleep();
  const profilEnvoye = forumEnvois.find((e) => e.url === "forum/profil");
  check(profilEnvoye && profilEnvoye.corps.display_name === "Léa"
        && profilEnvoye.corps.group_number === "4"
        && profilEnvoye.corps.display_name_public === true
        && profilEnvoye.corps.group_number_public === false,
        "« Enregistrer » envoie le nom, le groupe et les DEUX visibilités "
        + "séparément : " + JSON.stringify(profilEnvoye && profilEnvoye.corps));
  check(nodes.forumpseudo.value === "Léa",
        "le panneau repart du profil enregistré, pas de la suggestion");
  check(/Identité enregistrée/.test(contenuDe(panneau)),
        "et le dit sur place, sans refermer sous le nez de qui vient d'écrire");

  await dansPanneau("Fermer").listeners.click();
  check(panneau.hidden === true, "« Fermer » referme le panneau");
  // ET LE FIL EST TOUJOURS LÀ : le réglage ne se paie pas d'un changement de
  // vue, ni d'un rechargement de ce qu'on était en train de lire.
  check(nodes.vueforum.hidden === false && /Bob B/.test(vuDuForum()),
        "le fil n'a pas bougé pendant tout ça");

  const signalerNom = tousLesNoeuds(nodes.vueforum)
    .find((n) => n.textContent === "Signaler le nom");
  check(!!signalerNom, "un nom affiché est signalable");
  await signalerNom.listeners.click();
  await sleep(); await sleep();
  const nomSignale = forumEnvois.find(
    (e) => e.url === "forum/signalement" && e.corps && e.corps.kind === "name");
  check(!!nomSignale && nomSignale.corps.id === "m-nomme",
        "signaler un NOM passe par la même route, avec la poignée du message");

  // LE POINT LE PLUS IMPORTANT DE TOUT CE FICHIER. Le texte d'un message est
  // écrit par un autre étudiant : c'est la donnée la moins digne de confiance
  // de la page, et la seule qu'on rende en HTML.
  const rendreForum = global.ctester.forum.rendreMarkdown;
  function passerAuRendu(source) {
    const cible = document.createElement("div");
    const fait = rendreForum(cible, source);
    return { fait: fait, html: cible.innerHTML, texte: cible.textContent };
  }
  {
    // D'ABORD : le rendu a-t-il VRAIMENT eu lieu ? Sans cette vérification,
    // toutes celles qui suivent passeraient sur le repli en texte brut, qui
    // n'assainit rien parce qu'il n'écrit pas de HTML. C'est exactement le
    // faux positif qui rassure.
    const bon = passerAuRendu("**gras** et *italique*");
    check(bon.fait === true && /<strong>gras<\/strong>/.test(bon.html),
          "le rendu Markdown a réellement lieu : " + bon.html);

    // L'AUDIT EST STRUCTUREL, PAS TEXTUEL, et c'est tout le sujet. Chercher la
    // chaîne « onerror » dans la sortie donne un faux positif dès qu'un message
    // PARLE de `onerror` -- ce qui, sur un forum de programmation, arrive tous
    // les jours. Ce qu'il faut vérifier est ce que le navigateur va CONSTRUIRE :
    // on reparse la sortie et on regarde les éléments et les attributs qui
    // existent réellement. D'où jsdom, encore.
    const BALISES_OK = ["p", "br", "strong", "em", "ul", "ol", "li",
                        "blockquote", "code", "a"];
    function auditer(html) {
      const corps = new JSDOM("<body>" + html + "</body>").window.document.body;
      const fautes = [];
      for (const el of corps.querySelectorAll("*")) {
        const nom = el.tagName.toLowerCase();
        if (BALISES_OK.indexOf(nom) < 0) fautes.push("<" + nom + ">");
        for (const attr of Array.from(el.attributes)) {
          if (attr.name !== "href" && attr.name !== "rel") {
            fautes.push(nom + "@" + attr.name);
          }
          if (attr.name === "href" && !/^https?:\/\//i.test(attr.value)) {
            fautes.push("href=" + attr.value.slice(0, 24));
          }
        }
      }
      return { fautes: fautes, texte: corps.textContent };
    }

    const charges = [
      // Les classiques, tels qu'ils arriveraient dans un message.
      "<script>alert(1)</script>",
      "<img src=x onerror=alert(1)>",
      "<svg onload=alert(1)><circle/></svg>",
      "<svg><animate onbegin=alert(1) attributeName=x dur=1s>",
      "<math><mtext><script>alert(1)</script></mtext></math>",
      "<iframe src=https://x.test></iframe>",
      "<a href=\"https://x.test\" target=\"_blank\" onclick=\"a()\">x</a>",
      "<form action=/x><input name=p></form>",
      "<div style=\"position:fixed\" class=\"c\" id=\"i\">x</div>",
      "<x-perso onclick=alert(1)>hop</x-perso>",
      "<base href=https://x.test>",
      "<style>body{display:none}</style>",
      // Les URI, y compris casse mélangée et espaces intercalés.
      "[lien](javascript:alert(1))",
      "[lien](JaVaScRiPt:alert(1))",
      "[lien](  javascript:alert(1))",
      "[lien](java\tscript:alert(1))",
      "[lien](data:text/html;base64,PHNjcmlwdD4=)",
      "[lien](vbscript:msgbox)",
      "![img](https://x.test/a.png)",
      "<!-- <script>alert(1)</script> -->",
      // LE HTML BRUT CACHÉ DANS DU MARKDOWN : dans une liste, une citation, un
      // titre de lien, du code en ligne. C'est là qu'un échappement posé au
      // mauvais endroit laisse passer.
      "- <script>alert(1)</script>",
      "> <img src=x onerror=alert(1)>",
      "[**a**](https://ok.test \"<script>x</script>\")",
      "`<script>alert(1)</script>`",
      "**<img src=x onerror=alert(1)>**",
      // Liens malformés et tentatives de sortie d'attribut.
      "[x](https://ok.test\" onmouseover=\"alert(1))",
      "[x](<https://ok.test onclick=alert(1)>)",
      "<a href=&#106;avascript:alert(1)>x</a>",
    ];
    const passees = charges.filter((source) => {
      const r = passerAuRendu(source);
      if (!r.fait) { console.log("NON RENDU : " + source); return true; }
      const audit = auditer(r.html);
      if (audit.fautes.length) {
        console.log("PASSE : " + source + " -> " + audit.fautes.join(", "));
        return true;
      }
      return false;
    });
    check(passees.length === 0,
          "aucune des " + charges.length + " charges hostiles ne produit un "
          + "élément ou un attribut hors allow-list"
          + (passees.length ? " -- " + passees.length + " PASSENT" : ""));

    // LA CHARGE RESTE LISIBLE, ÉCHAPPÉE PLUTÔT QUE SUPPRIMÉE : un message dont
    // la moitié s'évapore ferait croire à un bug plutôt qu'à une règle -- et
    // surtout, « rien ne s'affiche » et « rien ne s'exécute » ne sont pas la
    // même preuve : les deux contrôles ci-dessous vérifient la seconde en
    // montrant la première.
    const vuTexte = auditer(passerAuRendu("<img src=x onerror=alert(1)>").html);
    check(/<img src=x onerror=alert\(1\)>/.test(vuTexte.texte),
          "une balise hostile reste lisible EN TEXTE : " + vuTexte.texte);

    const echappe = passerAuRendu("regarde <script>alert(1)</script> ici");
    check(/&lt;script&gt;/.test(echappe.html),
          "le HTML brut est échappé, pas escamoté : " + echappe.html);

    // LES LIENS AUTORISES : http(s) seulement, rel pose, aucune cible nommee.
    const lien = passerAuRendu("voir [la doc](https://exemple.test/a)");
    check(/<a [^>]*href="https:\/\/exemple\.test\/a"/.test(lien.html),
          "un lien https est rendu : " + lien.html);
    check(/rel="noopener noreferrer"/.test(lien.html),
          "avec rel=\"noopener noreferrer\" : " + lien.html);
    check(!/target=/.test(lien.html), "et sans cible nommée");
    const relatif = passerAuRendu("[interne](/app.js)");
    check(!/href=/.test(relatif.html) && /interne/.test(relatif.html),
          "une URL non http(s) perd son href et reste du texte : " + relatif.html);

    // LE RENDU AUTORISE RESTE ACCESSIBLE : de vrais elements semantiques, que
    // lit un lecteur d'ecran -- pas des <span> maquilles.
    const riche = passerAuRendu("- un\n- deux\n\n> citation\n\n`x` et **gras**");
    check(/<ul>/.test(riche.html) && /<li>/.test(riche.html) &&
          /<blockquote>/.test(riche.html) && /<code>/.test(riche.html) &&
          /<strong>/.test(riche.html),
          "listes, citation, code et gras traversent l'allow-list : "
          + riche.html.slice(0, 70));
    check(!/style=|class=|id=/.test(riche.html),
          "et rien n'en ressort avec style, class ou id");
    // PAS DE BLOC DE CODE RENDU : `pre` n'est pas dans l'allow-list.
    const bloc = passerAuRendu("```\nint main(void){}\n```");
    check(!/<pre/.test(bloc.html) && /int main/.test(bloc.html),
          "un bloc clôturé ne devient pas un bloc de code : " + bloc.html);
  }

  // --- PUBLIER : LA CHARTE D'ABORD -----------------------------------------
  forumEnvois.length = 0;
  nodes.forumtexte.value = "Ma **boucle** ne s'arrête pas, une idée ?";
  nodes.forumtexte.listeners.input();
  // L'APERÇU passe par le MÊME `rendreMarkdown` que le fil : ce qu'on voit
  // avant d'envoyer est ce que les autres verront, assaini de la même façon.
  const apercu = tousLesNoeuds(nodes.vueforum)
    .find(n => /apercu/.test(n.className || ""));
  check(apercu && /<strong>boucle<\/strong>/.test(apercu.innerHTML || ""),
        "l'aperçu rend le Markdown pendant la frappe : "
        + (apercu ? apercu.innerHTML : "pas d'aperçu"));
  check(apercu && apercu.getAttribute("role") === "region"
        && !apercu.getAttribute("aria-live"),
        "sans être annoncé à chaque frappe : une région, pas une zone vive");
  const publier = tousLesNoeuds(nodes.vueforum)
    .find(n => n.textContent === "Publier");
  await publier.listeners.click();
  await attendre();
  check(nodes.charte.hidden === false,
        "la charte s'affiche AVANT la première publication de la session");
  check(forumEnvois.length === 0,
        "et rien n'est parti tant qu'elle n'est pas acceptée");
  const compris = tousLesNoeuds(nodes.charte)
    .find(n => /J'ai compris/.test(n.textContent || ""));
  await compris.listeners.click();
  await attendre(); await attendre(); await attendre();
  check(nodes.charte.hidden === true, "l'accepter la referme");
  const envoi = forumEnvois.find(e => e.url === "forum");
  // LE FIL PAR DÉFAUT EST LE CHAT DE L'EXERCICE, et la clé le dit. Ouvrir
  // « Discussions » pendant un labo, c'est vouloir parler tout de suite ; le
  // forum et sa question privée restent à un onglet de là.
  check(envoi && envoi.corps.exercise_id === "@chat:tp2-ex3"
        && /boucle/.test(envoi.corps.text),
        "le message part dans le chat de l'exercice affiché : "
        + JSON.stringify(envoi && envoi.corps.exercise_id));
  check(/Message publié/.test(vuDuForum()),
        "la page le confirme : " + vuDuForum().slice(0, 40));
  check(/Ma \*\*boucle\*\* ne s'arrête pas/.test(JSON.stringify(FORUM)),
        "et c'est la SOURCE Markdown qui est stockée, pas du HTML");
  check(nodes.forumtexte.value === "", "le champ est vidé après un envoi réussi");

  // UN REFUS DU SERVEUR NE FAIT PAS PERDRE LE TEXTE, et il dit POURQUOI.
  nodes.forumtexte.value = "x".repeat(FORUM_MAX + 1);
  nodes.forumtexte.listeners.input();
  const publier2 = tousLesNoeuds(nodes.vueforum)
    .find(n => n.textContent === "Publier");
  await publier2.listeners.click();
  await attendre(); await attendre();
  check(/message trop long/.test(vuDuForum()),
        "un refus reprend le message du serveur : "
        + vuDuForum().slice(0, 60));
  check(nodes.forumtexte.value.length === FORUM_MAX + 1,
        "et le texte reste dans le champ, pour être corrigé");
  nodes.forumtexte.value = "";
  nodes.forumtexte.listeners.input();

  // --- LA CASE « EN PRIVÉ » : UN CHOIX, PLUS UN LIEU -----------------------
  // C'EST L'INVARIANT DE TOUTE LA REFONTE, et le seul contrôle qui le tient.
  // Il y avait un troisième espace, « Forum de l'exercice », qu'il fallait
  // choisir AVANT d'écrire. C'est devenu une case sous le champ -- et la case
  // NE DEMANDE AUCUNE EXCEPTION AU SERVEUR : `est_chat()` force le public,
  // donc on n'écrit pas « en privé dans le chat », on écrit DANS UN AUTRE
  // FIL. Si quelqu'un remplace un jour ça par `visibility: "private"` sur la
  // clé `@chat:`, le serveur refusera en 400 -- et ce test le dira avant lui.
  const casePrivee = () => tousLesNoeuds(nodes.vueforum)
    .find((x) => x.id === "forumprive");
  check(!!casePrivee(), "la case « en privé » est sous le champ, dans le chat");
  check(casePrivee().checked === false,
        "décochée par défaut : le chat est public, et on ne le devient pas par accident");

  casePrivee().checked = true;
  await casePrivee().listeners.change();
  await attendre();
  check(tousLesNoeuds(nodes.vueforum).some((x) => /Où ça coince/.test(x.textContent || "")),
        "la cocher déplie l'étape -- sans elle, l'agrégat de l'enseignant "
        + "étiquetterait tout « énoncé »");
  check(/seul l'enseignant le lira/.test(vuDuForum()),
        "et l'écran dit qui lira, avant d'écrire");

  forumEnvois.length = 0;
  nodes.forumtexte.value = "je bloque sur le scanf";
  nodes.forumtexte.listeners.input();
  await tousLesNoeuds(nodes.vueforum)
    .find((x) => x.textContent === "Publier").listeners.click();
  await attendre(); await attendre();
  const prive = forumEnvois.find((e) => e.url === "forum" && e.corps
                                  && e.corps.text === "je bloque sur le scanf");
  check(!!prive && prive.corps.exercise_id === "tp2-ex3",
        "une question privée part sur l'identifiant NU, jamais sur « @chat: » : "
        + JSON.stringify(prive && prive.corps.exercise_id));
  check(!!prive && !/^@chat:/.test(String(prive.corps.exercise_id)),
        "-- c'est ce qui fait qu'aucune exception n'est demandée à `est_chat()`");
  check(!!prive && prive.corps.visibility === "private" && !!prive.corps.step,
        "avec sa visibilité et son étape : " + JSON.stringify(prive && prive.corps));
  check(!!casePrivee() && casePrivee().checked === false,
        "et la case se décoche : sinon le message SUIVANT serait privé sans le dire");
  // ON REMET LE HARNAIS OÙ ON L'A TROUVÉ : le serveur en carton range le chat
  // et le forum d'un exercice dans la même liste (comme la vraie table), donc
  // la question privée apparaît dans le fil qui suit.
  FORUM["tp2-ex3"] = FORUM["tp2-ex3"].filter(
    (m) => m.text !== "je bloque sur le scanf");

  // --- ENTRÉE ENVOIE, DANS LE DOCK ET NULLE PART AILLEURS ------------------
  // Le réflexe que Discord, Teams et Instagram ont déjà appris à la cohorte.
  // Pas dans la vue large : on y rédige une question de dix lignes, et une
  // touche qui l'enverrait à moitié écrite serait pire que le clic.
  check(!nodes.forumtexte.listeners.keydown,
        "la vue large n'envoie PAS sur Entrée : on y rédige");

  // On repasse dans le dock, où le réflexe compte.
  await nodes.discussions.listeners.click();   // quitter la vue large
  await attendre();
  if (nodes.chatdock.hidden !== false) {
    await nodes.discussions.listeners.click();
    await attendre(); await attendre();
  }
  check(nodes.chatdock.hidden === false, "le dock est bien rouvert");
  // ET SES CHAMPS NE PORTENT PAS LES MÊMES IDENTIFIANTS QUE LA VUE LARGE.
  // Les deux surfaces coexistent dans le document : deux `id="forumtexte"`,
  // ce serait un `<label for>` qui désigne le mauvais champ et un
  // `getElementById` qui rend le premier venu -- une panne qu'aucun
  // `node --check` ne voit.
  const champChat = tousLesNoeuds(nodes.chatdock).find((x) => x.id === "chattexte");
  check(!!champChat, "le champ du dock a son propre identifiant");
  check(!tousLesNoeuds(nodes.chatdock).some((x) => x.id === "forumtexte"),
        "et surtout pas celui de la vue large");

  forumEnvois.length = 0;
  champChat.value = "une ligne, envoyée à la touche";
  champChat.listeners.input();
  await champChat.listeners.keydown({ key: "Enter", shiftKey: false,
                                      preventDefault() { this.stoppe = true; } });
  await attendre(); await attendre();
  check(forumEnvois.some((e) => e.url === "forum" && e.corps
                          && e.corps.text === "une ligne, envoyée à la touche"),
        "ENTRÉE ENVOIE -- le seul geste qu'on n'a pas à leur enseigner");

  forumEnvois.length = 0;
  champChat.value = "première ligne";
  champChat.listeners.input();
  await champChat.listeners.keydown({ key: "Enter", shiftKey: true,
                                      preventDefault() { this.stoppe = true; } });
  await attendre();
  check(!forumEnvois.some((e) => e.url === "forum"),
        "MAJ+ENTRÉE n'envoie pas : c'est un saut de ligne, comme partout ailleurs");
  const champApres = tousLesNoeuds(nodes.chatdock).find((x) => x.id === "chattexte");
  if (champApres) { champApres.value = ""; champApres.listeners.input(); }
  FORUM["tp2-ex3"] = FORUM["tp2-ex3"].filter(
    (m) => m.text !== "une ligne, envoyée à la touche");

  // --- LE CANAL SUIT L'ÉDITEUR, ON NE LE CHOISIT PAS DEUX FOIS -------------
  // C'est ce qui a permis de retirer le second menu d'exercice de l'écran :
  // ouvrir ex.0 ouvre son canal, sans rien cliquer.
  calls.length = 0;
  await choisir("TP 2", "tp2-ex0");
  await attendre(); await attendre(); await attendre();
  check(calls.some((c) => String(c.url).indexOf("forum?ex=%40chat%3Atp2-ex0") === 0
                       || String(c.url).indexOf("forum?ex=@chat:tp2-ex0") === 0),
        "changer d'exercice change le canal du dock, sans un clic de plus : "
        + calls.map((c) => c.url).filter((u) => /forum\?ex/.test(String(u))).join(" "));
  check(tousLesNoeuds(nodes.chatdock)
          .some((x) => /^# /.test(x.textContent || "") && /ex\.0/.test(x.textContent)),
        "et la liste de canaux le dit");

  // UNE SEULE SOCKET, TOUJOURS. Le dock et la vue large lisent le même fil :
  // deux salles pour un lecteur doubleraient la charge que `FORUM_LIVE_MAX`
  // borne, et mettraient deux compteurs sur la même personne.
  check(socketsOuvertes() <= 1,
        "une seule socket de chat, dock et vue large confondus : " + socketsOuvertes());

  // ON REMET LE HARNAIS OÙ ON L'A TROUVÉ : ce fichier est un scénario
  // linéaire, et ce qui suit lit le fil de tp2-ex3 dans la vue large.
  await choisir("TP 2", "tp2-ex3");
  await attendre(); await attendre();
  await global.ctester.forum.basculer();
  await attendre(); await attendre();
  check(nodes.vueforum.hidden === false, "la vue large est rouverte pour la suite");

  // --- SIGNALER CELUI D'UN AUTRE, SUPPRIMER LE SIEN ------------------------
  forumEnvois.length = 0;
  const signaler = tousLesNoeuds(nodes.vueforum)
    .find(n => n.textContent === "Signaler");
  await signaler.listeners.click();
  await attendre(); await attendre();
  const signalement = forumEnvois.find(e => e.url === "forum/signalement");
  check(signalement && signalement.corps.id === "m-autre",
        "« Signaler » envoie l'identifiant du message d'un autre");
  check(/Signalé/.test(vuDuForum()),
        "et la page confirme qu'un humain va le lire");

  forumEnvois.length = 0;
  const supprimer = tousLesNoeuds(nodes.vueforum)
    .find(n => /Supprimer mon message/.test(n.textContent || ""));
  check(!!supprimer, "un bouton de suppression n'existe que sur SON message");
  await supprimer.listeners.click();
  await attendre(); await attendre();
  check(forumEnvois.some(e => String(e.url).startsWith("forum?id=")),
        "supprimer part sur l'identifiant de son propre message");
  const apresSuppression = vuDuForum();
  check(!/boucle/.test(apresSuppression), "et il disparaît du fil");
  check(!tousLesNoeuds(nodes.vueforum)
          .some(n => /Supprimer mon message/.test(n.textContent || "")),
        "il ne reste aucun bouton « supprimer » sur le message d'un autre");

  // Le catalogue existant sert a changer de fil, sans quitter la vue.
  calls.length = 0;
  nodes.forumex.value = "tp2-ex0";
  await nodes.forumex.listeners.change();
  await attendre(); await attendre();
  check(calls.some(c => String(c.url).startsWith(
          "forum?ex=" + encodeURIComponent("@chat:tp2-ex0"))),
        "changer d'exercice recharge le fil correspondant");

  // --- LE DIRECT NE DOIT PAS VOLER LE CURSEUR ------------------------------
  // Une sonnette arrive pendant qu'on tape. Si `rafraichirFil()` redessinait
  // à chaque fois, le `<textarea>` serait recréé et le curseur renvoyé à la
  // fin -- au milieu d'une phrase, plusieurs fois par minute pendant un labo.
  // La signature est ce qui l'empêche, et c'est elle qu'on éprouve.
  nodes.forumex.value = "tp2-ex3";
  await nodes.forumex.listeners.change();
  await attendre(); await attendre();
  const champ = document.getElementById("forumtexte");
  champ.value = "je suis en train d'écrire";
  await champ.listeners.input();
  calls.length = 0;
  await ctester.forum.rafraichirFil();
  await attendre(); await attendre();
  check(calls.filter(c => String(c.url).startsWith("forum?ex=")).length === 1,
        "une sonnette déclenche EXACTEMENT une relecture du fil");
  check(document.getElementById("forumtexte") === champ
        && champ.value === "je suis en train d'écrire",
        "et rien ne bouge quand le fil n'a pas changé : le champ est le même");

  // Un vrai message qui arrive, lui, redessine.
  FORUM["tp2-ex3"].push({ id: "m-neuf", ex: "tp2-ex3", author: "Piston lisse",
                          mine: false, hidden: false, reply_to: null,
                          created_at: "2026-09-03T22:40Z", reportable_name: false,
                          upvotes: 0, downvotes: 0, my_vote: 0,
                          text: "un message arrivé pendant qu'on lisait" });
  await ctester.forum.rafraichirFil();
  await attendre(); await attendre();
  check(/arrivé pendant qu'on lisait/.test(vuDuForum()),
        "un message neuf, lui, apparaît sans recharger la page");

  // --- RÉPONDRE VISE UN MESSAGE -------------------------------------------
  const repondre = tousLesNoeuds(nodes.vueforum)
    .find(n => (n.textContent || "") === "Répondre");
  check(!!repondre, "chaque message porte un bouton « Répondre »");
  await repondre.listeners.click();
  await attendre();
  check(/Réponse à un message/.test(vuDuForum()),
        "et le formulaire le DIT avant qu'on écrive : sans ça on tape une "
        + "réponse en croyant ouvrir une question");
  const zoneReponse = document.getElementById("forumtexte");
  zoneReponse.value = "voilà ce que j'ai trouvé";
  await zoneReponse.listeners.input();
  forumEnvois.length = 0;
  const envoyerReponse = tousLesNoeuds(nodes.vueforum)
    .find(n => (n.textContent || "") === "Répondre" && n.className === "");
  await envoyerReponse.listeners.click();
  await attendre(); await attendre(); await attendre();
  const reponseEnvoyee = forumEnvois.find(e => e.url === "forum");
  check(reponseEnvoyee && reponseEnvoyee.corps.reply_to,
        "la réponse part avec `reply_to` : " + JSON.stringify(
          reponseEnvoyee && reponseEnvoyee.corps));
  check(reponseEnvoyee && reponseEnvoyee.corps.visibility === undefined,
        "et SANS visibilité -- une réponse hérite de sa conversation, et le "
        + "serveur refuse qu'elle en porte une");

  // ON REMET LE HARNAIS OÙ ON L'A TROUVÉ : ce fichier est un scénario linéaire,
  // et les vérifications qui suivent lisent le fil vide de tp2-ex0.
  FORUM["tp2-ex3"] = FORUM["tp2-ex3"].filter(
    (m) => m.id === "m-autre" || m.id === "m-nomme");
  nodes.forumex.value = "tp2-ex0";
  await nodes.forumex.listeners.change();
  await attendre(); await attendre();
  check(/Personne n'a encore écrit/.test(vuDuForum()),
        "un fil vide le dit, et invite à écrire");

  // --- REVENIR À L'EXERCICE SANS RIEN PERDRE -------------------------------
  await nodes.discussions.listeners.click();
  await attendre();
  check(nodes.travail.hidden === false && nodes.vueforum.hidden === true,
        "le même bouton ramène à l'exercice");
  check(nodes.code.value === "// mon code en cours",
        "et le travail en cours est intact : " + nodes.code.value);

  // --- MODÉRATEUR : LA FILE DE SIGNALEMENTS ET LE MASQUAGE -----------------
  FORUM_MODERATEUR = true;
  // PAR LA VUE LARGE, ET PAS PAR LE DOCK : la porte de modération n'est pas
  // dans le panneau latéral, délibérément -- deux publics dans une colonne de
  // 22 rem, ce serait exactement le défaut qu'on vient de réparer. Le bouton
  // de la barre bascule le dock ; « en grand » est la porte, et elle est déjà
  // éprouvée plus haut.
  await global.ctester.forum.basculer();
  await attendre(); await attendre();
  // LES OUTILS DE MODÉRATION NE SONT PLUS DANS LE FIL DE L'ÉTUDIANT. Ils y
  // étaient rendus au milieu de ce que la classe vient lire : deux publics dans
  // un écran, au détriment de celui pour qui la page existe. Il reste une porte.
  const vuFil = vuDuForum();
  check(!/j'ai la meme erreur/.test(vuFil),
        "le fil ne porte plus le contenu signalé destiné au modérateur");
  check(/Ouvrir la modération/.test(vuFil),
        "seulement une porte vers l'écran de modération : " + vuFil.slice(0, 40));

  const porte = tousLesNoeuds(nodes.vueforum)
    .find(n => n.textContent === "Ouvrir la modération");
  await porte.listeners.click();
  await attendre(); await attendre();
  check(nodes.vueforum.hidden === true && nodes.vuemoderation.hidden === false,
        "la modération est un écran à part, pas un bloc de plus");
  const vuMod = contenuDe(nodes.vuemoderation);
  check(/Signalements/.test(vuMod) && /1 signalement/.test(vuMod),
        "un modérateur voit la file, avec le nombre : " + vuMod.slice(0, 40));
  check(/j'ai la meme erreur/.test(vuMod),
        "et le texte du message signalé, rendu par le MÊME assainisseur");
  check(/&lt;img src=x onerror=alert\(1\)&gt;/.test(vuMod) && !/<img/.test(vuMod),
        "la vue de modération n'affiche PAS le HTML brut « pour voir dedans » : "
        + "c'est la page dont une attaque paierait le plus");

  forumEnvois.length = 0;
  const masquer = tousLesNoeuds(nodes.vuemoderation)
    .find(n => n.textContent === "Masquer");
  await masquer.listeners.click();
  await attendre(); await attendre();
  const action = forumEnvois.find(e => e.url === "forum/moderation");
  check(action && action.corps.action === "hide" && action.corps.id === "m-autre",
        "« Masquer » part avec l'action et l'identifiant");
  check(/masqué/.test(contenuDe(nodes.vuemoderation)),
        "et l'état est écrit en toutes lettres, pas seulement en couleur");
  const retablir = tousLesNoeuds(nodes.vuemoderation)
    .find(n => n.textContent === "Rétablir");
  check(!!retablir, "un message masqué se rétablit, il ne disparaît pas");

  // RETOUR AU FIL : la moderation est un ecran a part, on en sort comme des
  // autres destinations.
  await ctester.forum.basculerModeration();
  await attendre(); await attendre();
  check(nodes.vuemoderation.hidden === true && nodes.vueforum.hidden === false,
        "on sort de la moderation vers le fil");

  // ET UN ÉTUDIANT ORDINAIRE NE LE VOIT PLUS DU TOUT.
  FORUM_MODERATEUR = false;
  nodes.forumex.value = "tp2-ex3";
  await nodes.forumex.listeners.change();
  await attendre(); await attendre();
  const vuEtudiant = vuDuForum();
  check(!/j'ai la meme erreur/.test(vuEtudiant),
        "un message masqué n'existe plus pour un étudiant ordinaire");
  check(!/Signalements/.test(vuEtudiant),
        "et la file de signalements ne lui est pas offerte");

  // --- UNE PANNE SE DIT, ET N'EMPORTE PAS L'EXERCICE -----------------------
  // ON L'ÉPROUVE DANS LE DOCK, parce que c'est là que quelqu'un vient
  // chercher de l'aide : une panne annoncée seulement dans la vue large
  // serait une panne muette pour presque tout le monde.
  await nodes.discussions.listeners.click();   // quitter la vue large
  await attendre();
  if (nodes.chatdock.hidden === false) {
    await nodes.discussions.listeners.click(); // refermer le dock
    await attendre();
  }
  FORUM_CASSE = true;
  await nodes.discussions.listeners.click();   // rouvrir, sur une panne
  await attendre(); await attendre();
  const forumCasse = contenuDe(nodes.chatdock);
  check(/ne sont pas disponibles/.test(forumCasse),
        "une panne se dit clairement : " + forumCasse.slice(-70));
  check(!/Publier/.test(forumCasse),
        "et le formulaire n'est même pas offert");
  check(/fonctionnent normalement/.test(forumCasse),
        "en disant que le juge, lui, marche toujours");
  await nodes.discussions.listeners.click();   // refermer le dock
  await attendre();
  calls.length = 0;
  nodes.code.value = codeUnique();
  await nodes.go.listeners.click();
  await attendre(); await attendre();
  check(calls.some(c => c.url.split("?")[0] === "submit"),
        "et l'exercice reste soumettable pendant ce temps-là");
  FORUM_CASSE = false;

  // « SUPPRIMER MES DONNÉES » couvre aussi la progression : le serveur efface,
  // et la page ne garde pas un solde à l'écran après coup.
  await nodes.mesprogres.listeners.click();
  await attendre();
  check(nodes.vueprogres.hidden === false, "la vue est bien ouverte avant");
  await nodes.oublier.listeners.click();
  await attendre();
  check(/supprimées/.test(shown()), "la suppression est confirmée : " + shown().slice(0, 40));
  check(nodes.vueprogres.hidden === true && nodes.travail.hidden === false,
        "la vue de progrès se referme");
  check(global.ctester.progres.projection() === null,
        "et la projection est oubliée avec la session");
  check(nodes.mesprogres.hidden === true,
        "le bouton disparaît, comme le reste du bandeau connecté");

  // Se deconnecter remet tout a zero, jusqu'au bandeau.
  global.ctester.compte.signOut();
  check(global.ctester.token() === null, "se deconnecter oublie le jeton");
  check(nodes.mesprogres.hidden === true && nodes.connexion.hidden === false,
        "et le bandeau repropose la connexion");

  // --- EXPORTER UN TP EN UN SEUL main.c ------------------------------------
  // Le format de remise du cours : un `#define exercice N` qui choisit lequel
  // des `main()` est compile, un `#if exercice == N` par exercice, les
  // `#include` remontes une seule fois. CTester garde un brouillon par
  // exercice ; sans ce bouton, l'etudiant recolle huit fichiers a la main la
  // veille de la remise, et c'est la qu'il en perd un.
  //
  // TOUT CE BLOC TOURNE A LA FIN, expres : il change de TP et pose des
  // brouillons, et rien ne doit heriter de cet etat.
  check(!global.ctester.exporter &&
        !charges.some((n) => n.startsWith("exporter.js?")),
        "exporter.js n'est pas descendu : ni le parcours anonyme ni le "
        + "parcours connecte ne le paient tant que personne ne clique");

  // QUI A DROIT AU BOUTON, ET LA REGLE VIT DANS LE NOYAU. Un quiz n'a pas de
  // code ; un exercice « unity » est un module SANS `main()`, donc un fichier
  // qui ne compilerait pas. Promettre l'export la serait promettre une remise
  // cassee.
  await choisir("TP 1");
  check(nodes.exporttp.hidden === true, "aucun export sur un quiz");
  await choisir("TP 6");
  check(nodes.exporttp.hidden === true,
        "ni sur un TP « unity » : ses exercices n'ont pas de main() a choisir");
  await choisir("TP 2", "tp2-ex3");
  check(nodes.exporttp.hidden === false,
        "mais oui sur un TP « io », dont chaque exercice est un programme complet");

  // UN CODE QUI PORTE LES DEUX PIEGES : un `#include` au premier niveau, qui
  // doit remonter et se dedoublonner, et un `#include` DEJA pris dans un `#if`
  // de l'etudiant, qui doit rester ou il est -- le remonter le rendrait
  // inconditionnel et changerait le sens de son code.
  const CODE_EX3 = [
    "#define _CRT_SECURE_NO_WARNINGS",
    "#include <stdio.h>",
    "#include <stdlib.h>",
    "",
    "int main(void) {",
    "#ifdef DEBUG",
    "#include <assert.h>",
    "#endif",
    '    printf("ohm\\n");',
    "    return EXIT_SUCCESS;",
    "}",
  ].join("\n");
  global.ctester.enregistrerBrouillon("tp2-ex3", { "submission.c": CODE_EX3 });
  // ET L'AUTRE EXERCICE DU TP, VIDE : c'est l'etat de celui qui a travaille au
  // labo et exporte depuis la maison, et c'est lui qui doit faire descendre le
  // brouillon du compte un peu plus bas.
  global.ctester.enregistrerBrouillon("tp2-ex0", {});
  // ET LA VÉRIFICATION DU MÊME TP, AVEC DU CODE. Elle ne fait pas partie de la
  // remise : si elle entrait dans le main.c, elle y ajouterait un `#if
  // exercice == N` que l'énoncé ne prévoit pas, et décalerait la numérotation.
  global.ctester.enregistrerBrouillon("verif-tp2",
                                      { "submission.c": "int verification(void);" });

  // SANS COMPTE, ET C'EST LE POINT : les brouillons de cet appareil suffisent.
  // L'export est la seule chose du parcours anonyme qui produise un fichier, et
  // il ne doit toujours parler a personne.
  const avantExport = calls.length;
  await nodes.exporttp.listeners.click();
  await attendre();
  check(charges.some((n) => n.startsWith("exporter.js?")),
        "le module descend au clic, et pas avant");
  check(calls.length === avantExport,
        "sans compte, exporter n'emet AUCUNE requete");
  const seul = telechargements[telechargements.length - 1];
  check(seul && seul.nom === "main.c",
        "un fichier main.c part sur le disque : " + (seul && seul.nom));
  check(seul.texte.charCodeAt(0) === 0xFEFF,
        "avec sa marque d'ordre UTF-8, sans quoi Visual Studio lit les accents "
        + "de l'etudiant en cp1252");
  check(/#define _CRT_SECURE_NO_WARNINGS/.test(seul.texte),
        "l'en-tete pose _CRT_SECURE_NO_WARNINGS, comme le fichier du cours");
  check(!/verification\(void\)/.test(seul.texte),
        "la vérification du TP n'entre PAS dans le main.c de remise");
  check(/\n#define exercice 3\n/.test(seul.texte),
        "et `#define exercice` designe le PREMIER exercice qui a du code : un "
        + "fichier qui s'ouvre sur un bloc vide ne compile pas");
  check(/Auteur : \n/.test(seul.texte),
        "sans compte, le champ Auteur reste vide -- on n'invente pas un nom");
  check(/Description : Exercices 0, 3 — TP 2 — TCH009/.test(seul.texte),
        "la description enumere les exercices quand ils ne se suivent pas");

  // LES `#include` REMONTENT UNE SEULE FOIS, ET SEULEMENT CEUX DU PREMIER
  // NIVEAU. C'est la regle la plus subtile du fichier, et la seule qui puisse
  // changer le sens du code de quelqu'un.
  const avantPremierBloc = seul.texte.split("#if exercice ==")[0];
  check((seul.texte.match(/#include <stdio\.h>/g) || []).length === 1 &&
        avantPremierBloc.includes("#include <stdio.h>"),
        "les includes remontent en tete, une seule fois");
  check(!avantPremierBloc.includes("assert.h") &&
        /#ifdef DEBUG\n#include <assert\.h>/.test(seul.texte),
        "mais un include deja pris dans un #if de l'etudiant ne bouge PAS");
  check(!/#if exercice == 3\n#define _CRT_SECURE_NO_WARNINGS/.test(seul.texte),
        "et _CRT_SECURE_NO_WARNINGS ne se retrouve pas en double dans un bloc");

  // LE MEME EN-TETE, COMMENTE D'UN COTE : c'est le cas courant entre deux
  // exercices d'un meme TP, et dedoublonner sur la ligne entiere le rate. La
  // ligne gardee est celle de l'etudiant, commentaire compris.
  const commente = global.ctester.exporter.construire(
    [{ id: "tpY-ex1", short: "un", files: [{ name: "submission.c" }] },
     { id: "tpY-ex2", short: "deux", files: [{ name: "submission.c" }] }],
    { "tpY-ex1": { "submission.c":
        "#include <stdio.h>  // pour printf\n#include <stdlib.h>\n\n\nint main(void) { return 0; }" },
      "tpY-ex2": { "submission.c":
        "#include <stdio.h>\n#include <stdlib.h>\nint main(void) { return 1; }" } },
    "", "TP Y");
  check((commente.texte.match(/#include <stdio\.h>/g) || []).length === 1 &&
        /#include <stdio\.h>  \/\/ pour printf/.test(commente.texte),
        "un include commente reste UN include, et garde son commentaire");
  check(!/\n[ \t]*\n[ \t]*\n/.test(commente.texte),
        "et le trou laisse par les includes retires est rabattu : pas de "
        + "fichier en accordeon");

  // UN EXERCICE SANS CODE GARDE SA PLACE. Le supprimer decalerait toute la
  // numerotation par rapport a l'enonce que l'enseignant lit.
  check(/#if exercice == 0/.test(seul.texte) &&
        /Aucun code enregistré pour cet exercice/.test(seul.texte),
        "un exercice sans brouillon laisse un bloc vide, dit comme tel");
  check(/1 exercice sur 2 \(rien pour : 0\)/.test(nodes.brouillon.textContent),
        "et le compte rendu dit ce qui manque : " + nodes.brouillon.textContent);

  // AVEC UN COMPTE, l'export va chercher ce que CET appareil n'a pas : un
  // exercice travaille au labo se remet depuis la maison.
  global.ctester.setToken(JETON);
  BROUILLONS_SERVEUR["tp2-ex0"] = { "submission.c":
    "#include <stdio.h>\nint main(void) { printf(\"age\\n\"); return 0; }" };
  await nodes.exporttp.listeners.click();
  await attendre(); await attendre();
  const complet = telechargements[telechargements.length - 1];
  check(calls.some((c) => String(c.url) === "brouillon?ex=tp2-ex0"),
        "le brouillon manquant est demande au compte");
  check(/printf\("age/.test(complet.texte) &&
        !/Aucun code enregistré/.test(complet.texte),
        "et il complete le fichier : plus aucun bloc vide");
  check(/\n#define exercice 0\n/.test(complet.texte),
        "le numero de depart suit, puisque l'exercice 0 a du code maintenant");
  // LA DESCRIPTION SE LIT COMME L'ENONCE : une enumeration quand il manque des
  // exercices au TP (ici 0 et 3, l'un des deux n'existe pas dans ce catalogue
  // de test), un intervalle quand ils se suivent. La seconde branche est
  // eprouvee en appelant `construire` directement -- c'est le TEXTE qui compte,
  // et le harnais n'a pas de TP complet a offrir.
  check(/Description : Exercices 0, 3 — TP 2 — TCH009/.test(complet.texte),
        "la description enumere ce que le TP contient vraiment : " +
        (complet.texte.match(/Description : .*/) || [])[0]);
  const troisFichiers = [1, 2, 3].map((n) =>
    ({ id: "tpX-ex" + n, short: "ex." + n, files: [{ name: "submission.c" }] }));
  const suite = global.ctester.exporter.construire(troisFichiers,
    Object.fromEntries(troisFichiers.map((tp) =>
      [tp.id, { "submission.c": "int main(void) { return 0; }" }])),
    "", "TP X");
  check(/Description : Exercices 1 à 3 — TP X — TCH009/.test(suite.texte),
        "et passe a l'intervalle quand ils se suivent : " +
        (suite.texte.match(/Description : .*/) || [])[0]);
  // LE NOM PRE-REMPLIT, IL NE S'IMPOSE PAS : c'est celui que l'etudiant a
  // choisi dans « Mon identite », dans un fichier qui va sur SON disque.
  check(/Auteur : Léa\n/.test(complet.texte),
        "l'auteur est pre-rempli avec le nom choisi : " +
        (complet.texte.match(/Auteur : .*/) || [])[0]);

  // LE MEME BOUTON DANS « MES PROGRES », par laboratoire : c'est la qu'on est
  // quand on pense « remise » plutot que « exercice courant ».
  await nodes.mesprogres.listeners.click();
  await attendre(); await attendre();
  // THE EXPORT BUTTON FOLLOWED THE GRID: it now lives at the end of its
  // lab's row, where one reads what is left to do there. The contract does
  // not change -- one button only, the one for the lab being exported, and
  // it NAMES its lab.
  const lignesExport = tousLesNoeuds(nodes.vueprogres)
    .filter((c) => c.className === "exportligne")
    .map((c) => c.children[0].textContent);
  check(lignesExport.length === 1 && lignesExport[0] === "Exporter le TP 2 en main.c",
        "un seul bouton d'export dans la liste, celui du TP qui s'exporte : "
        + JSON.stringify(lignesExport));
  await nodes.mesprogres.listeners.click();
  await attendre(); await attendre();

  // --- L'ESPACE D'ÉQUIPE ----------------------------------------------------
  // CE QUI EST ÉPROUVÉ ICI, et que rien d'autre ne peut éprouver : que le CRDT
  // est vraiment branché sur l'éditeur. Un bouchon muet prouverait seulement
  // qu'on ouvre une socket ; ici le harnais joue un coéquipier, avec un VRAI
  // Y.Doc, et on regarde le texte arriver dans le <textarea>.
  global.ctester.setToken(JETON);
  await choisir("Devoir", "dev-a");
  await attendre(); await attendre(); await attendre();

  check(charges.some(n => n.startsWith("team.js?")),
        "l'espace d'équipe descend quand on ouvre un exercice de devoir");
  check(charges.some(n => /vendor\/yjs-/.test(n)),
        "et Yjs avec lui, une seule fois, au moment où il sert");
  check(!!global.ctester.team.session(), "la session d'équipe est ouverte");
  const bandeau = () => profond(nodes.teamband);
  check(nodes.teamband.hidden === false, "le bandeau du devoir s'affiche");
  check(/Devoir — Analyseur GPS/.test(bandeau()), "il nomme le devoir");
  check(/Équipe 1/.test(bandeau()) && /groupe 04/.test(bandeau()),
        "il nomme l'ÉQUIPE et le GROUPE, qui ne sont pas la même chose : "
        + bandeau());
  check(/Bob B/.test(bandeau()) && /Coéquipier 3/.test(bandeau()),
        "il nomme les coéquipiers : le nom choisi quand il y en a un, une "
        + "position sinon");
  check(!/sub-/.test(bandeau()), "et aucun identifiant de compte : " + bandeau());
  check(/à remettre le/.test(bandeau()), "il porte la date de remise");

  // LE DOCUMENT VIENT DU SERVEUR, PAS DU BROUILLON LOCAL. C'est la seule
  // chose qui rend "les quatre voient le même document" vraie au chargement.
  check(nodes.code.value === "int main(void){return 0;}\n",
        "l'éditeur part du document de l'équipe : " + nodes.code.value);

  const socketEquipe = derniereSocket();
  check(!!socketEquipe && /\/team\/live$/.test(socketEquipe.url),
        "une socket est ouverte sur l'exercice");
  check(socketEquipe.envoyes[0].t === "hello"
        && socketEquipe.envoyes[0].token === JETON
        && socketEquipe.envoyes[0].assignment === "devoir"
        && socketEquipe.envoyes[0].exercise === "dev-a",
        "le jeton part dans la PREMIÈRE TRAME, jamais dans l'URL : "
        + JSON.stringify(socketEquipe.envoyes[0]));
  check(!/token/.test(socketEquipe.url),
        "et l'URL de la socket ne porte aucun secret : " + socketEquipe.url);

  // LA SALLE RÉPOND « tu es le premier » : la page sème le document depuis le
  // texte du serveur et ouvre l'éditeur.
  recevoir({ t: "ready", epoch: "ep-1", peers: 0, me: "m1", exercise: "dev-a" });
  await attendre();
  check(nodes.code.readOnly === false,
        "le premier arrivé peut écrire dès que la salle a répondu");
  recevoir({ t: "presence", online: ["m1", "m2"] });
  await attendre();
  check(/1 coéquipier en ligne/.test(bandeau()),
        "la présence se lit dans le bandeau : " + bandeau());

  // UN COÉQUIPIER TAPE. On fabrique une vraie mise à jour Yjs à partir du même
  // document, et on la pousse dans la socket : c'est exactement ce que le
  // serveur relaie.
  const Yjs = global.Y;
  const distant = new Yjs.Doc();
  Yjs.applyUpdate(distant, Yjs.encodeStateAsUpdate(
    global.ctester.team.session().doc));
  distant.getText("f:main.c").insert(0, "/* bob */\n");
  const miseAJour = Yjs.encodeStateAsUpdate(
    distant, Yjs.encodeStateVector(global.ctester.team.session().doc));
  const enB64 = (octets) => Buffer.from(octets).toString("base64");
  // LE CURSEUR EST PLACÉ AVANT que la modification distante n'arrive, et il
  // doit SUIVRE : c'est la panne qui rend un éditeur partagé inutilisable --
  // le texte saute et le curseur part à la fin.
  nodes.code.selectionStart = nodes.code.selectionEnd = 4;
  recevoir({ t: "update", d: enB64(miseAJour), from: "m2" });
  await attendre();
  check(nodes.code.value === "/* bob */\nint main(void){return 0;}\n",
        "le texte du coéquipier arrive dans l'éditeur : " + nodes.code.value);
  check(nodes.code.selectionStart === 4 + "/* bob */\n".length,
        "et le curseur suit le décalage au lieu de sauter : "
        + nodes.code.selectionStart);

  // CE QUE LA PAGE ENVOIE QUAND ON TAPE : une mise à jour tout de suite, et
  // une sauvegarde après la temporisation -- pas l'inverse. Un coéquipier ne
  // doit pas attendre une seconde et demie pour voir une lettre.
  const avantEnvois = socketEquipe.envoyes.length;
  const avantAppels = calls.length;
  nodes.code.value = "X" + nodes.code.value;
  nodes.code.listeners.input();
  await attendre();
  const sortiesEquipe = socketEquipe.envoyes.slice(avantEnvois);
  check(sortiesEquipe.some(t => t.t === "update"),
        "taper envoie une mise à jour immédiatement : "
        + JSON.stringify(sortiesEquipe.map(t => t.t)));
  check(sortiesEquipe.some(t => t.t === "cursor" && t.file === "main.c"),
        "et la position du curseur, pour que les autres la voient");
  // LA TRAME NE PORTE PAS D'IDENTITÉ : c'est le serveur qui tamponne
  // l'émetteur. Une page qui signerait ses trames pourrait signer celles des
  // autres.
  check(sortiesEquipe.every(t => !("from" in t)),
        "et aucune trame ne s'attribue un émetteur : "
        + JSON.stringify(sortiesEquipe));

  // DEUX TEMPORISATIONS SONT EN VOL : celle du noyau (le brouillon local) et
  // celle de la session (le document partagé). On les déclenche toutes les
  // deux -- n'en déclencher qu'une éprouverait la moitié du contrat.
  timers[timers.length - 1]();
  timers[timers.length - 2]();
  await attendre(); await attendre();
  const sauvegardeEquipe = equipeEnvois.filter(e => e.url === "team/document").pop();
  check(!!sauvegardeEquipe && sauvegardeEquipe.corps.assignment_id === "devoir"
        && sauvegardeEquipe.corps.exercise_id === "dev-a",
        "la sauvegarde partagée part après la temporisation : "
        + JSON.stringify(sauvegardeEquipe && sauvegardeEquipe.corps.exercise_id));
  check(!!sauvegardeEquipe && /^X\/\* bob \*\//.test(sauvegardeEquipe.corps.files["main.c"]),
        "et elle porte le document FUSIONNÉ, pas la valeur brute d'un onglet");
  check(!("team_id" in (sauvegardeEquipe.corps || {})),
        "le corps ne nomme AUCUNE équipe : le serveur la dérive du jeton");
  // ET LE BROUILLON INDIVIDUEL N'EST PAS ÉCRIT. Quatre membres synchronisant
  // le même texte dans `exercise_draft` seraient quatre lignes pour un seul
  // travail, et brouilleraient la seule distinction sur laquelle tout ça
  // repose. La copie LOCALE, elle, reste : elle ne coûte rien.
  check(!calls.slice(avantAppels).some(
          c => String(c.url).startsWith("brouillon")
               && c.opts && c.opts.method === "PUT"),
        "aucun brouillon individuel n'est écrit pendant une session d'équipe : "
        + JSON.stringify(calls.slice(avantAppels).map(c => String(c.url))));
  check("dev-a" in JSON.parse(storage["ctester.drafts"] || "{}"),
        "mais l'appareil en garde une copie de secours : "
        + Object.keys(JSON.parse(storage["ctester.drafts"] || "{}")).join(","));

  // L'HISTORIQUE : qui et quand, jamais un pourcentage.
  const boutonEquipe = (mot) => nodes.teamband.children
    .flatMap(c => c.children || [])
    .find(b => (b.textContent || "").indexOf(mot) === 0);
  await boutonEquipe("Historique").listeners.click();
  await attendre(); await attendre();
  check(/Bob B/.test(bandeau()) && /2026-09-07/.test(bandeau()),
        "l'historique nomme un coéquipier et une date : " + bandeau());
  check(!/%/.test(bandeau()),
        "et aucun pourcentage de contribution nulle part");

  // LE ZIP EST CONSTRUIT PAR LE SERVEUR : la page n'envoie aucun fichier.
  await boutonEquipe("Télécharger").listeners.click();
  await attendre(); await attendre();
  const demandeZip = calls.filter(c => /handin\.zip/.test(String(c.url))).pop();
  check(!!demandeZip && !demandeZip.opts.body,
        "le téléchargement n'envoie AUCUN fichier, seulement le devoir visé");
  check(demandeZip.opts.headers.Authorization === "Bearer " + JETON,
        "et il est authentifié comme le reste");

  // LA REMISE EST UN GESTE D'ÉQUIPE, et le bandeau le dit ensuite.
  global.confirm = () => true;
  await boutonEquipe("Remettre").listeners.click();
  await attendre(); await attendre();
  const remiseEquipe = equipeEnvois.filter(e => e.url === "team/handin").pop();
  check(!!remiseEquipe && remiseEquipe.corps.assignment_id === "devoir"
        && Object.keys(remiseEquipe.corps).length === 1,
        "la remise n'envoie que l'identifiant du devoir : "
        + JSON.stringify(remiseEquipe && remiseEquipe.corps));
  check(/remis le/.test(bandeau()), "et le bandeau porte la remise : " + bandeau());

  // CHANGER D'EXERCICE SANS QUITTER L'ESPACE : le bandeau reste, la socket
  // change de salle, et rien n'est perdu.
  const sallesAvant = sockets.length;
  await choisir("Devoir", "dev-b");
  await attendre(); await attendre(); await attendre();
  check(sockets.length === sallesAvant + 1,
        "changer d'exercice ouvre la salle du nouveau");
  check(socketEquipe.readyState === 3, "et ferme l'ancienne");
  check(derniereSocket().envoyes[0].exercise === "dev-b",
        "sur le bon exercice : " + derniereSocket().envoyes[0].exercise);
  check(nodes.teamband.hidden === false, "le bandeau du devoir reste affiché");

  // ET SORTIR DU DEVOIR FERME TOUT. Un exercice ordinaire ne doit garder ni
  // socket ouverte, ni bandeau, ni éditeur verrouillé.
  await choisir("TP 2", "tp2-ex3");
  await attendre(); await attendre();
  check(nodes.teamband.hidden === true,
        "un exercice ordinaire n'affiche aucun bandeau d'équipe");
  check(!global.ctester.team.session(), "et la session est refermée");
  check(nodes.code.readOnly === false, "l'éditeur individuel reste éditable");
  check(nodes.code.value !== "int main(void){return 0;}\n",
        "et il retrouve le brouillon individuel, pas le document d'équipe");

  // UN ÉTUDIANT SANS ÉQUIPE VOIT POURQUOI, et peut travailler quand même.
  CONTEXTE_REFUSE = true;
  global.ctester.team.oublier();
  await choisir("Devoir", "dev-a");
  await attendre(); await attendre(); await attendre();
  check(nodes.teamband.hidden === false && /pas d'espace d'équipe/.test(bandeau()),
        "sans équipe, le bandeau le dit : " + bandeau());
  check(/enseignant/.test(bandeau()),
        "avec la phrase du serveur, qui dit à qui parler : " + bandeau());
  check(!global.ctester.team.session() && nodes.code.readOnly === false,
        "et l'exercice reste travaillable seul, brouillon compris");
  CONTEXTE_REFUSE = false;
  global.ctester.team.oublier();

  // LE main.c D'EXPORT NE RAMASSE PAS LE TRAVAIL D'ÉQUIPE : un devoir a sa
  // propre remise, et six modules partagés n'ont rien à faire dans le fichier
  // personnel de quelqu'un.
  check(global.ctester.groupeExportable("Devoir") === false,
        "le devoir n'offre pas l'export en main.c");
  check(global.ctester.exercicesExportables("Devoir").length === 0,
        "et aucun de ses exercices n'y entre");

  // L'ORIGINE DE L'API, LES TROIS BRANCHES. Un `config.js` qui rendrait "" en
  // production enverrait chaque appel sur GitHub Pages, qui repond 404 en HTML :
  // le `catch` dirait « le serveur ne repond pas » et les logs de l'origine
  // seraient vides. C'est la panne muette que ce harnais existe pour voir.
  // `config.js` EST DANS LE <head> ET AVANT `app.js`. C'est lui qui pose le
  // theme avant le premier rendu depuis qu'il n'y a plus de script inline, et
  // c'est lui qui pose `window.API` dont depend chaque appel. Charge en fin de
  // <body>, le flash sombre->clair serait deja passe ; charge apres `app.js`,
  // la page tomberait sur une ReferenceError au premier fetch.
  const tete = html.split("</head>")[0];
  check(/<script src="config\.js/.test(tete), "config.js est charge dans le <head>");
  check(html.indexOf("config.js") < html.indexOf("app.js"),
        "et avant app.js");
  check(!/<script(?![^>]*\ssrc=)[^>]*>[^<]*\S/.test(html),
        "aucun script inline : `script-src 'self'` du <meta> le bloquerait");

  // --- LES MÉTRIQUES DE L'ÉDITEUR SONT LOAD-BEARING ------------------------
  // `#hl` (le texte coloré) est SOUS `#code` (le texte transparent) : tout ce
  // qui décale l'un d'un pixel décale les couleurs. `#gutter` est le troisième
  // texte à aligner. Ils doivent partager police, taille et interligne.
  //
  // CE CONTRÔLE EXISTE PARCE QUE LA RÉGRESSION A EU LIEU : passer le corps de
  // la page en sans-serif a fait retomber `#code` sur `font: inherit` de la
  // règle générique des champs, et lui seul est passé en 16 px. Rien dans le
  // JS ne l'aurait vu -- c'est du CSS pur, et l'oeil ne le voit qu'en tapant.
  // `feuille` ET PAS `css` : ce nom est deja pris plus haut dans cette portee,
  // et le redeclarer met l'usage anterieur en zone morte temporelle. C'est la
  // panne exacte que ce fichier existe pour attraper.
  const feuille = lire("style.css");
  const police = (selecteur) => {
    const bloc = feuille.split(selecteur + " {")[1];
    if (!bloc) return null;
    const regle = bloc.split("}")[0].match(/font:\s*([^;]+);/);
    return regle ? regle[1].trim().replace(/\s+/g, " ") : null;
  };
  const superposition = police(".hl, .codein");
  const gouttiere = police(".gutter");
  check(!!superposition,
        "la superposition declare sa police d'un seul tenant (propriete `font`)");
  check(superposition === gouttiere,
        "et la gouttiere porte EXACTEMENT la meme : "
        + superposition + " / " + gouttiere);

  // ET IL Y A DEUX ÉDITEURS MAINTENANT. La Console a le sien -- elle ne touche
  // jamais `#code` -- mais il porte les MÊMES classes, donc la même et unique
  // déclaration de police. Un `font-family` reposé sur `#code` ou `#scratchcode`
  // gagnerait par spécificité d'ID sur la classe, et la couche colorée
  // décrocherait du texte tapé d'un caractère de plus à chaque ligne. C'est la
  // régression que ce contrôle-ci attrape, et elle est invisible au JS.
  const motif = "^[^{}" + String.fromCharCode(10) + "]*#(?:scratch)?code"
              + "[^{}" + String.fromCharCode(10) + "]*\\{[^}]*font-family";
  const surcharge = feuille.match(new RegExp(motif, "m"));
  check(!surcharge,
        "aucun selecteur d'ID ne repose une police sur un des deux editeurs"
        + (surcharge ? " : " + surcharge[0].split("{")[0].trim() : ""));
  const markup = lire("index.html");
  for (const classe of ["hl", "codein", "gutter"]) {
    check(new RegExp("class=\"[^\"]*\\b" + classe + "\\b").test(markup),
          "l'editeur d'exercice porte la classe partagee `" + classe + "`");
  }

  // --- LA CONSOLE -----------------------------------------------------------
  // CE QUI EST ÉPROUVÉ ICI : que la socket part vraiment, que le jeton voyage
  // dans la PREMIÈRE TRAME et jamais dans l'URL, que la sortie du programme
  // arrive à l'écran, et que quitter la vue ferme la session -- sans quoi un
  // conteneur survivrait à un changement d'écran en tenant un cœur du Dell.
  check(nodes.scratch.hidden === false,
        "connecté : le bouton Console apparaît");
  BLOC_NOTES = "int main(void){return 0;}";
  await nodes.scratch.listeners.click();
  await attendre(); await attendre();
  check(!!global.ctester.scratch, "scratch.js est chargé au clic, pas avant");
  check(nodes.viewscratch.hidden === false, "et la vue Console s'ouvre");
  check(nodes.scratchcode.value === BLOC_NOTES,
        "le bloc-notes du COMPTE remplit l'éditeur : "
        + JSON.stringify(nodes.scratchcode.value));

  // LA COLORATION EST CELLE DU NOYAU, pas une seconde grammaire. Ce qui est
  // éprouvé ici, c'est le câblage : que la couche colorée soit peinte au
  // chargement du bloc-notes, et que la gouttière compte les mêmes lignes.
  check(/<span class="tk">int<\/span>/.test(nodes.scratchhlcode.innerHTML),
        "l'éditeur de la Console est coloré par `ctester.colorierC` : "
        + nodes.scratchhlcode.innerHTML);
  check(profond(nodes.scratchgutter).trim() === "1",
        "et sa gouttière numérote les lignes : "
        + JSON.stringify(profond(nodes.scratchgutter)));

  // L'éditeur de la Console est le SIEN : il ne doit jamais toucher celui de
  // l'exercice, qui appartient à `currentId` et à son brouillon.
  const codeExercice = nodes.code.value;
  nodes.scratchcode.value = "#include <stdio.h>\nint main(void){printf(\"salut\");}";
  await nodes.scratchgo.listeners.click();
  await attendre();
  const sock = derniereSocket();
  check(!!sock && /\/scratch\/live$/.test(sock.url),
        "une socket est ouverte sur /scratch/live : " + (sock && sock.url));
  check(!/token/.test((sock && sock.url) || ""),
        "et son URL ne porte AUCUN secret");
  const hello = sock && sock.envoyes[0];
  check(hello && hello.t === "hello" && hello.token === JETON
        && hello.code === nodes.scratchcode.value,
        "la première trame est `hello`, avec le jeton et le code : "
        + JSON.stringify(hello));
  check(nodes.code.value === codeExercice,
        "et l'éditeur de l'EXERCICE n'a pas bougé d'un caractère");

  // La file, puis la sortie du programme.
  recevoir({ t: "queued", position: 3, eta: 120 });
  await attendre();
  check(/file/i.test(profond(nodes.scratchetat)),
        "la position dans la file s'affiche : " + profond(nodes.scratchetat));
  recevoir({ t: "ready" });
  recevoir({ t: "out", d: "Entrez un nombre : " });
  await attendre();
  check(profond(nodes.scratchout).includes("Entrez un nombre : "),
        "ce que le programme écrit arrive dans le terminal");

  // Répondre : la trame porte le saut de ligne, sans quoi `scanf` resterait
  // bloqué sur une entrée que l'étudiant croit avoir envoyée.
  nodes.scratchsaisie.value = "42";
  await nodes.scratchenvoi.listeners.click();
  await attendre();
  const tape = sock.envoyes[sock.envoyes.length - 1];
  check(tape && tape.t === "stdin" && tape.d === "42\n",
        "ce qu'on tape part avec son saut de ligne : " + JSON.stringify(tape));
  check(profond(nodes.scratchout).includes("42"),
        "et l'écho local le montre : il n'y a pas de terminal pour le faire");

  // « Fin d'entrée », qui est ce qui termine un `while (scanf(...) == 1)`.
  await nodes.scratcheof.listeners.click();
  await attendre();
  check(sock.envoyes[sock.envoyes.length - 1].t === "eof",
        "« Fin d'entrée » envoie une trame `eof`");

  // Une sortie expliquée, et pas seulement un code.
  recevoir({ t: "exit", code: 137, reason: "cpu" });
  await attendre();
  check(/boucle infinie/i.test(profond(nodes.scratchetat)),
        "une mort par temps CPU est EXPLIQUÉE, pas juste chiffrée : "
        + profond(nodes.scratchetat));

  // QUITTER LA VUE FERME LA SESSION.
  nodes.scratchcode.value = "int main(void){return 1;}";
  await nodes.scratchgo.listeners.click();
  await attendre();
  check(!!global.ctester.scratch.session(), "une session est ouverte");
  await nodes.scratch.listeners.click();
  await attendre();
  check(!global.ctester.scratch.session(),
        "quitter la vue ferme la socket : aucun conteneur ne survit à un"
        + " changement d'écran");
  check(nodes.viewscratch.hidden === true, "et la vue se referme");

  for (const [hote, attendu] of [
    ["tch009.thevhome.com", "https://tch099.thevhome.com/catalog.json"],
    ["vianpyro.github.io", "https://tch099.thevhome.com/catalog.json"],
    ["localhost", "catalog.json"],
  ]) {
    global.location.hostname = hote;
    new Function(lire("config.js"))();
    check(global.API("catalog.json") === attendu, "config.js : " + hote + " -> " + attendu);
  }

  // LE CATALOGUE ABSENT ET LE LIEN VERROUILLÉ, dans leur propre processus. Le catalogue
  // n'est lu qu'une fois par chargement de page : les éprouver ici voudrait
  // dire rejouer un premier chargement, ce qu'aucun `await` ne sait faire.
  for (const mode of ["absent", "verrou", "sanscle"]) {
    const fils = require("child_process").spawnSync(
      process.execPath, [__filename, APP],
      { env: Object.assign({}, process.env, { CTESTER_MODE: mode }),
        encoding: "utf8" });
    process.stdout.write(fils.stdout || "");
    process.stderr.write(fils.stderr || "");
    if (fils.status !== 0) failures++;
  }

  console.log(failures ? `\n${failures} ÉCHEC(S)` : "\nla page fonctionne");
  process.exit(failures ? 1 : 0);
})();
