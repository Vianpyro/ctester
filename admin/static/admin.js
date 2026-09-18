// No build step and no dependency: the dashboard is small enough to stay plain.

import { connecter, demarrer, jetonValide, oublier } from "/auth.js";

const $ = (id) => document.getElementById(id);
const RAFRAICHIR = 5000;

// A verdict's colour says who should care. A student whose code does not compile
// is the course working as intended, so it stays neutral; amber is a resource
// limit, which can mean a badly calibrated exercise; red is the judge itself.
const ETATS = {
  ok: "ok",
  compile_error: "neutre",
  link_error: "neutre",
  forbidden_include: "neutre",
  compile_timeout: "attention",
  timeout: "attention",
  memory_error: "attention",
  error: "alerte",
  console: "console",
};

const classeEtat = (statut) => "etat-" + (ETATS[statut] || "neutre");
const couleurEtat = (statut) => "var(--" + (ETATS[statut] || "neutre") + ")";

const deux = (n) => String(n).padStart(2, "0");

function horloge(iso) {
  const d = new Date(iso);
  return deux(d.getHours()) + ":" + deux(d.getMinutes()) + ":" + deux(d.getSeconds());
}

const texte = (v) => (v === null || v === undefined || v === "" ? "–" : String(v));

function secondes(v) {
  if (typeof v !== "number") return "–";
  if (v >= 60) return Math.round(v / 60) + " min";
  return (v >= 10 ? Math.round(v) : v.toFixed(1)) + " s";
}

function duree(s) {
  if (typeof s !== "number") return "–";
  if (s < 60) return Math.round(s) + " s";
  if (s < 3600) return Math.round(s / 60) + " min";
  return Math.round(s / 3600) + " h";
}

function el(tag, classe, contenu) {
  const node = document.createElement(tag);
  if (classe) node.className = classe;
  if (contenu !== undefined) node.textContent = contenu;
  return node;
}

function vide(cible, message) {
  cible.textContent = "";
  cible.append(el("p", "vide", message));
}

// Reconstruire un panneau remet son defilement en haut : ne le faire que si les
// donnees ont vraiment change, et remettre le lecteur ou il etait quand ca arrive.
function rendre(cible, donnees, remplir) {
  const signature = JSON.stringify(donnees);
  if (cible.dataset.signature === signature) return;
  const haut = cible.scrollTop;
  remplir();
  cible.dataset.signature = signature;
  // ponytail: des lignes inserees en tete decalent ce que cette position montre ;
  // s'ancrer sur un identifiant de ligne serait exact et nettement plus lourd.
  cible.scrollTop = haut;
}

async function json(url) {
  const porteur = await jetonValide();
  if (!porteur) throw new Error("session expirée");
  const reponse = await fetch(url, {
    headers: { accept: "application/json", authorization: "Bearer " + porteur },
  });
  // 401 : le jeton est mort malgre le renouvellement, il faut se reconnecter.
  if (reponse.status === 401) {
    oublier();
    ecranConnexion("Session expirée.");
    throw new Error("session expirée");
  }
  if (reponse.status === 403) {
    ecranConnexion("Ce compte n'est pas enseignant.");
    throw new Error("réservé à l'enseignant");
  }
  if (reponse.status === 503) {
    const dit = await reponse.json().catch(() => ({}));
    ecranConnexion(dit.error || "Service indisponible.");
    throw new Error(dit.error || "service indisponible");
  }
  if (!reponse.ok) throw new Error(reponse.status + " " + reponse.statusText);
  return reponse.json();
}

let minuterie = null;

function ecranConnexion(raison) {
  if (minuterie) {
    clearInterval(minuterie);
    minuterie = null;
  }
  document.body.classList.add("deconnecte");
  $("connexion-raison").textContent = raison || "";
}

/* ---- vitals ------------------------------------------------------------ */

function vital(cle, valeur, note, options = {}) {
  const node = el("div", "vital");
  node.append(el("div", "cle", cle));
  const v = el("div", "valeur" + (options.mono ? " mono" : "") + (options.alarme ? " alarme" : ""),
               valeur);
  node.append(v, el("div", "note", note || " "));
  return node;
}

function vitaux(data) {
  const cible = $("vitaux");
  rendre(cible, [data.queue, data.stats, data.release, data.windows],
         () => remplirVitaux(cible, data));
}

function remplirVitaux(cible, data) {
  cible.textContent = "";
  const q = data.queue;
  const s = data.stats;
  const r = data.release;

  if (q) {
    const attente = q.waiting === undefined ? q.pending : q.waiting;
    cible.append(vital("En file", attente,
      q.running ? q.running + " en cours de correction"
        : (attente ? "plus ancien " + duree(q.oldest_s) : "rien en attente")));
    cible.append(vital("Attente estimée", duree(q.eta_s),
      q.pending ? "avant le dernier job" : "file libre"));
  }
  if (data.windows) {
    const n = data.windows.open;
    cible.append(vital("Fenêtres", n === null || n === undefined ? "–" : n,
      n === null || n === undefined ? "API injoignable" : "ouvertes, connecté ou non"));
  }
  if (s) {
    const notes = s.graded === undefined ? s.total : s.graded;
    const taux = notes ? Math.round((s.cache_hits / notes) * 100) : 0;
    cible.append(vital("Runs 24 h", s.total,
      s.total ? s.ok + " réussis" : "aucun run"));
    cible.append(vital("Cache", taux + " %",
      s.cache_hits + " sans compiler, sur " + notes + " notés"));
    cible.append(vital("Attente moyenne", secondes(s.average_wait_s), "avant un worker"));
    cible.append(vital("Reprises", s.reprises,
      s.reprises ? "un worker a été interrompu" : "aucune interruption",
      { alarme: s.reprises > 0 }));
  }
  if (r) {
    cible.append(vital("Révision", r.revision ? r.revision.slice(0, 10) : "–",
      r.published_at
        ? new Date(r.published_at * 1000).toLocaleString("fr-CA",
            { dateStyle: "short", timeStyle: "short" })
          + (r.exercises ? ", " + r.exercises + " exercices" : "")
        : "aucune release",
      { mono: true }));
  }
}

/* ---- verdict distribution ---------------------------------------------- */

function repartition(statuses) {
  rendre($("legende"), statuses, () => remplirRepartition(statuses));
}

function remplirRepartition(statuses) {
  const jauge = $("jauge");
  const legende = $("legende");
  jauge.textContent = "";
  legende.textContent = "";
  const lignes = statuses || [];
  const total = lignes.reduce((n, s) => n + s.count, 0);
  if (!total) {
    legende.append(el("span", null, "Aucun verdict sur la période."));
    return;
  }
  for (const s of lignes) {
    const part = el("span");
    part.style.width = (s.count / total) * 100 + "%";
    part.style.background = couleurEtat(s.status);
    part.title = s.status + " : " + s.count;
    jauge.append(part);

    const item = el("span");
    const puce = el("span", "puce");
    puce.style.background = couleurEtat(s.status);
    item.append(puce, document.createTextNode(s.status + " "), el("i", null, s.count));
    legende.append(item);
  }
}

/* ---- tables ------------------------------------------------------------ */

function tableau(cible, colonnes, lignes, rendu, message) {
  if (!lignes || lignes.length === 0) {
    vide(cible, message);
    return;
  }
  const table = el("table");
  const colgroup = el("colgroup");
  for (const col of colonnes) {
    const c = el("col");
    if (col.largeur) c.style.width = col.largeur;
    colgroup.append(c);
  }
  table.append(colgroup);
  const tr = el("tr");
  for (const col of colonnes) {
    tr.append(el("th", col.classe || null, col.titre));
  }
  const thead = el("thead");
  thead.append(tr);
  const tbody = el("tbody");
  for (const ligne of lignes) tbody.append(rendu(ligne));
  table.append(thead, tbody);
  cible.textContent = "";
  cible.append(table);
}

// [texte, classe, infobulle] -- the third item carries what truncation hides.
function cellules(valeurs) {
  const tr = el("tr");
  for (const v of valeurs) {
    const liste = Array.isArray(v) ? v : [v];
    const td = el("td", liste[1] || null, liste[0]);
    if (liste[2]) td.title = liste[2];
    tr.append(td);
  }
  return tr;
}

/* ---- panels ------------------------------------------------------------ */

function workers(rows, configures) {
  const cible = $("workers");
  rendre(cible, [rows, configures], () => remplirWorkers(cible, rows, configures));
}

function remplirWorkers(cible, rows, configures) {
  const note = $("workers-note");
  if (!rows || rows.length === 0) {
    note.textContent = configures ? "0 sur " + configures : "";
    vide(cible, "Aucun run depuis 24 h.");
    return;
  }
  const vivants = rows.filter((w) => w.alive).length;
  note.textContent = vivants + " actif" + (vivants > 1 ? "s" : "")
    + (configures ? " sur " + configures : "");
  cible.textContent = "";
  for (const w of rows) {
    const ligne = el("div", "ligne");
    const point = el("span", w.alive ? "vivant" : "mort");
    point.title = w.alive ? "a fini un run récemment" : "silencieux depuis 5 min";
    const droite = el("div", "droite");
    droite.append(el("b", null, w.runs), document.createTextNode(" runs, "
      + secondes(w.average_s)));
    ligne.append(point, el("span", "nom", "worker " + w.worker_id), droite);
    if (w.failures) ligne.title = w.failures + " échec(s)";
    cible.append(ligne);
  }
}

function usage(data, jours) {
  const cible = $("usage");
  rendre(cible, [data.usage, data.stats, jours], () => remplirUsage(cible, data, jours));
}

function remplirUsage(cible, data, jours) {
  $("usage-note").textContent = jours === 1 ? "24 h" : jours + " jours";
  if (!data.usage) {
    vide(cible, "Base de données injoignable.");
    return;
  }
  cible.textContent = "";
  const grille = el("div", "usage");
  const paires = [
    ["Résolus", data.usage.solved],
    ["Comptes", data.usage.active_accounts],
    ["XP", data.usage.xp],
    ["Réussite", data.stats && data.stats.graded
      ? Math.round((data.stats.ok / data.stats.graded) * 100) + " %"
      : "–"],
  ];
  for (const [cle, valeur] of paires) {
    const bloc = el("div");
    bloc.append(el("div", "cle", cle), el("div", "valeur", valeur));
    grille.append(bloc);
  }
  cible.append(grille);
}

function file(q) {
  const cible = $("file");
  rendre(cible, q, () => remplirFile(cible, q));
}

function remplirFile(cible, q) {
  const head = (q && q.head) || [];
  $("file-note").textContent = q && q.pending
    ? q.pending + " en attente" : "";
  tableau(cible,
    [{ titre: "exercice" }, { titre: "attente", classe: "n", largeur: "4.5rem" }],
    head,
    (j) => {
      const tr = cellules([texte(j.exercise_id), [duree(j.waiting_s), "n"]]);
      tr.title = (j.signed_in ? "connecté" : "anonyme") + ", job " + j.job_id.slice(-8);
      return tr;
    },
    "Rien en attente.");
}

function exercices(rows, jours) {
  rendre($("exercices"), [rows, jours], () => remplirExercices(rows, jours));
}

function remplirExercices(rows, jours) {
  $("exercices-note").textContent = jours === 1 ? "24 h" : jours + " jours";
  tableau($("exercices"),
    [{ titre: "exercice" }, { titre: "runs", classe: "n", largeur: "3.2rem" },
     { titre: "échecs", classe: "n", largeur: "3.8rem" },
     { titre: "moy.", classe: "n", largeur: "4.2rem" },
     { titre: "p95", classe: "n", largeur: "4.2rem" }],
    rows,
    (e) => cellules([
      [e.exercise_id || "–", null, e.exercise_id],
      [String(e.runs), "n"],
      [String(e.failures), e.failures ? "n etat-alerte" : "n zero"],
      [secondes(e.average_s), "n"],
      [secondes(e.p95_s), "n"],
    ]),
    "Aucun run sur la période.");
}

/* ---- discussions ------------------------------------------------------- */

const CHAT = "@chat:";

function nomCanal(cle) {
  if (cle === CHAT + "general") return "# général";
  if (cle.startsWith(CHAT)) return "# " + cle.slice(CHAT.length);
  return cle + " (privé)";
}

function depuis(iso) {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "à l'instant";
  if (minutes < 60) return minutes + " min";
  if (minutes < 1440) return Math.round(minutes / 60) + " h";
  return Math.round(minutes / 1440) + " j";
}

function canaux(rows, jours) {
  rendre($("canaux"), [rows, jours], () => remplirCanaux(rows, jours));
}

function remplirCanaux(rows, jours) {
  $("canaux-note").textContent = jours === 1 ? "24 h" : jours + " jours";
  tableau($("canaux"),
    [{ titre: "canal" }, { titre: "msg", classe: "n", largeur: "3.2rem" },
     { titre: "24 h", classe: "n", largeur: "3.2rem" },
     { titre: "pers.", classe: "n", largeur: "3.6rem" },
     { titre: "dernier", classe: "n", largeur: "5rem" }],
    rows,
    (c) => cellules([
      [nomCanal(c.thread), null, c.thread],
      [String(c.messages), "n"],
      [String(c.recent), c.recent ? "n etat-attention" : "n zero"],
      [String(c.people), "n"],
      [depuis(c.last), "n", new Date(c.last).toLocaleString("fr-CA")],
    ]),
    "Aucun message sur la période.");
}

function activite(data, jours) {
  const cible = $("activite");
  rendre(cible, [data.activity, jours], () => remplirActivite(cible, data, jours));
}

function remplirActivite(cible, data, jours) {
  const note = $("activite-note");
  const bloc = data.activity;
  if (!bloc || bloc.buckets.length === 0) {
    note.textContent = "";
    vide(cible, "Aucun run sur la période.");
    return;
  }
  const parHeure = bloc.unit === "hour";
  note.textContent = parHeure ? "par heure" : "par jour";

  // The axis is the chosen period, not the span that happens to hold data: a week
  // with one run must read as a quiet week, not as one busy day.
  const pas = parHeure ? 3600e3 : 86400e3;
  const vus = new Map(bloc.buckets.map((b) => [Math.floor(Date.parse(b.t) / pas), b]));
  const fin = Math.floor(Date.now() / pas);
  const debut = fin - (parHeure ? 24 : jours) + 1;
  const suite = [];
  for (let k = debut; k <= fin; k += 1) {
    suite.push(vus.get(k) || { t: new Date(k * pas).toISOString(), runs: 0, failures: 0 });
  }
  const sommet = Math.max(...suite.map((b) => b.runs), 1);

  const histo = el("div", "histo");
  // A term's worth of days needs thinner gutters than a day's worth of hours.
  if (suite.length > 80) histo.style.gap = "1px";
  for (const b of suite) {
    const colonne = el("div", "colonne");
    const date = new Date(b.t);
    colonne.title = (parHeure
      ? deux(date.getHours()) + " h"
      : date.toLocaleDateString("fr-CA"))
      + " : " + b.runs + " run(s), " + b.failures + " échec(s)";
    if (!b.runs) {
      colonne.append(el("span", "part creux"));
    } else {
      const hauteur = (n) => "max(1px, " + (n / sommet) * 100 + "%)";
      if (b.failures) {
        const rates = el("span", "part rate");
        rates.style.height = hauteur(b.failures);
        colonne.append(rates);
      }
      if (b.runs - b.failures) {
        const reussis = el("span", "part reussi");
        reussis.style.height = hauteur(b.runs - b.failures);
        colonne.append(reussis);
      }
    }
    histo.append(colonne);
  }

  const axe = el("div", "axe");
  const borne = (b) => {
    const d = new Date(b.t);
    return parHeure ? deux(d.getHours()) + " h"
      : d.toLocaleDateString("fr-CA", { month: "short", day: "numeric" });
  };
  axe.append(el("span", null, borne(suite[0])),
             el("span", null, "max " + sommet),
             el("span", null, borne(suite[suite.length - 1])));
  cible.textContent = "";
  cible.append(histo, axe);
}

let connus = null;

function runs(rows) {
  const cible = $("runs");
  if (rows === null || rows === undefined) {
    rendre(cible, "panne", () => vide(cible,
      "La base n'a pas répondu pour les runs. Si les autres panneaux sont remplis, "
      + "c'est que le schéma n'est pas à jour : applique app/schema.sql."));
    return;
  }
  rendre(cible, rows, () => remplirRuns(cible, rows));
}

function remplirRuns(cible, rows) {
  tableau(cible,
    [{ titre: "fini", classe: "mono", largeur: "5.9rem" },
     { titre: "exercice", largeur: "11rem" }, { titre: "statut", largeur: "9rem" },
     { titre: "mode", largeur: "4rem" },
     { titre: "durée", classe: "n", largeur: "4.4rem" },
     { titre: "attente", classe: "n", largeur: "4.8rem" },
     { titre: "worker", classe: "n", largeur: "4rem" },
     ...(revele() ? [{ titre: "auteur", largeur: "10rem" }] : []),
     { titre: "code", largeur: "4rem" },
     { titre: "job", classe: "mono" }],
    rows,
    (r) => {
      const tr = cellules([
        [horloge(r.finished_at), "mono"],
        [texte(r.exercise_id), null, r.exercise_id],
        [texte(r.status), classeEtat(r.status)],
        [texte(r.kind), r.cache_hit ? "cache" : null,
         r.cache_hit ? "servi par le cache, sans compiler" : null],
        [secondes(r.duration_s), "n"],
        [secondes(r.queue_wait_s), "n"],
        [texte(r.worker_id), "n mono"],
        ...(revele()
          ? [[r.account || "anonyme", r.account ? "compte" : "compte zero",
              r.account || "aucun compte"]]
          : []),
        [r.exercise_id && !r.exercise_id.startsWith(":") ? "voir" : "–",
         r.exercise_id && !r.exercise_id.startsWith(":") ? "voir" : "zero"],
        [r.job_id, "mono", r.job_id],
      ]);
      if (r.exercise_id && !r.exercise_id.startsWith(":")) {
        tr.cells[tr.cells.length - 2].addEventListener("click", () => void montrerCode(r));
      }
      if (connus && !connus.has(r.job_id)) tr.className = "neuf";
      return tr;
    },
    "Aucun run enregistré.");
  if (rows) connus = new Set(rows.map((r) => r.job_id));
}

/* ---- personal data ------------------------------------------------------ */

const revele = () => $("reveler").checked;

// Le compte n'est pas seulement cache : le serveur ne l'envoie que sur demande.
function parametresRuns() {
  const params = new URLSearchParams({ limit: "150" });
  if (revele()) params.set("reveal", "1");
  const champs = { exercise: "f-exercice", status: "f-statut", worker: "f-worker" };
  for (const [cle, id] of Object.entries(champs)) {
    const valeur = $(id).value.trim();
    if (valeur) params.set(cle, valeur);
  }
  return params;
}

const SOURCES = {
  run: "le code de ce run",
  dernier: "dernier code soumis pour cet exercice",
};

async function montrerCode(r) {
  const boite = $("code");
  $("code-titre").textContent = r.exercise_id;
  $("code-source").textContent = "chargement…";
  $("code-corps").textContent = "";
  boite.showModal();
  const params = new URLSearchParams({ job_id: r.job_id, exercise_id: r.exercise_id });
  if (r.account) params.set("account", r.account);
  let bloc;
  try {
    bloc = await json("/api/code?" + params);
  } catch (err) {
    $("code-source").textContent = err.message;
    return;
  }
  const noms = Object.keys(bloc.files || {});
  if (!noms.length) {
    // Le spool est balaye apres 600 s, et rien n'est garde pour un run jamais sonde.
    $("code-source").textContent = "plus disponible";
    $("code-corps").append(el("p", "vide",
      "Ce run est trop ancien pour le spool, et aucun code soumis n'est enregistré "
      + "pour ce compte sur cet exercice."));
    return;
  }
  const quand = bloc.at ? new Date(bloc.at).toLocaleString("fr-CA") : "";
  $("code-source").textContent = (SOURCES[bloc.source] || "") + (quand ? ", " + quand : "");
  for (const nom of noms) {
    $("code-corps").append(el("div", "fichier", nom));
    // textContent, jamais innerHTML : ce texte vient d'un etudiant et cette page
    // detient un jeton de moderateur.
    $("code-corps").append(el("pre", null, bloc.files[nom]));
  }
}

/* ---- state line -------------------------------------------------------- */

function etat(message, niveau) {
  const ligne = $("etat");
  $("etat-texte").textContent = message;
  ligne.classList.toggle("casse", niveau === "casse");
  ligne.classList.toggle("tiede", niveau === "tiede");
}

/* ---- loading ----------------------------------------------------------- */

function periode() {
  const actif = document.querySelector('.periode button[aria-pressed="true"]');
  return Number(actif ? actif.dataset.jours : 7);
}

// Une requete par lot a la fois. Le cout de /api/stats croit avec la periode, et sur
// la plus longue une requete peut depasser le tick : le tableau ralentit alors a la
// vitesse reelle de la base au lieu d'empiler des requetes.
let enVol = { apercu: false, stats: false };

async function rafraichir() {
  if (enVol.apercu) return;
  enVol.apercu = true;
  try {
    const data = await json("/api/overview");
    vitaux(data);
    workers(data.workers, data.queue && data.queue.workers_configured);
    file(data.queue);
    const ingestion = data.ingestion;
    if (data.degraded) {
      etat("Base injoignable, file et contenu seulement", "tiede");
    } else if (ingestion && ingestion.ok === false) {
      etat("Le journal ne s'ingère plus" + (ingestion.depuis
        ? " depuis " + duree((Date.now() / 1000) - ingestion.depuis) : "")
        + " — aucun nouveau run n'arrivera", "casse");
    } else {
      etat("À jour " + new Date().toLocaleTimeString("fr-CA"));
    }
  } catch (err) {
    etat("Rafraîchissement impossible : " + err.message, "casse");
  }
  try {
    await listeRuns();
  } finally {
    enVol.apercu = false;
  }
}

async function statistiques() {
  if (enVol.stats) return;
  enVol.stats = true;
  const jours = periode();
  try {
    const data = await json("/api/stats?days=" + jours);
    repartition(data.statuses);
    exercices(data.exercises, jours);
    canaux(data.channels, jours);
    activite(data, jours);
    usage(data, jours);
  } catch (err) {
    etat("Statistiques indisponibles : " + err.message, "casse");
  } finally {
    enVol.stats = false;
  }
}

async function listeRuns() {
  try {
    const reponse = await json("/api/runs?" + parametresRuns());
    runs(reponse.runs);
    if (reponse.degraded) etat("Les runs ne remontent pas de la base", "tiede");
  } catch (err) {
    etat("Runs indisponibles : " + err.message, "casse");
  }
}

for (const bouton of document.querySelectorAll(".periode button")) {
  bouton.addEventListener("click", () => {
    for (const autre of document.querySelectorAll(".periode button")) {
      autre.removeAttribute("aria-pressed");
    }
    bouton.setAttribute("aria-pressed", "true");
    statistiques();
  });
}

for (const id of ["f-exercice", "f-statut", "f-worker"]) {
  let minuteur;
  $(id).addEventListener("input", () => {
    clearTimeout(minuteur);
    minuteur = setTimeout(listeRuns, 250);
  });
}

// Un seul tick pour tout : pendant un laboratoire on suit l'activite en direct, et la
// periode selectionnee est alors « 24 h », ou les agregats sont triviaux.
function tic() {
  if (document.hidden) return;
  void rafraichir();
  void statistiques();
}

// Un onglet en arriere-plan ne demande rien ; au retour on rafraichit tout de suite
// plutot que d'attendre le prochain tick.
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) tic();
});

$("reveler").addEventListener("change", () => {
  // La signature change avec la colonne : le tableau doit se reconstruire.
  $("runs").dataset.signature = "";
  void listeRuns();
});

$("code-fermer").addEventListener("click", () => $("code").close());

$("connexion-bouton").addEventListener("click", () => {
  void connecter().catch((err) => ecranConnexion(err.message));
});

// La page se sert sans jeton ; c'est ici qu'on decide de montrer le tableau ou
// l'ecran de connexion.
demarrer().then((porteur) => {
  if (!porteur) {
    ecranConnexion("");
    return;
  }
  document.body.classList.remove("deconnecte");
  tic();
  minuterie = setInterval(tic, RAFRAICHIR);
}, (err) => ecranConnexion(err.message));
