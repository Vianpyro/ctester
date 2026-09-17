// No build step and no dependency: the dashboard is small enough to stay plain.

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

async function json(url) {
  const reponse = await fetch(url, { headers: { accept: "application/json" } });
  if (!reponse.ok) throw new Error(reponse.status + " " + reponse.statusText);
  return reponse.json();
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
  cible.textContent = "";
  const q = data.queue;
  const s = data.stats;
  const r = data.release;

  if (q) {
    cible.append(vital("En file", q.pending,
      q.pending ? "plus ancien " + duree(q.oldest_s) : "rien en attente"));
    cible.append(vital("Attente estimée", duree(q.eta_s),
      q.pending ? "avant le dernier job" : "file libre"));
  }
  if (s) {
    const taux = s.total ? Math.round((s.cache_hits / s.total) * 100) : 0;
    cible.append(vital("Runs 24 h", s.total,
      s.total ? s.ok + " réussis" : "aucun run"));
    cible.append(vital("Cache", taux + " %", s.cache_hits + " sans compiler"));
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
    ["Réussite", data.stats && data.stats.total
      ? Math.round((data.stats.ok / data.stats.total) * 100) + " %"
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
  $("exercices-note").textContent = jours === 1 ? "24 h" : jours + " jours";
  tableau($("exercices"),
    [{ titre: "exercice" }, { titre: "runs", classe: "n", largeur: "3.2rem" },
     { titre: "échecs", classe: "n", largeur: "3.8rem" },
     { titre: "moy.", classe: "n", largeur: "3.6rem" },
     { titre: "p95", classe: "n", largeur: "3.4rem" }],
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

let connus = null;

function runs(rows) {
  const cible = $("runs");
  tableau(cible,
    [{ titre: "fini", classe: "mono", largeur: "5.9rem" },
     { titre: "exercice", largeur: "11rem" }, { titre: "statut", largeur: "9rem" },
     { titre: "mode", largeur: "4rem" },
     { titre: "durée", classe: "n", largeur: "4.4rem" },
     { titre: "attente", classe: "n", largeur: "4.8rem" },
     { titre: "worker", classe: "n", largeur: "4rem" },
     { titre: "job", classe: "mono" }],
    rows,
    (r) => {
      const tr = cellules([
        [horloge(r.finished_at), "mono"],
        [texte(r.exercise_id), null, r.exercise_id],
        [texte(r.status), classeEtat(r.status)],
        r.cache_hit ? "cache" : texte(r.kind),
        [secondes(r.duration_s), "n"],
        [secondes(r.queue_wait_s), "n"],
        [texte(r.worker_id), "n mono"],
        [r.job_id, "mono", r.job_id],
      ]);
      if (connus && !connus.has(r.job_id)) tr.className = "neuf";
      return tr;
    },
    "Aucun run enregistré.");
  if (rows) connus = new Set(rows.map((r) => r.job_id));
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

async function rafraichir() {
  try {
    const data = await json("/api/overview");
    vitaux(data);
    workers(data.workers, data.queue && data.queue.workers_configured);
    file(data.queue);
    etat(data.degraded
      ? "Base injoignable, file et contenu seulement"
      : "À jour " + new Date().toLocaleTimeString("fr-CA"),
      data.degraded ? "tiede" : null);
  } catch (err) {
    etat("Rafraîchissement impossible : " + err.message, "casse");
  }
  await listeRuns();
}

async function statistiques() {
  const jours = periode();
  try {
    const data = await json("/api/stats?days=" + jours);
    repartition(data.statuses);
    exercices(data.exercises, jours);
    usage(data, jours);
  } catch (err) {
    etat("Statistiques indisponibles : " + err.message, "casse");
  }
}

async function listeRuns() {
  const params = new URLSearchParams({ limit: "150" });
  const champs = { exercise: "f-exercice", status: "f-statut", worker: "f-worker" };
  for (const [cle, id] of Object.entries(champs)) {
    const valeur = $(id).value.trim();
    if (valeur) params.set(cle, valeur);
  }
  try {
    runs((await json("/api/runs?" + params)).runs);
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

rafraichir();
statistiques();
setInterval(rafraichir, RAFRAICHIR);
