// Exécute VRAIMENT le JS de index.html, avec un DOM minimal en trompe-l'oeil.
// C'est le contrôle que `node --check` ne peut pas faire : la seule panne que
// cette page ait connue en production était une ReferenceError de zone morte
// temporelle -- une erreur d'exécution, pas de syntaxe.
//
//   node test_page.js [web/]
//
// La page est en TROIS fichiers depuis qu'elle a ete decoupee, et chacun porte
// un contrat different : `html` les identifiants et l'ordre du document, `css`
// les regles `display:`, `js` le code qu'on execute vraiment.
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
    // Un vrai element en a un : la vue « Mes progrès » y déplace le focus en
    // s'ouvrant, et un harnais qui ne le connait pas ferait lever la page.
    focus() { focusé = this.id; },
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
// UN HOTE INCONNU DE `config.js`, expres : le harnais joue le mode local,
// celui ou `app.py` sert encore la page et ou les appels restent relatifs.
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
// Un déploiement où la connexion EST configurée, ET où le forum est activé
// (donc où des modérateurs sont configurés côté serveur). Tout ce qui suit doit
// malgré tout se comporter comme avant tant que personne ne s'est connecté :
// c'est la combinaison la plus exigeante pour la promesse « l'anonyme ne
// télécharge rien ».
const OIDC_RESPONSE = { issuer: "https://auth.example", client_id: "ctester",
                        forum: true };
let SUBMIT_RESPONSE;
let DECOUVERTE_CASSEE = false;
const JETON = "jeton-de-test";
// LE THÈME DU COMPTE, cote serveur. Une chaine vide veut dire « ce compte n'a
// rien choisi » -- ce qui n'est pas la meme chose qu'une panne, et la page ne
// doit pas ecraser le theme de l'appareil dans ce cas.
let THEME_SERVEUR = "";
const ETATS = { etats: [{ exercice_id: "tp2-ex0", statut: "valide" }] };
const PRATIQUE = { pratique: [
  { exercice_id: "tp2-ex3", tentatives: 3, reussites: 1 }] };
let POLL_RESPONSE = { state: "queued", position: 1 };
let PROGRES_CASSE = false;

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
const FORUM = {
  "tp2-ex3": [{ id: "m-autre", ex: "tp2-ex3", auteur: "Participant",
                mien: false, masque: false, cree_le: "2026-09-03T22:30Z",
                nom_signalable: false,
                texte: "<img src=x onerror=alert(1)> j'ai la meme erreur" },
              { id: "m-nomme", ex: "tp2-ex3", auteur: "Bob B", mien: false,
                masque: false, cree_le: "2026-09-03T22:35Z", groupe: 4,
                nom_signalable: true, texte: "moi aussi" }],
  "tp2-ex0": [],
};
const FORUM_SIGNALES = new Map();   // identifiant de message -> combien de fois
// LE PROFIL DE CE COMPTE. `suggestion` est le `preferred_username` de Rauthy :
// une PROPOSITION, qui ne doit rien afficher tant qu'on n'a pas enregistre.
const PROFIL = { pseudo: null, groupe: null, pseudo_public: false,
                 groupe_public: false, max_pseudo: 24, groupes: [4, 6],
                 suggestion: "vveremme" };
const forumEnvois = [];
let forumCompteur = 0;
// UNE COMPETENCE HOSTILE : les identifiants viennent du depot de tests, et un
// libelle inconnu s'affiche tel quel. S'il finit dans du HTML, il s'execute.
const PROGRES = {
  politique: "pilote-1",
  xp: 45,
  niveau: { rang: 2, depuis: 30, prochain: 80, restant: 35 },
  exercices: { total: 4, pratiques: 2, reussis: 1 },
  competences: [
    { id: "variables", total: 2, pratiques: 2, reussis: 1 },
    { id: "<img src=x onerror=alert(1)>", total: 1, pratiques: 1, reussis: 0 },
  ],
  succes: [{ id: "premiere-reussite", titre: "Premier exercice réussi",
             description: "Tu as fait passer tous les tests d'un exercice.",
             obtenu_le: "2026-09-01" }],
  suivant: { exercice_id: "tp2-ex3", competence: "variables" },
  transactions: [{ exercice_id: "tp2-ex0", montant: 15,
                   motif: "première réussite", accorde_le: "2026-09-01" }],
};
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
    return { ok: true, status: 200, json: async () => ({ sources: {} }) };
  }
  if (String(url).startsWith("forum")) return forumRepond(url, opts);
  if (url === "submit") return SUBMIT_RESPONSE;
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
      return rendJson({ signalements: tous()
        .filter((m) => FORUM_SIGNALES.has(m.id))
        .map((m) => ({ id: m.id, exercice_id: m.ex, texte: m.texte,
                       masque: m.masque, cree_le: m.cree_le,
                       signalements: FORUM_SIGNALES.get(m.id) })) });
    }
    forumEnvois.push({ url, corps });
    const cible = tous().find((m) => m.id === corps.id);
    if (!cible) return rendErreur(404, "message introuvable");
    cible.masque = corps.action === "masquer";
    return rendJson({ ok: true });
  }
  // LE PROFIL : le nom qu'on s'est donne, le groupe, et ce qui est affiche.
  if (url === "forum/profil") {
    if (methode === "GET") return rendJson(Object.assign({}, PROFIL));
    forumEnvois.push({ url, corps });
    Object.assign(PROFIL, {
      pseudo: corps.pseudo || null,
      groupe: corps.groupe === "" ? null : Number(corps.groupe),
      pseudo_public: !!corps.pseudo_public && !!corps.pseudo,
      groupe_public: !!corps.groupe_public,
      suggestion: "",
    });
    // Le fil reflete le nom choisi, comme le ferait le serveur.
    for (const m of tous()) {
      if (!m.mien) continue;
      m.auteur = PROFIL.pseudo_public ? PROFIL.pseudo : "Vous";
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
    if (corps.texte.length > FORUM_MAX) {
      return rendErreur(400, "message trop long (maximum " + FORUM_MAX
                             + " caractères)");
    }
    forumCompteur++;
    (FORUM[corps.tp] || (FORUM[corps.tp] = [])).push({
      id: "m" + forumCompteur, ex: corps.tp, auteur: "Vous", mien: true,
      masque: false, cree_le: "2026-09-03 10:0" + forumCompteur,
      texte: corps.texte });
    return rendJson({ ok: true });
  }
  if (methode === "DELETE") {
    forumEnvois.push({ url, corps: null });
    const id = decodeURIComponent(String(url).split("id=")[1] || "");
    for (const ex of Object.keys(FORUM)) {
      FORUM[ex] = FORUM[ex].filter((m) => m.id !== id || !m.mien);
    }
    return rendJson({ ok: true });
  }
  const ex = decodeURIComponent(String(url).split("ex=")[1] || "");
  return rendJson({
    exercice_id: ex,
    moderateur: FORUM_MODERATEUR,
    max: FORUM_MAX,
    messages: (FORUM[ex] || []).filter((m) => FORUM_MODERATEUR || !m.masque),
  });
}

// UNE VISITE PRÉCÉDENTE, déposée avant que la page ne démarre : un brouillon
// bien formé, et deux entrées empoisonnées. Ce qui sort du stockage n'est pas
// de la donnée de confiance, et seule la première doit atteindre l'éditeur.
storage["ctester.drafts"] = JSON.stringify({
  "tp2-ex3": { "submission.c": "// travail d'hier" },
  "tp2-ex0": { "submission.c": { pas: "une chaîne" } },
  "tp6-ex1": "pas un objet de fichiers",
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
        nodes.oublier.hidden === true && nodes.discussions.hidden === true,
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
  check(nodes.travail.hidden === true && nodes.vueprogres.hidden === false &&
        nodes.liste.hidden === true,
        "la vue remplace l'exercice, et la vue liste reste fermée");
  check(nodes.mesprogres.textContent === "Retour à l'exercice",
        "le bouton dit comment revenir");
  check(focusé === "progrestitre",
        "le focus suit l'écran : sans ça, la tabulation repart du haut et un "
        + "lecteur d'écran n'annonce rien");

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
  check(nodes.ex.value === "tp2-ex3" && nodes.vueprogres.hidden === true,
        "il ouvre l'exercice recommandé et referme la vue");

  // APRÈS UN VERDICT, la projection est redemandée AU SERVEUR. C'est lui qui
  // vient peut-être d'accorder l'XP d'une première réussite ; la page n'en
  // calcule aucune part, elle la relit.
  POLL_RESPONSE = { state: "done", status: "ok", kind: "io",
                    passed: 1, total: 1, cases: [] };
  SUBMIT_RESPONSE = { ok: true, status: 200,
                      json: async () => ({ id: "f".repeat(32) }) };
  nodes.code.value = "int main(void){return 0;}";
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
  nodes.code.value = "int main(void){return 0;}";
  await nodes.go.listeners.click();
  await attendre(); await attendre();
  check(calls.some(c => c.url === "submit"),
        "et l'exercice reste soumettable pendant ce temps-là");
  PROGRES_CASSE = false;

  // --- « DISCUSSIONS » : LE FORUM ------------------------------------------
  // Tout ce qui suit n'existe QUE connecté, et QUE sur un déploiement qui a des
  // modérateurs configurés. Le bloc anonyme plus haut prouve l'inverse : ni
  // fichier, ni requête, ni en-tête.
  await choisir("TP 2", "tp2-ex3");
  nodes.code.value = "// mon code en cours";
  check(nodes.discussions.hidden === false,
        "« Discussions » apparaît une fois connecté");
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
  check(nodes.travail.hidden === true && nodes.vueforum.hidden === false &&
        nodes.vueprogres.hidden === true && nodes.liste.hidden === true,
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
  check(/j'ai la meme erreur/.test(vuForum) && /Participant/.test(vuForum),
        "le fil montre le message d'un autre, signé « Participant »");
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

  const dansPanneau = (texte) => tousLesNoeuds(panneau)
    .find((n) => n.textContent === texte);
  nodes.forumpseudo.value = "Léa";
  nodes.forumgroupe.value = "4";
  nodes.forumvoirnom.checked = true;
  await dansPanneau("Enregistrer").listeners.click();
  await sleep(); await sleep(); await sleep();
  const profilEnvoye = forumEnvois.find((e) => e.url === "forum/profil");
  check(profilEnvoye && profilEnvoye.corps.pseudo === "Léa"
        && profilEnvoye.corps.groupe === "4"
        && profilEnvoye.corps.pseudo_public === true
        && profilEnvoye.corps.groupe_public === false,
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
    (e) => e.url === "forum/signalement" && e.corps && e.corps.quoi === "nom");
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

    // ET LA CHARGE RESTE VISIBLE COMME DU TEXTE. Un message dont la moitié
    // s'évapore ferait croire à un bug plutôt qu'à une règle -- et surtout,
    // « rien ne s'affiche » et « rien ne s'exécute » ne sont pas la même
    // preuve : ceci vérifie la seconde en montrant la première.
    const vuTexte = auditer(passerAuRendu("<img src=x onerror=alert(1)>").html);
    check(/<img src=x onerror=alert\(1\)>/.test(vuTexte.texte),
          "une balise hostile reste lisible EN TEXTE : " + vuTexte.texte);

    // ET LE HTML BRUT RESTE LISIBLE PLUTOT QUE DE DISPARAITRE : il est
    // ECHAPPE, pas supprime. Un message dont la moitie s'evapore ferait croire
    // a un bug plutot qu'a une regle.
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
  check(envoi && envoi.corps.tp === "tp2-ex3" && /boucle/.test(envoi.corps.texte),
        "le message part, avec l'exercice affiché");
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
  check(calls.some(c => String(c.url).startsWith("forum?ex=tp2-ex0")),
        "changer d'exercice recharge le fil correspondant");
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
  await nodes.discussions.listeners.click();
  await attendre(); await attendre();
  const vuMod = vuDuForum();
  check(/Signalements/.test(vuMod) && /1 signalement/.test(vuMod),
        "un modérateur voit la file, avec le nombre : " + vuMod.slice(0, 40));
  check(/j'ai la meme erreur/.test(vuMod),
        "et le texte du message signalé, rendu par le MÊME assainisseur");
  check(/&lt;img src=x onerror=alert\(1\)&gt;/.test(vuMod) && !/<img/.test(vuMod),
        "la vue de modération n'affiche PAS le HTML brut « pour voir dedans » : "
        + "c'est la page dont une attaque paierait le plus");

  forumEnvois.length = 0;
  const masquer = tousLesNoeuds(nodes.vueforum)
    .find(n => n.textContent === "Masquer");
  await masquer.listeners.click();
  await attendre(); await attendre();
  const action = forumEnvois.find(e => e.url === "forum/moderation");
  check(action && action.corps.action === "masquer" && action.corps.id === "m-autre",
        "« Masquer » part avec l'action et l'identifiant");
  check(/masqué/.test(vuDuForum()),
        "et l'état est écrit en toutes lettres, pas seulement en couleur");
  const retablir = tousLesNoeuds(nodes.vueforum)
    .find(n => n.textContent === "Rétablir");
  check(!!retablir, "un message masqué se rétablit, il ne disparaît pas");

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
  await nodes.discussions.listeners.click();   // fermer
  await attendre();
  FORUM_CASSE = true;
  await nodes.discussions.listeners.click();
  await attendre(); await attendre();
  const forumCasse = vuDuForum();
  check(/ne sont pas disponibles/.test(forumCasse),
        "une panne se dit clairement : " + forumCasse.slice(-70));
  check(!/Publier/.test(forumCasse),
        "et le formulaire n'est même pas offert");
  check(/fonctionnent normalement/.test(forumCasse),
        "en disant que le juge, lui, marche toujours");
  await nodes.discussions.listeners.click();   // retour à l'exercice
  await attendre();
  calls.length = 0;
  nodes.code.value = "int main(void){return 0;}";
  await nodes.go.listeners.click();
  await attendre(); await attendre();
  check(calls.some(c => c.url === "submit"),
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
  check(nodes.mesexos.hidden === true && nodes.connexion.hidden === false,
        "et le bandeau repropose la connexion");

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

  for (const [hote, attendu] of [
    ["tch009.thevhome.com", "https://tch099.thevhome.com/tps.json"],
    ["vianpyro.github.io", "https://tch099.thevhome.com/tps.json"],
    ["localhost", "tps.json"],
  ]) {
    global.location.hostname = hote;
    new Function(lire("config.js"))();
    check(global.API("tps.json") === attendu, "config.js : " + hote + " -> " + attendu);
  }

  console.log(failures ? `\n${failures} ÉCHEC(S)` : "\nla page fonctionne");
  process.exit(failures ? 1 : 0);
})();
