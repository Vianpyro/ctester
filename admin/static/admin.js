// No build step and no dependency: the dashboard is small enough to stay plain.

import { connect, start, validToken, forget } from "/auth.js";

const $ = (id) => document.getElementById(id);
const REFRESH = 5000;

// A verdict's colour says who should care. A student whose code does not compile
// is the course working as intended, so it stays neutral; amber is a resource
// limit, which can mean a badly calibrated exercise; red is the judge itself.
const STATES = {
  ok: "ok",
  compile_error: "neutral",
  link_error: "neutral",
  forbidden_include: "neutral",
  compile_timeout: "attention",
  timeout: "attention",
  memory_error: "attention",
  error: "alert",
  console: "console",
};

const stateClass = (status) => "state-" + (STATES[status] || "neutral");
const stateColor = (status) => "var(--" + (STATES[status] || "neutral") + ")";

const pad2 = (n) => String(n).padStart(2, "0");

function clock(iso) {
  const d = new Date(iso);
  return pad2(d.getHours()) + ":" + pad2(d.getMinutes()) + ":" + pad2(d.getSeconds());
}

const text = (v) => (v === null || v === undefined || v === "" ? "–" : String(v));

function seconds(v) {
  if (typeof v !== "number") return "–";
  if (v >= 60) return Math.round(v / 60) + " min";
  return (v >= 10 ? Math.round(v) : v.toFixed(1)) + " s";
}

function duration(s) {
  if (typeof s !== "number") return "–";
  if (s < 60) return Math.round(s) + " s";
  if (s < 3600) return Math.round(s / 60) + " min";
  return Math.round(s / 3600) + " h";
}

function el(tag, cls, content) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (content !== undefined) node.textContent = content;
  return node;
}

function showEmpty(target, message) {
  target.textContent = "";
  target.append(el("p", "empty", message));
}

// Rebuilding a panel scrolls it back to the top: only do it when the data really
// changed, and put the reader back where they were when it happens.
function render(target, data, fill) {
  const signature = JSON.stringify(data);
  if (target.dataset.signature === signature) return;
  const top = target.scrollTop;
  fill();
  target.dataset.signature = signature;
  // ponytail: rows inserted at the top shift what this position shows; anchoring
  // on a row id would be exact and noticeably heavier.
  target.scrollTop = top;
}

async function json(url) {
  const bearer = await validToken();
  if (!bearer) throw new Error("session expirée");
  const response = await fetch(url, {
    headers: { accept: "application/json", authorization: "Bearer " + bearer },
  });
  // 401: the token died despite the renewal, a new login is needed.
  if (response.status === 401) {
    forget();
    loginScreen("Session expirée.");
    throw new Error("session expirée");
  }
  if (response.status === 403) {
    loginScreen("Ce compte n'est pas enseignant.");
    throw new Error("réservé à l'enseignant");
  }
  if (response.status === 503) {
    const said = await response.json().catch(() => ({}));
    loginScreen(said.error || "Service indisponible.");
    throw new Error(said.error || "service indisponible");
  }
  if (!response.ok) throw new Error(response.status + " " + response.statusText);
  return response.json();
}

let refreshTimer = null;

function loginScreen(reason) {
  if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }
  document.body.classList.add("loggedout");
  $("login-reason").textContent = reason || "";
}

/* ---- vitals ------------------------------------------------------------ */

function vital(key, value, note, options = {}) {
  const node = el("div", "vital");
  node.append(el("div", "key", key));
  const v = el("div", "value" + (options.mono ? " mono" : "") + (options.alarm ? " alarm" : ""),
               value);
  node.append(v, el("div", "note", note || " "));
  return node;
}

function vitals(data) {
  const target = $("vitals");
  render(target, [data.queue, data.stats, data.release, data.windows],
         () => fillVitals(target, data));
}

function fillVitals(target, data) {
  target.textContent = "";
  const q = data.queue;
  const s = data.stats;
  const r = data.release;

  if (q) {
    const waiting = q.waiting === undefined ? q.pending : q.waiting;
    target.append(vital("En file", waiting,
      q.running ? q.running + " en cours de correction"
        : (waiting ? "plus ancien " + duration(q.oldest_s) : "rien en attente")));
    target.append(vital("Attente estimée", duration(q.eta_s),
      q.pending ? "avant le dernier job" : "file libre"));
  }
  if (data.windows) {
    const n = data.windows.open;
    target.append(vital("Fenêtres", n === null || n === undefined ? "–" : n,
      n === null || n === undefined ? "API injoignable" : "ouvertes, connecté ou non"));
  }
  if (s) {
    const notes = s.graded === undefined ? s.total : s.graded;
    const markFailed = notes ? Math.round((s.cache_hits / notes) * 100) : 0;
    target.append(vital("Runs 24 h", s.total,
      s.total ? s.ok + " réussis" : "aucun run"));
    target.append(vital("Cache", markFailed + " %",
      s.cache_hits + " sans compiler, sur " + notes + " notés"));
    target.append(vital("Attente moyenne", seconds(s.average_wait_s), "avant un worker"));
    target.append(vital("Reprises", s.reprises,
      s.reprises ? "un worker a été interrompu" : "aucune interruption",
      { alarm: s.reprises > 0 }));
  }
  if (r) {
    target.append(vital("Révision", r.revision ? r.revision.slice(0, 10) : "–",
      r.published_at
        ? new Date(r.published_at * 1000).toLocaleString("fr-CA",
            { dateStyle: "short", timeStyle: "short" })
          + (r.exercises ? ", " + r.exercises + " exercises" : "")
        : "aucune release",
      { mono: true }));
  }
}

/* ---- verdict distribution ---------------------------------------------- */

function distribution(statuses) {
  render($("legend"), statuses, () => fillDistribution(statuses));
}

function fillDistribution(statuses) {
  const gauge = $("gauge");
  const legend = $("legend");
  gauge.textContent = "";
  legend.textContent = "";
  const lines = statuses || [];
  const total = lines.reduce((n, s) => n + s.count, 0);
  if (!total) {
    legend.append(el("span", null, "Aucun verdict sur la période."));
    return;
  }
  for (const s of lines) {
    const part = el("span");
    part.style.width = (s.count / total) * 100 + "%";
    part.style.background = stateColor(s.status);
    part.title = s.status + " : " + s.count;
    gauge.append(part);

    const item = el("span");
    const chip = el("span", "chip");
    chip.style.background = stateColor(s.status);
    item.append(chip, document.createTextNode(s.status + " "), el("i", null, s.count));
    legend.append(item);
  }
}

/* ---- tables ------------------------------------------------------------ */

function fillTable(target, columns, lines, rendered, message) {
  if (!lines || lines.length === 0) {
    showEmpty(target, message);
    return;
  }
  const table = el("table");
  const colgroup = el("colgroup");
  for (const col of columns) {
    const c = el("col");
    if (col.width) c.style.width = col.width;
    colgroup.append(c);
  }
  table.append(colgroup);
  const tr = el("tr");
  for (const col of columns) {
    tr.append(el("th", col.cls || null, col.title));
  }
  const thead = el("thead");
  thead.append(tr);
  const tbody = el("tbody");
  for (const line of lines) tbody.append(rendered(line));
  table.append(thead, tbody);
  target.textContent = "";
  target.append(table);
}

// [text, class, tooltip] -- the third item carries what truncation hides.
function cells(values) {
  const tr = el("tr");
  for (const v of values) {
    const list = Array.isArray(v) ? v : [v];
    const td = el("td", list[1] || null, list[0]);
    if (list[2]) td.title = list[2];
    tr.append(td);
  }
  return tr;
}

/* ---- panels ------------------------------------------------------------ */

function workers(rows, configured) {
  const target = $("workers");
  render(target, [rows, configured], () => fillWorkers(target, rows, configured));
}

function fillWorkers(target, rows, configured) {
  const note = $("workers-note");
  if (!rows || rows.length === 0) {
    note.textContent = configured ? "0 sur " + configured : "";
    showEmpty(target, "Aucun run depuis 24 h.");
    return;
  }
  const alive = rows.filter((w) => w.alive).length;
  note.textContent = alive + " actif" + (alive > 1 ? "s" : "")
    + (configured ? " sur " + configured : "");
  target.textContent = "";
  const sorted = [...rows].sort((a, b) =>
    a.worker_id.localeCompare(b.worker_id, undefined, { numeric: true }));
  for (const w of sorted) {
    const line = el("div", "line");
    const point = el("span", w.alive ? "alive" : "dead");
    point.title = w.alive ? "a fini un run récemment" : "silencieux depuis 5 min";
    const right = el("div", "right");
    right.append(el("b", null, w.runs), document.createTextNode(" runs, "
      + seconds(w.average_s)));
    line.append(point, el("span", "name", "worker " + w.worker_id), right);
    if (w.failures) line.title = w.failures + " échec(s)";
    target.append(line);
  }
}

function usage(data, days) {
  const target = $("usage");
  render(target, [data.usage, data.stats, days], () => fillUsage(target, data, days));
}

function fillUsage(target, data, days) {
  $("usage-note").textContent = days === 1 ? "24 h" : days + " jours";
  if (!data.usage) {
    showEmpty(target, "Base de données injoignable.");
    return;
  }
  target.textContent = "";
  const grid = el("div", "usage");
  const pairs = [
    ["Résolus", data.usage.solved],
    ["Comptes", data.usage.active_accounts],
    ["XP", data.usage.xp],
    ["Réussite", data.stats && data.stats.graded
      ? Math.round((data.stats.ok / data.stats.graded) * 100) + " %"
      : "–"],
  ];
  for (const [key, value] of pairs) {
    const cell = el("div");
    cell.append(el("div", "key", key), el("div", "value", value));
    grid.append(cell);
  }
  target.append(grid);
}

function file(q) {
  const target = $("queue");
  render(target, q, () => fillQueue(target, q));
}

function fillQueue(target, q) {
  const head = (q && q.head) || [];
  $("queue-note").textContent = q && q.pending
    ? q.pending + " en attente" : "";
  fillTable(target,
    [{ title: "exercice" }, { title: "attente", cls: "n", width: "4.5rem" }],
    head,
    (j) => {
      const tr = cells([text(j.exercise_id), [duration(j.waiting_s), "n"]]);
      tr.title = (j.signed_in ? "connecté" : "anonyme") + ", job " + j.job_id.slice(-8);
      return tr;
    },
    "Rien en attente.");
}

function exercises(rows, days) {
  render($("exercises"), [rows, days], () => fillExercises(rows, days));
}

function fillExercises(rows, days) {
  $("exercises-note").textContent = days === 1 ? "24 h" : days + " jours";
  fillTable($("exercises"),
    [{ title: "exercice" }, { title: "runs", cls: "n", width: "3.2rem" },
     { title: "échecs", cls: "n", width: "3.8rem" },
     { title: "moy.", cls: "n", width: "4.2rem" },
     { title: "p95", cls: "n", width: "4.2rem" }],
    rows,
    (e) => cells([
      [e.exercise_id || "–", null, e.exercise_id],
      [String(e.runs), "n"],
      [String(e.failures), e.failures ? "n state-alert" : "n zero"],
      [seconds(e.average_s), "n"],
      [seconds(e.p95_s), "n"],
    ]),
    "Aucun run sur la période.");
}

/* ---- discussions ------------------------------------------------------- */

const CHAT = "@chat:";

function channelName(key) {
  if (key === CHAT + "general") return "# général";
  if (key.startsWith(CHAT)) return "# " + key.slice(CHAT.length);
  return key + " (privé)";
}

function since(iso) {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "à l'instant";
  if (minutes < 60) return minutes + " min";
  if (minutes < 1440) return Math.round(minutes / 60) + " h";
  return Math.round(minutes / 1440) + " j";
}

function channels(rows, days) {
  render($("channels"), [rows, days], () => fillChannels(rows, days));
}

function fillChannels(rows, days) {
  $("channels-note").textContent = days === 1 ? "24 h" : days + " jours";
  fillTable($("channels"),
    [{ title: "canal" }, { title: "msg", cls: "n", width: "3.2rem" },
     { title: "24 h", cls: "n", width: "3.2rem" },
     { title: "pers.", cls: "n", width: "3.6rem" },
     { title: "dernier", cls: "n", width: "5rem" }],
    rows,
    (c) => cells([
      [channelName(c.thread), null, c.thread],
      [String(c.messages), "n"],
      [String(c.recent), c.recent ? "n state-attention" : "n zero"],
      [String(c.people), "n"],
      [since(c.last), "n", new Date(c.last).toLocaleString("fr-CA")],
    ]),
    "Aucun message sur la période.");
}

function activity(data, days) {
  const target = $("activity");
  render(target, [data.activity, days], () => fillActivity(target, data, days));
}

function fillActivity(target, data, days) {
  const note = $("activity-note");
  const cell = data.activity;
  if (!cell || cell.buckets.length === 0) {
    note.textContent = "";
    showEmpty(target, "Aucun run sur la période.");
    return;
  }
  const byHour = cell.unit === "hour";
  note.textContent = byHour ? "par heure" : "par jour";

  // The axis is the chosen period, not the span that happens to hold data: a week
  // with one run must read as a quiet week, not as one busy day.
  const step = byHour ? 3600e3 : 86400e3;
  const seen = new Map(cell.buckets.map((b) => [Math.floor(Date.parse(b.t) / step), b]));
  const end = Math.floor(Date.now() / step);
  const first = end - (byHour ? 24 : days) + 1;
  const series = [];
  for (let k = first; k <= end; k += 1) {
    series.push(seen.get(k) || { t: new Date(k * step).toISOString(), runs: 0, failures: 0 });
  }
  const peak = Math.max(...series.map((b) => b.runs), 1);

  const histogram = el("div", "histogram");
  // A term's worth of days needs thinner gutters than a day's worth of hours.
  if (series.length > 80) histogram.style.gap = "1px";
  for (const b of series) {
    const column = el("div", "column");
    const date = new Date(b.t);
    column.title = (byHour
      ? pad2(date.getHours()) + " h"
      : date.toLocaleDateString("fr-CA"))
      + " : " + b.runs + " run(s), " + b.failures + " échec(s)";
    if (!b.runs) {
      column.append(el("span", "part hollow"));
    } else {
      const barHeight = (n) => "max(1px, " + (n / peak) * 100 + "%)";
      if (b.failures) {
        const failedBar = el("span", "part failed");
        failedBar.style.height = barHeight(b.failures);
        column.append(failedBar);
      }
      if (b.runs - b.failures) {
        const solved = el("span", "part solved");
        solved.style.height = barHeight(b.runs - b.failures);
        column.append(solved);
      }
    }
    histogram.append(column);
  }

  const axis = el("div", "axis");
  const edgeLabel = (b) => {
    const d = new Date(b.t);
    return byHour ? pad2(d.getHours()) + " h"
      : d.toLocaleDateString("fr-CA", { month: "short", day: "numeric" });
  };
  axis.append(el("span", null, edgeLabel(series[0])),
             el("span", null, "max " + peak),
             el("span", null, edgeLabel(series[series.length - 1])));
  target.textContent = "";
  target.append(histogram, axis);
}

let known = null;

function runs(rows) {
  const target = $("runs");
  if (rows === null || rows === undefined) {
    render(target, "panne", () => showEmpty(target,
      "La base n'a pas répondu pour les runs. Si les autres panneaux sont remplis, "
      + "c'est que le schéma n'est pas à jour : applique app/schema.sql."));
    return;
  }
  render(target, rows, () => fillRuns(target, rows));
}

// Null when the run never reached the tests: a compilation error, a timeout.
function testsCell(r) {
  if (r.passed == null || r.total == null) return ["–", "n zero"];
  const cls = r.passed === r.total ? "n state-ok" : "n state-neutral";
  return [r.passed + "/" + r.total, cls];
}

// An anonymous run carries a hash of its browser's station id: the same tag means the
// same browser, which tells two anonymous students apart.
function authorCell(r) {
  if (r.account) return [r.account, "count", r.account];
  if (r.station) {
    return ["anonyme · " + r.station, "count mono",
      "aucun compte ; même étiquette = même navigateur"];
  }
  return ["anonyme", "count zero", "aucun compte"];
}

function fillRuns(target, rows) {
  fillTable(target,
    [{ title: "fini", cls: "mono", width: "5.9rem" },
     { title: "exercice", width: "11rem" }, { title: "statut", width: "9rem" },
     { title: "mode", width: "4rem" },
     { title: "tests", cls: "n", width: "4rem" },
     { title: "durée", cls: "n", width: "4.4rem" },
     { title: "attente", cls: "n", width: "4.8rem" },
     { title: "worker", cls: "n", width: "4rem" },
     ...(revealed() ? [{ title: "auteur", width: "10rem" }] : []),
     { title: "code", width: "4rem" },
     { title: "job", cls: "mono" }],
    rows,
    (r) => {
      const tr = cells([
        [clock(r.finished_at), "mono"],
        [text(r.exercise_id), null, r.exercise_id],
        [text(r.status), stateClass(r.status)],
        [text(r.kind), r.cache_hit ? "cache" : null,
         r.cache_hit ? "servi par le cache, sans compiler" : null],
        testsCell(r),
        [seconds(r.duration_s), "n"],
        [seconds(r.queue_wait_s), "n"],
        [text(r.worker_id), "n mono"],
        ...(revealed() ? [authorCell(r)] : []),
        [r.exercise_id && !r.exercise_id.startsWith(":") ? "show" : "–",
         r.exercise_id && !r.exercise_id.startsWith(":") ? "show" : "zero"],
        [r.job_id, "mono", r.job_id],
      ]);
      if (r.exercise_id && !r.exercise_id.startsWith(":")) {
        tr.cells[tr.cells.length - 2].addEventListener("click", () => void showCode(r));
      }
      if (known && !known.has(r.job_id)) tr.className = "new";
      return tr;
    },
    "Aucun run enregistré.");
  if (rows) known = new Set(rows.map((r) => r.job_id));
}

/* ---- personal data ------------------------------------------------------ */

const revealed = () => $("reveal").checked;

// The account is not merely hidden: the server only sends it on request.
function runParams() {
  const params = new URLSearchParams({ limit: "150" });
  if (revealed()) params.set("reveal", "1");
  const fields = { exercise: "f-exercise", status: "f-status", worker: "f-worker" };
  for (const [key, id] of Object.entries(fields)) {
    const value = $(id).value.trim();
    if (value) params.set(key, value);
  }
  return params;
}

const SOURCES = {
  run: "le code de ce run",
  last: "dernier code soumis pour cet exercice",
};

async function showCode(r) {
  const box = $("code");
  $("code-title").textContent = r.exercise_id;
  $("code-source").textContent = "chargement…";
  $("code-body").textContent = "";
  box.showModal();
  const params = new URLSearchParams({ job_id: r.job_id, exercise_id: r.exercise_id });
  if (r.account) params.set("account", r.account);
  let cell;
  try {
    cell = await json("/api/code?" + params);
  } catch (err) {
    $("code-source").textContent = err.message;
    return;
  }
  const names = Object.keys(cell.files || {});
  if (!names.length) {
    // The spool is swept after 600 s, and nothing is kept for a run never polled.
    $("code-source").textContent = "plus disponible";
    $("code-body").append(el("p", "empty",
      "Ce run est trop ancien pour le spool, et aucun code soumis n'est enregistré "
      + "pour ce compte sur cet exercice."));
    return;
  }
  const when = cell.at ? new Date(cell.at).toLocaleString("fr-CA") : "";
  $("code-source").textContent = (SOURCES[cell.source] || "") + (when ? ", " + when : "");
  for (const name of names) {
    $("code-body").append(el("div", "file", name));
    // textContent, never innerHTML: this text comes from a student and this page
    // holds a moderator token.
    $("code-body").append(el("pre", null, cell.files[name]));
  }
}

/* ---- state line -------------------------------------------------------- */

function state(message, level) {
  const line = $("state");
  $("state-text").textContent = message;
  line.classList.toggle("broken", level === "broken");
  line.classList.toggle("warm", level === "warm");
}

/* ---- loading ----------------------------------------------------------- */

function period() {
  const active = document.querySelector('.period button[aria-pressed="true"]');
  return Number(active ? active.dataset.days : 7);
}

// One request per batch at a time. The cost of /api/stats grows with the period, and
// on the longest one a request can outlast the tick: the dashboard then slows to the
// database's real speed instead of piling up requests.
let inFlight = { preview: false, stats: false };

async function refresh() {
  if (inFlight.preview) return;
  inFlight.preview = true;
  try {
    const data = await json("/api/overview");
    vitals(data);
    workers(data.workers, data.queue && data.queue.workers_configured);
    file(data.queue);
    const ingestion = data.ingestion;
    if (data.degraded) {
      state("Base injoignable, file et contenu seulement", "warm");
    } else if (ingestion && ingestion.ok === false) {
      state("Le journal ne s'ingère plus" + (ingestion.since
        ? " depuis " + duration((Date.now() / 1000) - ingestion.since) : "")
        + " — aucun nouveau run n'arrivera", "broken");
    } else {
      state("À jour " + new Date().toLocaleTimeString("fr-CA"));
    }
  } catch (err) {
    state("Rafraîchissement impossible : " + err.message, "broken");
  }
  try {
    await listRuns();
  } finally {
    inFlight.preview = false;
  }
}

async function statistics() {
  if (inFlight.stats) return;
  inFlight.stats = true;
  const days = period();
  try {
    const data = await json("/api/stats?days=" + days);
    distribution(data.statuses);
    exercises(data.exercises, days);
    channels(data.channels, days);
    activity(data, days);
    usage(data, days);
  } catch (err) {
    state("Statistiques indisponibles : " + err.message, "broken");
  } finally {
    inFlight.stats = false;
  }
}

async function listRuns() {
  try {
    const response = await json("/api/runs?" + runParams());
    runs(response.runs);
    if (response.degraded) state("Les runs ne remontent pas de la base", "warm");
  } catch (err) {
    state("Runs indisponibles : " + err.message, "broken");
  }
}

for (const button of document.querySelectorAll(".period button")) {
  button.addEventListener("click", () => {
    for (const other of document.querySelectorAll(".period button")) {
      other.removeAttribute("aria-pressed");
    }
    button.setAttribute("aria-pressed", "true");
    statistics();
  });
}

for (const id of ["f-exercise", "f-status", "f-worker"]) {
  let resizeTimer;
  $(id).addEventListener("input", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(listRuns, 250);
  });
}

// A single tick for everything: during a lab the activity is followed live, and the
// selected period is then "24 h", where the aggregates are trivial.
function tick() {
  if (document.hidden) return;
  void refresh();
  void statistics();
}

// A background tab asks for nothing; on return it refreshes at once rather than
// waiting for the next tick.
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) tick();
});

$("reveal").addEventListener("change", () => {
  // The signature changes with the column: the table must be rebuilt.
  $("runs").dataset.signature = "";
  void listRuns();
});

$("code-close").addEventListener("click", () => $("code").close());

$("login-button").addEventListener("click", () => {
  void connect().catch((err) => loginScreen(err.message));
});

// The page is served without a token; this is where the dashboard or the login
// screen is chosen.
start().then((bearer) => {
  if (!bearer) {
    loginScreen("");
    return;
  }
  document.body.classList.remove("loggedout");
  tick();
  refreshTimer = setInterval(tick, REFRESH);
}, (err) => loginScreen(err.message));
