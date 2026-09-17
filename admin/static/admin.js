// No build step and no dependency: the dashboard is small enough to stay plain.

const $ = (id) => document.getElementById(id);
const RAFRAICHIR = 5000;

const COULEURS = {
  ok: "var(--ok)",
  compile_error: "var(--alerte)",
  link_error: "var(--alerte)",
  forbidden_include: "var(--alerte)",
  compile_timeout: "var(--attente)",
  timeout: "var(--attente)",
  memory_error: "var(--attente)",
  error: "var(--faible)",
};

const texte = (v) => (v === null || v === undefined || v === "" ? "—" : String(v));
const secondes = (v) => (typeof v === "number" ? v.toFixed(1) + " s" : "—");

function duree(s) {
  if (typeof s !== "number") return "—";
  if (s < 60) return Math.round(s) + " s";
  if (s < 3600) return Math.round(s / 60) + " min";
  return Math.round(s / 3600) + " h";
}

function carte(cle, valeur, note, classe) {
  const el = document.createElement("div");
  el.className = "carte";
  const k = document.createElement("div");
  k.className = "cle";
  k.textContent = cle;
  const v = document.createElement("div");
  v.className = "valeur" + (classe ? " " + classe : "");
  v.textContent = valeur;
  el.append(k, v);
  if (note) {
    const n = document.createElement("div");
    n.className = "note";
    n.textContent = note;
    el.append(n);
  }
  return el;
}

function vide(message) {
  const el = document.createElement("p");
  el.className = "vide";
  el.textContent = message;
  return el;
}

function tableau(colonnes, lignes, rendu) {
  if (!lignes || lignes.length === 0) {
    return vide("Rien à montrer.");
  }
  const enveloppe = document.createElement("div");
  enveloppe.className = "enveloppe";
  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const tr = document.createElement("tr");
  for (const col of colonnes) {
    const th = document.createElement("th");
    th.textContent = col;
    tr.append(th);
  }
  thead.append(tr);
  const tbody = document.createElement("tbody");
  for (const ligne of lignes) tbody.append(rendu(ligne));
  table.append(thead, tbody);
  enveloppe.append(table);
  return enveloppe;
}

function cellules(valeurs) {
  const tr = document.createElement("tr");
  for (const v of valeurs) {
    const td = document.createElement("td");
    if (Array.isArray(v)) {
      td.textContent = v[0];
      if (v[1]) td.className = v[1];
    } else {
      td.textContent = v;
    }
    tr.append(td);
  }
  return tr;
}

async function json(url) {
  const reponse = await fetch(url, { headers: { accept: "application/json" } });
  if (!reponse.ok) throw new Error(reponse.status + " " + reponse.statusText);
  return reponse.json();
}

function bandeau(data) {
  const cible = $("bandeau");
  cible.textContent = "";
  const q = data.queue;
  const r = data.release;
  const s = data.stats;
  if (q) {
    cible.append(carte("En file", q.pending,
      q.pending ? "plus ancien : " + duree(q.oldest_s) : "rien en attente"));
    cible.append(carte("Attente estimée", duree(q.eta_s),
      q.workers_configured + " worker(s) configuré(s)"));
  }
  if (s) {
    const taux = s.total ? Math.round((s.cache_hits / s.total) * 100) : 0;
    cible.append(carte("Runs (24 h)", s.total, s.ok + " réussis"));
    cible.append(carte("Cache", taux + " %", s.cache_hits + " servis sans compiler"));
    cible.append(carte("Reprises", s.reprises,
      s.reprises ? "un worker a été interrompu" : "aucune interruption",
      s.reprises ? "statut-ko" : ""));
  }
  if (r) {
    const quand = r.published_at
      ? new Date(r.published_at * 1000).toLocaleString("fr-CA")
      : "—";
    cible.append(carte("Contenu publié", r.revision ? r.revision.slice(0, 12) : "—",
      quand + (r.exercises ? " · " + r.exercises + " exercices" : "")));
  }
}

function workers(rows) {
  const cible = $("workers");
  cible.textContent = "";
  if (!rows || rows.length === 0) {
    cible.append(vide("Aucun run enregistré depuis 24 h."));
    return;
  }
  for (const w of rows) {
    const el = carte("worker " + w.worker_id, w.runs + " runs",
      "moyenne " + secondes(w.average_s)
      + (w.failures ? " · " + w.failures + " échecs" : ""));
    const pastille = document.createElement("span");
    pastille.className = "pastille " + (w.alive ? "vivant" : "mort");
    pastille.title = w.alive ? "actif" : "silencieux depuis 5 min";
    el.querySelector(".cle").prepend(pastille);
    cible.append(el);
  }
}

function file(q) {
  const cible = $("file");
  cible.textContent = "";
  cible.append(tableau(["job", "exercice", "compte", "attente"], q && q.head,
    (j) => cellules([
      j.job_id.slice(0, 12),
      texte(j.exercise_id),
      j.signed_in ? "connecté" : "anonyme",
      duree(j.waiting_s),
    ])));
}

function barre(statuses, total) {
  const el = document.createElement("div");
  el.className = "barre";
  for (const s of statuses) {
    const part = document.createElement("span");
    part.style.width = (s.count / total) * 100 + "%";
    part.style.background = COULEURS[s.status] || "var(--faible)";
    part.title = s.status + " : " + s.count;
    el.append(part);
  }
  return el;
}

function legende(statuses) {
  const el = document.createElement("div");
  el.className = "legende";
  for (const st of statuses) {
    const item = document.createElement("span");
    const puce = document.createElement("span");
    puce.className = "puce";
    puce.style.background = COULEURS[st.status] || "var(--faible)";
    const compte = document.createElement("b");
    compte.textContent = st.count;
    item.append(puce, document.createTextNode(st.status + " "), compte);
    el.append(item);
  }
  return el;
}

function stats(data) {
  const cible = $("stats");
  cible.textContent = "";
  const s = data.stats;
  if (data.usage) {
    const cartes = document.createElement("div");
    cartes.className = "cartes";
    cartes.append(carte("Exercices résolus", data.usage.solved, "tous comptes confondus"));
    cartes.append(carte("Comptes actifs", data.usage.active_accounts, "sur la période"));
    cartes.append(carte("XP distribué", data.usage.xp, "sur la période"));
    if (s) {
      cartes.append(carte("Attente moyenne", secondes(s.average_wait_s),
        "avant le premier worker"));
    }
    cible.append(cartes);
  }
  const statuses = data.statuses || [];
  const total = statuses.reduce((n, st) => n + st.count, 0);
  if (total) {
    cible.append(barre(statuses, total));
    cible.append(legende(statuses));
  }
  const titre = document.createElement("h2");
  titre.textContent = "Par exercice";
  cible.append(titre);
  cible.append(tableau(["exercice", "runs", "échecs", "moyenne", "p95"], data.exercises,
    (e) => cellules([
      e.exercise_id,
      [String(e.runs), "n"],
      [String(e.failures), e.failures ? "n statut-ko" : "n"],
      [secondes(e.average_s), "n"],
      [secondes(e.p95_s), "n"],
    ])));
}

function runs(rows) {
  const cible = $("runs");
  cible.textContent = "";
  cible.append(tableau(
    ["fini", "exercice", "statut", "mode", "durée", "attente", "worker", "cache"],
    rows, (r) => cellules([
      new Date(r.finished_at).toLocaleTimeString("fr-CA"),
      texte(r.exercise_id),
      [texte(r.status), r.status === "ok" ? "statut-ok" : "statut-ko"],
      texte(r.kind),
      [secondes(r.duration_s), "n"],
      [secondes(r.queue_wait_s), "n"],
      texte(r.worker_id),
      r.cache_hit ? "oui" : "",
    ])));
}

function etat(message, casse) {
  const el = $("etat");
  el.textContent = message;
  el.classList.toggle("casse", Boolean(casse));
}

async function rafraichir() {
  try {
    const data = await json("/api/overview");
    bandeau(data);
    workers(data.workers);
    file(data.queue);
    etat(data.degraded
      ? "Base de données injoignable — file et contenu seulement."
      : "À jour " + new Date().toLocaleTimeString("fr-CA"), data.degraded);
  } catch (err) {
    etat("Rafraîchissement impossible : " + err.message, true);
  }
}

async function listeRuns() {
  const params = new URLSearchParams({ limit: "100" });
  const champs = { exercise: "f-exercice", status: "f-statut", worker: "f-worker" };
  for (const [cle, id] of Object.entries(champs)) {
    const valeur = $(id).value.trim();
    if (valeur) params.set(cle, valeur);
  }
  try {
    runs((await json("/api/runs?" + params)).runs);
  } catch (err) {
    etat("Runs indisponibles : " + err.message, true);
  }
}

async function recharger() {
  try {
    stats(await json("/api/stats?days=" + encodeURIComponent($("jours").value)));
  } catch (err) {
    etat("Statistiques indisponibles : " + err.message, true);
  }
  await listeRuns();
}

$("jours").addEventListener("change", recharger);
for (const id of ["f-exercice", "f-statut", "f-worker"]) {
  let minuteur;
  $(id).addEventListener("input", () => {
    clearTimeout(minuteur);
    minuteur = setTimeout(listeRuns, 300);
  });
}

rafraichir();
recharger();
setInterval(rafraichir, RAFRAICHIR);
