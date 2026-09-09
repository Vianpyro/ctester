// The team workspace: one assignment, one team, one shared document per
// exercise. Loaded ON DEMAND, and only when a signed-in student opens an
// exercise whose catalog entry says it belongs to an assignment -- so the
// anonymous path fetches none of it, and neither does anyone working an
// ordinary lab.
//
// THE CONVERGENCE IS YJS'S, THE AUTHORIZATION IS THE SERVER'S. This file
// holds a Y.Doc, sends the opaque updates it produces down a WebSocket, and
// applies the ones that come back. It invents no merge rule: four people
// typing in the same line is exactly the case a hand-rolled protocol gets
// wrong in week three, and Yjs is a proven implementation of it.
//
// WHAT THE SERVER RELAYS, IT DOES NOT READ. `app/services/collab.py` forwards
// these frames without parsing them and stamps the SENDER on each one from
// the roster -- so a caret cannot be attributed to somebody else by writing a
// different id, and a room cannot be joined by naming a different team.
//
// THE DURABLE COPY IS PLAIN TEXT. Every local edit is debounced into
// `PUT /team/document`, which validates the file names against the catalog
// like every other write in this application and coalesces a revision. What
// gets tested, exported and handed in is that text -- never a CRDT blob -- so
// nothing here can produce a hand-in the judge has not seen.
(function (ctester) {
const $ = ctester.$;

// PINNED IN THE NAME, in three places on purpose: here, `config.VENDOR`
// (which serves it) and `web/vendor/README.md` (which says how it was built).
const YJS = "vendor/yjs-13.6.32.iife.js";

// How long after the last keystroke the shared document is written to
// Postgres. The socket has already carried the change to the teammates; this
// is only about surviving a closed tab.
const SAVE_DELAY = 1500;
// Reconnection backoff, in milliseconds. Short enough that a laptop lid
// closed for a minute comes back on its own, long enough that a service being
// restarted is not hammered by four browsers.
const RETRY = [1000, 2000, 4000, 8000, 15000];

// The one code we can do something about ourselves: the token expired while
// the room was open, and renewing it is cheaper than telling someone to sign
// in again. See `connect`'s close handler.
const UNAUTHORIZED = 4401;

// The four close codes the server uses. A student whose session expired and a
// student who is not on a team must not both read "connection lost".
const CLOSED = {
  4401: "Ta session a expiré. Reconnecte-toi pour retrouver l'espace d'équipe.",
  4403: "Tu n'es pas inscrit à une équipe pour ce devoir.",
  4429: "Trop d'onglets ouverts sur cet exercice. Ferme-en un et réessaie.",
  4400: "L'espace d'équipe n'a pas pu démarrer. Recharge la page.",
};

let session = null;      // the open workspace, or null
let contexts = {};       // assignment id -> the /team/context payload
let history = null;      // the revisions panel's state, when it is open

function node(tag, className, text) {
  const n = document.createElement(tag);
  if (className) n.className = className;
  if (text !== undefined) n.textContent = text;
  return n;
}

// --- Bytes on the wire ---------------------------------------------------------
// Yjs speaks Uint8Array, the socket carries JSON. base64 rather than a binary
// frame, for one reason: the frames the server relays also carry a `from` it
// stamps itself, and a JSON envelope is what lets it do that without parsing
// -- or even understanding -- the payload inside.
const b64 = (bytes) => {
  let out = "";
  for (const byte of bytes) out += String.fromCharCode(byte);
  return btoa(out);
};
const unb64 = (text) => {
  const raw = atob(text);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return bytes;
};

// --- The document --------------------------------------------------------------
// ONE Y.Text PER FILE OF THE EXERCISE, named after the file. The names come
// from the catalog, which is the same allow-list `validate_files` checks
// server-side: a shared document can hold nothing the exercise does not
// declare.
const LOCAL = "local";   // the transaction origin that means "I typed this"

function textOf(doc, name) {
  return doc.getText("f:" + name);
}

// THE DIFF THAT TURNS A TEXTAREA INTO CRDT OPERATIONS. A keystroke, a paste
// and a selection replaced are all ONE contiguous change, which is what the
// common prefix and suffix find. Replacing the whole text instead -- delete
// everything, insert everything -- would technically converge and would
// destroy every teammate's caret on every keystroke.
function applyLocal(doc, ytext, next) {
  const previous = ytext.toString();
  if (previous === next) return false;
  const shortest = Math.min(previous.length, next.length);
  let start = 0;
  while (start < shortest && previous[start] === next[start]) start++;
  let tail = 0;
  while (tail < shortest - start
         && previous[previous.length - 1 - tail] === next[next.length - 1 - tail]) {
    tail++;
  }
  const removed = previous.length - start - tail;
  const inserted = next.slice(start, next.length - tail);
  doc.transact(() => {
    if (removed) ytext.delete(start, removed);
    if (inserted) ytext.insert(start, inserted);
  }, LOCAL);
  return true;
}

// WHERE THE CARET LANDS AFTER SOMEBODY ELSE'S CHANGE. The delta says what
// happened before it; this is the standard transform, and it is the whole
// reason a remote edit does not throw the typist to the end of the file.
function shift(delta, position) {
  let index = 0;
  let moved = position;
  for (const op of delta) {
    if (op.retain) {
      index += op.retain;
    } else if (typeof op.insert === "string") {
      if (index < moved) moved += op.insert.length;
      index += op.insert.length;
    } else if (op.delete) {
      if (index < moved) moved -= Math.min(op.delete, moved - index);
    }
    if (index > moved) break;
  }
  return Math.max(0, moved);
}

// --- Caret rendering -----------------------------------------------------------
// THE OVERLAY IS ALREADY THERE. `#hl` and `#code` share their metrics to the
// pixel (see the note in style.css), so a caret is arithmetic on a character
// width measured once -- not a second copy of the document in the DOM, which
// is what four remote carets over a 64 KB file would have cost on every
// keystroke.
let metrics = null;

function measure() {
  const zone = ctester.editeur.zone();
  const style = window.getComputedStyle ? window.getComputedStyle(zone) : null;
  const probe = node("span", "", "0".repeat(50));
  // `setAttribute("style", …)` AND NOT `.style.x = …`, like every computed
  // style in this page (see `progres.js`'s gauges). One way of writing it,
  // and the one the CSP's `style-src 'unsafe-inline'` already covers.
  probe.setAttribute("style",
    "position:absolute;visibility:hidden;white-space:pre"
    + (style ? ";font:" + style.font : ""));
  (zone.parentNode || document.body).append(probe);
  const box = probe.getBoundingClientRect ? probe.getBoundingClientRect() : null;
  probe.remove();
  const line = style ? parseFloat(style.lineHeight) : 0;
  const padTop = style ? parseFloat(style.paddingTop) : 0;
  const padLeft = style ? parseFloat(style.paddingLeft) : 0;
  metrics = {
    char: box && box.width ? box.width / 50 : 0,
    line: line || 0,
    top: padTop || 0,
    left: padLeft || 0,
  };
  return metrics;
}

function rowColumn(text, offset) {
  const before = text.slice(0, Math.max(0, offset));
  const rows = before.split("\n");
  return { row: rows.length - 1, column: rows[rows.length - 1].length };
}

// WHERE A (COLUMN, ROW) LANDS IN THE OVERLAY. One function, so a caret and
// the selection band under it can never disagree about the same position.
function place(box, zone, column, row) {
  return "left:" + (box.left + column * box.char - (zone.scrollLeft || 0)) + "px;"
       + "top:" + (box.top + row * box.line - (zone.scrollTop || 0)) + "px;";
}

function renderCarets() {
  const layer = $("carets");
  if (!layer || !session) return;
  layer.innerHTML = "";
  const active = ctester.editeur.fichierActif();
  const zone = ctester.editeur.zone();
  const box = metrics || measure();
  // NO METRICS MEANS NO CARETS, and that is a deliberate silence: a caret
  // drawn at the wrong place is worse than none at all -- it points at a line
  // its owner is not on. `getBoundingClientRect` returns zeros in a headless
  // DOM, which is exactly where this must not throw.
  if (!box.char || !box.line) return;
  const text = ctester.editeur.lire(active);
  for (const member of session.members) {
    const caret = session.carets[member.id];
    if (member.you || !caret || caret.file !== active) continue;
    const at = rowColumn(text, caret.head);
    const mark = node("i", "caret");
    mark.setAttribute("style", place(box, zone, at.column, at.row)
      + "height:" + box.line + "px;background:" + member.color);
    // THE NAME RIDES ON THE CARET, in the same colour: two carets a line
    // apart are otherwise two identical slivers. `textContent`, like
    // everything else that comes from another account.
    const tag = node("b", "caretname", member.name);
    tag.setAttribute("style", "background:" + member.color);
    mark.append(tag);
    layer.append(mark);
    // THE SELECTION, one band per line, and only when there is one. Drawn as
    // rectangles rather than as text ranges: the overlay is a `<pre>` with
    // `white-space: pre`, so a line's width in characters is all it takes.
    if (caret.anchor !== caret.head) {
      const from = rowColumn(text, Math.min(caret.anchor, caret.head));
      const to = rowColumn(text, Math.max(caret.anchor, caret.head));
      const lines = text.split("\n");
      for (let row = from.row; row <= to.row && row < lines.length; row++) {
        const startColumn = row === from.row ? from.column : 0;
        const endColumn = row === to.row ? to.column : lines[row].length;
        if (endColumn <= startColumn) continue;
        const band = node("i", "sel");
        band.setAttribute("style", place(box, zone, startColumn, row)
          + "width:" + ((endColumn - startColumn) * box.char) + "px;"
          + "height:" + box.line + "px;background:" + member.color);
        layer.append(band);
      }
    }
  }
}

// --- The socket ----------------------------------------------------------------


function send(payload) {
  if (session && session.socket && session.socket.readyState === 1) {
    session.socket.send(JSON.stringify(payload));
  }
}

async function connect(live) {
  // THE TOKEN GOES IN THE FIRST FRAME, so it has to still be good BEFORE the
  // socket opens: a room refused on 4401 costs a full round trip and a
  // reconnection, where renewing here costs nothing when the token is fresh.
  await ctester.jetonValide();
  if (session !== live) return;     // the workspace closed while we waited
  let socket;
  try {
    socket = new WebSocket(ctester.socketUrl("/team/live"));
  } catch (e) {
    return retry(live);
  }
  live.socket = socket;
  socket.onopen = () => {
    // THE TOKEN GOES IN THE FIRST FRAME, NOT IN THE URL. A browser cannot set
    // an `Authorization` header on a WebSocket, and a token in a query string
    // is a token in every proxy log between here and the Dell.
    socket.send(JSON.stringify({
      t: "hello", token: ctester.token(),
      assignment: live.assignment, exercise: live.exercise,
    }));
  };
  socket.onmessage = (event) => onFrame(live, event.data);
  socket.onclose = (event) => {
    if (session !== live) return;
    live.online = [];
    if (CLOSED[event.code]) {
      // AN EXPIRED TOKEN IS THE ONE REFUSAL WE CAN ANSWER OURSELVES. One
      // renewal, one reconnection, and `live.reauth` is what stops it there:
      // cleared only by a room that actually said `ready`, so a server that
      // keeps refusing a freshly minted token ends up as the sentence below
      // instead of an endless loop.
      if (event.code === UNAUTHORIZED && !live.reauth) {
        live.reauth = true;
        draw();
        ctester.rafraichirJeton().then((ok) => {
          if (session !== live) return;
          if (ok) return connect(live);
          // The refresh was refused: `compte.js` has already signed out, and
          // the sentence tells them what to do about it.
          live.fatal = CLOSED[UNAUTHORIZED];
          lock(live, true);
          draw();
        });
        return;
      }
      // A REFUSAL IS NOT A NETWORK PROBLEM, and retrying it forever would
      // hide the sentence that says what to do about it.
      live.fatal = CLOSED[event.code];
      lock(live, true);
      draw();
      return;
    }
    draw();
    retry(live);
  };
}

function retry(live) {
  if (session !== live || live.fatal) return;
  const wait = RETRY[Math.min(live.attempts, RETRY.length - 1)];
  live.attempts++;
  live.timer = setTimeout(() => {
    if (session === live) connect(live);
  }, wait);
}

function onFrame(live, raw) {
  let frame = null;
  try { frame = JSON.parse(raw); } catch (e) { return; }
  if (!frame || session !== live) return;
  if (frame.t === "ready") return onReady(live, frame);
  if (frame.t === "presence") {
    live.online = Array.isArray(frame.online) ? frame.online : [];
    draw();
    return;
  }
  if (frame.t === "update" && typeof frame.d === "string") {
    // APPLIED WITH A FOREIGN ORIGIN, which is what tells the observer below
    // this did not come from the textarea -- and therefore that the caret has
    // to be transformed rather than left where it is.
    try { live.Y.applyUpdate(live.doc, unb64(frame.d), "remote"); } catch (e) {}
    // THE FIRST UPDATE IS WHAT OPENS THE EDITOR when we joined a room that
    // already had members: until it lands, our document is empty, and text
    // typed into an empty document would be MERGED ON TOP of the team's real
    // text a moment later rather than replaced by it. See `arm()`.
    arm(live);
    return;
  }
  if (frame.t === "sync" && typeof frame.d === "string") {
    // SOMEBODY ASKED WHAT WE HAVE THAT THEY DO NOT. We answer with exactly
    // that difference -- never the whole document -- and, if they asked us to
    // ask back, we do so once. That terminates: the reply carries `ask:false`.
    try {
      const missing = live.Y.encodeStateAsUpdate(live.doc, unb64(frame.d));
      send({ t: "update", d: b64(missing) });
      if (frame.ask) {
        send({ t: "sync", d: b64(live.Y.encodeStateVector(live.doc)), ask: false });
      }
    } catch (e) {}
    return;
  }
  if (frame.t === "cursor" && frame.from) {
    live.carets[frame.from] = decodeCaret(live, frame);
    renderCarets();
  }
}

function onReady(live, frame) {
  live.attempts = 0;
  // THE ROOM ACCEPTED US, so the next expiry -- an hour into a lab -- gets its
  // own renewal. Without this line a session could only ever be renewed once.
  live.reauth = false;
  live.me = frame.me || "";
  // THE EPOCH IS THE SEAM. The server drops a room as soon as its last member
  // leaves and rebuilds it -- with a new epoch -- for whoever arrives next.
  // A client coming back to a REBUILT room must throw its local document away
  // and start from the server's text: merging a stale CRDT into a freshly
  // seeded one would leave the file written twice, which is the one failure
  // this whole design has to make impossible.
  if (live.epoch && live.epoch !== frame.epoch) {
    reseed(live, frame);
    return;
  }
  live.epoch = frame.epoch;
  startSync(live, frame.peers);
}

// HOW A CLIENT GETS A DOCUMENT, and the whole rule is `peers`.
//
// An EMPTY room means the server's plain text is the truth, so we seed from
// it. A room that already has somebody means THEY have the document and we do
// not, so we ask and stay read-only until their answer lands -- text typed
// into an empty document would be MERGED ON TOP of the team's real text a
// moment later rather than replaced by it.
//
// Two clients cannot both see an empty room: join order is decided in one
// process, under one event loop, before either `ready` is written.
function startSync(live, peers) {
  clearTimeout(live.armTimer);
  if (peers === 0 && !live.seeded) {
    seed(live);
    arm(live);
    return;
  }
  send({ t: "sync", d: b64(live.Y.encodeStateVector(live.doc)), ask: true });
  if (live.seeded) { arm(live); return; }   // a reconnect: we already have it
  live.note = "synchronisation avec ton équipe…";
  draw();
  // A PEER THAT VANISHED BETWEEN THE JOIN AND THE ANSWER must not leave the
  // workspace read-only forever. On this deadline the server's own text is
  // the fallback, exactly as for a first arrival.
  live.armTimer = setTimeout(() => arm(live, true), 3000);
}

// Opens the editor once the document is real: when a peer's state lands, or
// on that deadline. Idempotent -- an update arriving after we already armed
// must not seed a second time.
function arm(live, expired) {
  if (session !== live) return;
  clearTimeout(live.armTimer);
  if (!live.seeded) {
    if (expired) seed(live);
    live.seeded = true;
    lock(live, false);
  }
  live.note = "";
  draw();
  pushCaret(live);
}

// --- Seeding and reseeding ------------------------------------------------------

function seed(live) {
  live.doc.transact(() => {
    for (const name of live.files) {
      const ytext = textOf(live.doc, name);
      const text = live.server[name] || "";
      if (ytext.length === 0 && text) ytext.insert(0, text);
    }
  }, LOCAL);
  // `seeded` IS ARM'S TO SET, NOT SEED'S. Setting it here would make `arm()`
  // believe the editor had already been opened and skip unlocking it -- the
  // workspace would stay read-only for the first person into an empty room,
  // which is the one person who is certainly allowed to type.
  paintAll(live);
}

async function reseed(live, frame) {
  // Everything local goes, including anything typed while disconnected: the
  // room was rebuilt from the server's copy, and there is no honest way to
  // merge into a document whose history no longer exists. The save that
  // follows every keystroke is what makes this cost seconds rather than work.
  live.epoch = frame.epoch;
  live.seeded = false;
  lock(live, true);
  const fresh = await fetchDocument(live.assignment, live.exercise);
  if (session !== live) return;
  live.server = (fresh && fresh.sources) || {};
  buildDoc(live);
  startSync(live, frame.peers);
}


function buildDoc(live) {
  live.doc = new live.Y.Doc();
  live.carets = {};
  for (const name of live.files) {
    const ytext = textOf(live.doc, name);
    ytext.observe((event) => onRemoteText(live, name, event));
  }
  live.doc.on("update", (update, origin) => {
    if (origin === "remote") return;   // never echo back what we just applied
    send({ t: "update", d: b64(update) });
    scheduleSave(live);
  });
}

function paintAll(live) {
  for (const name of live.files) {
    ctester.editeur.ecrire(name, textOf(live.doc, name).toString());
  }
  renderCarets();
}

function onRemoteText(live, name, event) {
  if (event.transaction.origin === LOCAL) return;
  const text = textOf(live.doc, name).toString();
  const zone = ctester.editeur.zone();
  const selection = name === ctester.editeur.fichierActif()
    ? { start: shift(event.delta, zone.selectionStart || 0),
        end: shift(event.delta, zone.selectionEnd || 0) }
    : null;
  ctester.editeur.ecrire(name, text, selection);
  renderCarets();
}

// --- Cursors -------------------------------------------------------------------
// RELATIVE POSITIONS, NOT OFFSETS. An offset means something different the
// moment a teammate inserts a line above it; a Yjs relative position survives
// concurrent edits, which is exactly the case a caret has to survive.

function pushCaret(live) {
  const name = ctester.editeur.fichierActif();
  if (!name || !live.seeded) return;
  const zone = ctester.editeur.zone();
  const ytext = textOf(live.doc, name);
  try {
    const anchor = live.Y.createRelativePositionFromTypeIndex(
      ytext, Math.min(zone.selectionStart || 0, ytext.length));
    const head = live.Y.createRelativePositionFromTypeIndex(
      ytext, Math.min(zone.selectionEnd || 0, ytext.length));
    send({ t: "cursor", file: name,
           a: b64(live.Y.encodeRelativePosition(anchor)),
           h: b64(live.Y.encodeRelativePosition(head)) });
  } catch (e) { /* a caret is never worth an exception */ }
}

function decodeCaret(live, frame) {
  const at = (value) => {
    try {
      const absolute = live.Y.createAbsolutePositionFromRelativePosition(
        live.Y.decodeRelativePosition(unb64(value)), live.doc);
      return absolute ? absolute.index : 0;
    } catch (e) { return 0; }
  };
  return { file: String(frame.file || ""), anchor: at(frame.a), head: at(frame.h) };
}

// --- Persistence ----------------------------------------------------------------

function scheduleSave(live) {
  clearTimeout(live.saveTimer);
  live.saveTimer = setTimeout(() => save(live), SAVE_DELAY);
}

async function save(live) {
  if (session !== live || !ctester.compte) return;
  const files = {};
  for (const name of live.files) files[name] = textOf(live.doc, name).toString();
  const answer = await ctester.compte.sendJson("team/document", "PUT", {
    assignment_id: live.assignment, exercise_id: live.exercise, files: files,
  });
  live.saved = !!(answer && answer.ok);
  // "NOT SAVED" IS THE ONLY MESSAGE ON THIS LINE THAT MATTERS, so it is the
  // one that stays: a green tick that flickers teaches nobody anything, a red
  // one is why somebody stops typing and checks.
  ctester.showDraftStatus(
    live.saved ? "partagé avec ton équipe · " + ctester.maintenant()
               : "NON enregistré — garde une copie de ton code", !live.saved);
  draw();
}

// --- The band ------------------------------------------------------------------

function lock(live, locked) {
  ctester.editeur.verrouiller(locked);
  live.locked = locked;
}

function statusLine(live) {
  if (live.fatal) return { text: live.fatal, bad: true };
  if (!live.socket || live.socket.readyState !== 1) {
    return { text: "hors ligne — tes changements repartiront tout seuls "
                   + "dès que la connexion revient", bad: true };
  }
  const others = live.online.filter((handle) => handle !== live.me).length;
  return { text: others
    ? others + " coéquipier" + (others > 1 ? "s" : "") + " en ligne"
    : "tu es seul sur cet exercice pour l'instant", bad: false };
}

function draw() {
  const band = $("teamband");
  if (!band) return;
  band.innerHTML = "";
  if (!session) { band.hidden = true; return; }
  band.hidden = false;
  const context = session.context;
  const assignment = context.assignment;

  const head = node("div", "teamhead");
  head.append(node("b", "teamtitle", assignment.title));
  if (assignment.deadline) {
    const when = new Date(assignment.deadline);
    head.append(node("span", "tag" + (assignment.deadline_passed ? " rate" : ""),
      isNaN(when.getTime()) ? "à remettre"
        : (assignment.deadline_passed ? "remise close le " : "à remettre le ")
          + when.toLocaleDateString(undefined,
              { day: "numeric", month: "long" })
          + " à " + when.toLocaleTimeString(undefined,
              { hour: "2-digit", minute: "2-digit" })));
  }
  head.append(node("span", "tag", context.team.label));
  // SUR DEUX CHIFFRES, comme partout ailleurs dans la page (`groupNumber()`
   // de forum.js, la plaque de la barre) : « groupe 4 » ici et « groupe 04 »
   // dans le profil, ce sont deux façons d'écrire une chose dont l'étudiant
   // finit par se demander si ce sont deux choses.
  head.append(node("span", "tag",
                   "groupe " + String(context.team.group_number).padStart(2, "0")));
  band.append(head);

  // THE TEAM, AND WHO IS HERE RIGHT NOW. The colour is the one their caret
  // uses, which is the only way "that cursor is Coéquipier 2" is legible.
  const who = node("div", "teamwho");
  for (const member of session.members) {
    const online = member.you || session.online.indexOf(member.id) >= 0;
    const chip = node("span", "mate" + (online ? " on" : ""));
    const dot = node("i", "dot");
    dot.setAttribute("style", "background:" + member.color);
    chip.append(dot, node("span", "", member.name + (member.you ? " (toi)" : "")));
    chip.title = online ? "en ligne" : "hors ligne";
    who.append(chip);
  }
  const state = statusLine(session);
  who.append(node("span", "grow"));
  who.append(node("span", "etat" + (state.bad ? " rate" : ""), state.text));
  band.append(who);

  const actions = node("div", "teamactions");
  actions.append(button("Historique", () => toggleHistory()));
  if (assignment.handin.length) {
    actions.append(button("Télécharger le ZIP", downloadArchive));
    const hand = button(context.submission && context.submission.submitted_at
      ? "Remettre à nouveau" : "Remettre le devoir", handIn);
    if (assignment.deadline_passed) {
      hand.disabled = true;
      hand.title = "la date de remise est passée";
    }
    actions.append(hand);
  }
  if (context.submission && context.submission.submitted_at) {
    actions.append(node("span", "tag ok",
      "remis le " + context.submission.submitted_at.replace("T", " à ")));
  }
  actions.append(node("span", "grow"));
  actions.append(node("span", "aide", session.note || ""));
  band.append(actions);
  if (history) band.append(historyPanel());
}

function button(label, onClick) {
  const b = node("button", "nav", label);
  b.type = "button";
  b.addEventListener("click", onClick);
  return b;
}

function say(text, bad) {
  if (session) session.note = text;
  if (bad) ctester.systeme(text, true);
  draw();
}

// --- History -------------------------------------------------------------------
// RECOVERY AND READING, NEVER A MEASUREMENT. The list says who and when, and
// there is deliberately no percentage anywhere in it: a number counting typed
// characters becomes a grade the day it appears, and it is wrong about
// whoever thinks before typing.

async function toggleHistory() {
  if (history) { history = null; draw(); return; }
  const answer = await ctester.compte.getJson(
    "team/revisions?assignment=" + encodeURIComponent(session.assignment)
    + "&ex=" + encodeURIComponent(session.exercise));
  history = (answer && Array.isArray(answer.revisions))
    ? { rows: answer.revisions } : { rows: [], failed: true };
  draw();
}

function memberName(id) {
  const found = session.members.find((m) => m.id === id);
  return found ? found.name : "un ancien membre";
}

function historyPanel() {
  const panel = node("div", "teamhistory");
  panel.append(node("h3", "", "Historique partagé"));
  if (history.failed) {
    panel.append(node("p", "aide",
      "L'historique n'est pas disponible pour l'instant. Ton code, lui, "
      + "continue d'être enregistré."));
    return panel;
  }
  if (!history.rows.length) {
    panel.append(node("p", "aide",
      "Rien encore. Une version est gardée à chaque fois que l'un de vous "
      + "travaille sur cet exercice."));
    return panel;
  }
  for (const row of history.rows) {
    const line = node("div", "revline");
    line.append(node("span", "who", memberName(row.author)));
    line.append(node("time", "quand", row.created_at.replace("T", " à ")));
    line.append(node("span", "tag", Math.round(row.bytes / 100) / 10 + " Ko"));
    line.append(node("span", "grow"));
    line.append(button("Restaurer", () => restore(row)));
    panel.append(line);
  }
  return panel;
}

async function restore(row) {
  if (typeof confirm === "function"
      && !confirm("Remettre la version de " + memberName(row.author) + " du "
                  + row.created_at + " ? Le code actuel de l'équipe sera "
                  + "remplacé — il reste dans l'historique.")) {
    return;
  }
  const answer = await ctester.compte.sendJson("team/restore", "POST", {
    assignment_id: session.assignment, exercise_id: session.exercise,
    revision_id: row.id,
  });
  if (!answer || !answer.ok) {
    say((answer && answer.corps && answer.corps.error)
        || "La restauration n'a pas abouti.", true);
    return;
  }
  // APPLIED AS AN ORDINARY LOCAL EDIT, so teammates receive it the way they
  // receive any other change. The server does not push into the CRDT -- it
  // does not know what a CRDT is, and that is what keeps the relay dumb.
  const files = answer.corps && answer.corps.sources;
  if (files) {
    for (const name of session.files) {
      applyLocal(session.doc, textOf(session.doc, name), files[name] || "");
    }
    paintAll(session);
  }
  history = null;
  say("version restaurée");
}

// --- The hand-in ----------------------------------------------------------------

let previousUrl = null;

async function downloadArchive() {
  say("");
  let answer;
  try {
    // THROUGH `compte.js`, LIKE EVERY OTHER AUTHENTICATED CALL: an archive is
    // asked for at hand-in time, which is exactly when a tab has been open all
    // evening and the access token has quietly died.
    answer = await ctester.compte.authFetch(
      "team/handin.zip?assignment=" + encodeURIComponent(session.assignment));
  } catch (e) {
    say("Le serveur ne répond pas. Réessaie dans un instant.", true);
    return;
  }
  if (!answer.ok) {
    let body = null;
    try { body = await answer.json(); } catch (e) { body = null; }
    say((body && body.error) || "L'archive n'a pas pu être construite.", true);
    return;
  }
  const blob = await answer.blob();
  if (previousUrl) URL.revokeObjectURL(previousUrl);
  previousUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = previousUrl;
  link.download = session.assignment + ".zip";
  document.body.append(link);
  link.click();
  link.remove();
  say("archive téléchargée");
}

async function handIn() {
  if (typeof confirm === "function"
      && !confirm("Remettre le devoir au nom de toute l'équipe ? "
                  + "Tes coéquipiers verront la remise, et vous pourrez la "
                  + "refaire jusqu'à la date limite.")) {
    return;
  }
  const answer = await ctester.compte.sendJson("team/handin", "POST",
                                               { assignment_id: session.assignment });
  if (!answer || !answer.ok) {
    say((answer && answer.corps && answer.corps.error)
        || "La remise n'a pas abouti.", true);
    return;
  }
  session.context.submission = (answer.corps && answer.corps.submission) || {};
  contexts[session.assignment] = session.context;
  say("devoir remis pour l'équipe");
}

// --- Entering and leaving --------------------------------------------------------

async function fetchContext(assignmentId) {
  if (contexts[assignmentId]) return contexts[assignmentId];
  const answer = await ctester.compte.sendJson(
    "team/context?assignment=" + encodeURIComponent(assignmentId), "GET");
  if (!answer) return null;
  if (!answer.ok) return { refused: (answer.corps && answer.corps.error) || "" };
  contexts[assignmentId] = answer.corps;
  return answer.corps;
}

async function fetchDocument(assignmentId, exerciseId) {
  return ctester.compte.getJson(
    "team/document?assignment=" + encodeURIComponent(assignmentId)
    + "&ex=" + encodeURIComponent(exerciseId));
}

// THE BAND WITHOUT A WORKSPACE. A student who is not on a team must still be
// able to read the assignment and practise its exercises on their own -- the
// individual draft path is untouched -- and must be told why there is no
// shared editor, in a sentence that says who to ask.
function refuse(tp, message) {
  session = null;
  ctester.brancherSession(null);
  ctester.editeur.verrouiller(false);
  const band = $("teamband");
  if (!band) return;
  band.innerHTML = "";
  band.hidden = false;
  const head = node("div", "teamhead");
  const assignment = ctester.assignmentOf(tp.assignment);
  head.append(node("b", "teamtitle", (assignment && assignment.title) || "Devoir"));
  head.append(node("span", "tag rate", "pas d'espace d'équipe"));
  band.append(head);
  band.append(node("p", "aide", message));
}

async function enter(tp) {
  if (session && session.exercise === tp.id) return;
  leave();
  if (!ctester.compte) return;
  const context = await fetchContext(tp.assignment);
  if (!context) {
    refuse(tp, "L'espace d'équipe n'est pas joignable pour l'instant. "
             + "Tu peux écrire et tester : ton brouillon est enregistré sur "
             + "cet appareil.");
    return;
  }
  if (context.refused !== undefined) {
    refuse(tp, (context.refused || "Tu n'as pas accès à l'espace d'équipe de "
                + "ce devoir.")
             + " Tu peux quand même travailler l'exercice de ton côté : ton "
             + "brouillon est enregistré comme d'habitude.");
    return;
  }
  // THE LIBRARY, AND THERE IS NO FALLBACK IF IT DOES NOT ARRIVE. Without a
  // CRDT there is no safe way for four people to edit one document; a "best
  // effort" that pushed the last textarea value would destroy work rather
  // than degrade. The editor is locked and says so.
  try {
    await ctester.charger(YJS);
  } catch (e) {
    refuse(tp, "La bibliothèque d'édition partagée n'a pas pu être chargée. "
             + "Recharge la page — en attendant, n'écris pas ici : ton texte "
             + "ne partirait pas à ton équipe.");
    ctester.editeur.verrouiller(true);
    return;
  }
  if (!window.Y || !window.Y.Doc) {
    refuse(tp, "La bibliothèque d'édition partagée est arrivée incomplète. "
             + "Recharge la page.");
    ctester.editeur.verrouiller(true);
    return;
  }
  const document_ = await fetchDocument(tp.assignment, tp.id);
  const live = {
    Y: window.Y,
    assignment: tp.assignment,
    exercise: tp.id,
    context: context,
    members: context.team.members || [],
    files: (tp.files || []).map((f) => f.name),
    server: (document_ && document_.sources) || {},
    online: [], carets: {}, attempts: 0, epoch: "", seeded: false,
    note: "", me: "", fatal: "", reauth: false, saveTimer: null, timer: null,
  };
  if (!live.files.length) live.files = ["submission.c"];
  session = live;
  buildDoc(live);
  // WHAT THE SERVER HAS, SHOWN AT ONCE AND READ-ONLY. `setupFiles` has just
  // filled the editor with this account's INDIVIDUAL draft -- the right thing
  // for every other exercise, and the wrong thing here: the team would see
  // one member's old private code for as long as the socket takes to answer,
  // and a save firing in that window would push it at the other three.
  //
  // LOCKED UNTIL THE ROOM ANSWERS, and that is the other half. Typing into a
  // document that has not been synced yet would either be lost or, worse, be
  // merged on top of the team's real text a second later.
  for (const name of live.files) {
    ctester.editeur.ecrire(name, live.server[name] || "");
  }
  lock(live, true);
  ctester.brancherSession({
    // CE QUE LE NOYAU DEMANDE AVANT DE SYNCHRONISER UN BROUILLON INDIVIDUEL.
    // Tant que cette session tient l'exercice, c'est elle qui enregistre --
    // dans le document de l'ÉQUIPE, et une seule fois.
    owns: (id) => id === live.exercise,
    onInput: () => {
      const name = ctester.editeur.fichierActif();
      if (!name || !live.seeded) return;
      applyLocal(live.doc, textOf(live.doc, name), ctester.editeur.lire(name));
      pushCaret(live);
      renderCarets();
    },
    onCaret: () => { pushCaret(live); renderCarets(); },
    onScroll: () => renderCarets(),
    onSwitch: () => { metrics = null; pushCaret(live); renderCarets(); },
  });
  draw();
  connect(live);
}

function leave() {
  if (!session) {
    const band = $("teamband");
    if (band) { band.hidden = true; band.innerHTML = ""; }
    return;
  }
  const live = session;
  session = null;
  history = null;
  clearTimeout(live.saveTimer);
  clearTimeout(live.timer);
  ctester.brancherSession(null);
  ctester.editeur.verrouiller(false);
  const layer = $("carets");
  if (layer) layer.innerHTML = "";
  const band = $("teamband");
  if (band) { band.hidden = true; band.innerHTML = ""; }
  try { if (live.socket) live.socket.close(); } catch (e) {}
  // ONE LAST SAVE, NOT A SCHEDULED ONE. Leaving an exercise is exactly when
  // the 1.5 s timer would be cancelled with a keystroke still unsaved.
  if (live.seeded && ctester.compte) {
    const files = {};
    for (const name of live.files) files[name] = textOf(live.doc, name).toString();
    ctester.compte.sendJson("team/document", "PUT", {
      assignment_id: live.assignment, exercise_id: live.exercise, files: files,
    });
  }
}

function forget() {
  leave();
  contexts = {};
}

ctester.team = {
  enter: enter,
  leave: leave,
  oublier: forget,
  // Read by the harness and by anyone debugging a room: what this tab thinks
  // it is connected to. Never written from outside.
  session: () => session,
};
})(window.ctester);
