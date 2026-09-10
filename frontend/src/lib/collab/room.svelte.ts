// THE TEAM ROOM: one assignment, one team, one shared document per exercise.
//
// THE CONVERGENCE IS YJS'S, THE AUTHORIZATION IS THE SERVER'S. This module holds a
// `Y.Doc`, sends the opaque updates it produces down a WebSocket, and applies the
// ones that come back. It invents no merge rule: four people typing in the same
// line is exactly the case a hand-rolled protocol gets wrong in week three.
//
// WHAT THE SERVER RELAYS, IT DOES NOT READ. `app/services/collab.py` forwards these
// frames without parsing them and STAMPS THE SENDER on each one from the roster --
// so a caret cannot be attributed to somebody else by writing a different id, and a
// room cannot be joined by naming a different team. No frame this file sends
// carries a team.
//
// THE DURABLE COPY IS PLAIN TEXT. Every local edit is debounced into
// `PUT /team/document`, which validates the file names against the catalog like
// every other write. What gets tested, exported and handed in is that text -- never
// a CRDT blob -- so nothing here can produce a hand-in the judge has not seen.
//
// LOADED ON DEMAND, WITH YJS INSIDE THIS CHUNK. The anonymous visitor downloads not
// one byte of it, and neither does a signed-in student working an ordinary lab.

import * as Y from "yjs";
import { socketUrl } from "../config";
import { ensureValid, renew, session } from "../auth/session.svelte";
import { fetchContext, fetchDocument, saveDocument } from "../api/team";
import { applyLocal, LOCAL, REMOTE, seed, snapshot, textOf } from "./document";
import { fromBase64, shift, toBase64 } from "./carets";
import { editor } from "../state/editor.svelte";
import { collaborators } from "../state/collaborators.svelte";
import { drafts } from "../state/drafts.svelte";
import { clockNow } from "../domain/labels";
import type { Exercise } from "../domain/catalog";
import type { CaretPosition } from "../state/collaborators.svelte";
import type { TeamContext } from "../api/types";

/** How long after the last keystroke the document is written to Postgres. The
 *  socket has already carried the change to the teammates; this is only about
 *  surviving a closed tab. */
const SAVE_DELAY = 1500;
/** Reconnection backoff: short enough that a closed laptop lid comes back on its
 *  own, long enough that a service being restarted is not hammered. */
const RETRY = [500, 1000, 2000, 5000, 10_000];
/** A peer that vanished between the join and the answer must not leave the
 *  workspace read-only forever. */
const SYNC_DEADLINE = 3000;

const UNAUTHORIZED = 4401;

/** The four close codes the server uses. A student whose session expired and one
 *  who is not on a team must not both read "connection lost". */
const CLOSED: Record<number, string> = {
  4401: "Ta session a expiré. Reconnecte-toi pour retrouver l'espace d'équipe.",
  4403: "Tu n'es pas inscrit à une équipe pour ce devoir.",
  4429: "Trop d'onglets ouverts sur cet exercice. Ferme-en un et réessaie.",
  4400: "L'espace d'équipe n'a pas pu démarrer. Recharge la page.",
};

interface Live {
  assignment: string;
  exercise: string;
  files: string[];
  server: Record<string, string>;
  doc: Y.Doc;
  socket: WebSocket | null;
  attempts: number;
  epoch: string;
  seeded: boolean;
  reauth: boolean;
  saveTimer: ReturnType<typeof setTimeout> | null;
  retryTimer: ReturnType<typeof setTimeout> | null;
  armTimer: ReturnType<typeof setTimeout> | null;
}

class Room {
  /** null when no workspace is open. */
  context = $state<TeamContext | null>(null);
  /** The refusal sentence, when there is a band but no workspace. */
  refusal = $state("");
  /** A fatal close: a refusal, not a network problem, so retrying would hide it. */
  fatal = $state("");
  note = $state("");
  connected = $state(false);
  saved = $state(true);

  #live: Live | null = null;

  get open(): boolean {
    return this.#live !== null;
  }

  get exerciseId(): string {
    return this.#live?.exercise ?? "";
  }

  get assignmentId(): string {
    return this.#live?.assignment ?? "";
  }

  get files(): string[] {
    return this.#live?.files ?? [];
  }

  /** THE STATUS LINE, and it is about the room rather than about the code. */
  get status(): { text: string; bad: boolean } {
    if (this.fatal) return { text: this.fatal, bad: true };
    if (!this.connected) {
      return {
        text: "hors ligne — tes changements repartiront tout seuls dès que la connexion revient",
        bad: true,
      };
    }
    const others = collaborators.online.filter((h) => h !== collaborators.me).length;
    return {
      text: others
        ? others + " coéquipier" + (others > 1 ? "s" : "") + " en ligne"
        : "tu es seul sur cet exercice pour l'instant",
      bad: false,
    };
  }

  // --- Entering ---------------------------------------------------------------

  async enter(ex: Exercise): Promise<void> {
    if (this.#live && this.#live.exercise === ex.id) return;
    this.leave();
    if (!session.signedIn) return;
    const answer = await fetchContext(ex.assignment);
    if (answer.status === 0 || (!answer.ok && !answer.body)) {
      this.#refuse(
        "L'espace d'équipe n'est pas joignable pour l'instant. Tu peux écrire et " +
          "tester : ton brouillon est enregistré sur cet appareil.",
      );
      return;
    }
    if (!answer.ok) {
      const said = (answer.body as { error?: string } | null)?.error ?? "";
      this.#refuse(
        (said || "Tu n'as pas accès à l'espace d'équipe de ce devoir.") +
          " Tu peux quand même travailler l'exercice de ton côté : ton brouillon " +
          "est enregistré comme d'habitude.",
      );
      return;
    }
    const context = answer.body!;
    const document_ = await fetchDocument(ex.assignment, ex.id);
    const files = ex.files.map((f) => f.name);
    const live: Live = {
      assignment: ex.assignment,
      exercise: ex.id,
      files: files.length ? files : ["submission.c"],
      server: document_?.sources ?? {},
      doc: new Y.Doc(),
      socket: null,
      attempts: 0,
      epoch: "",
      seeded: false,
      reauth: false,
      saveTimer: null,
      retryTimer: null,
      armTimer: null,
    };
    this.context = context;
    this.refusal = "";
    this.fatal = "";
    this.note = "";
    collaborators.set(context.team.members, "");
    this.#live = live;
    this.#buildDoc(live);
    // WHAT THE SERVER HAS, SHOWN AT ONCE AND READ-ONLY. The editor has just been
    // filled with this account's INDIVIDUAL draft -- right for every other
    // exercise, wrong here: the team would see one member's old private code for as
    // long as the socket takes to answer, and a save firing in that window would
    // push it at the other three.
    //
    // LOCKED UNTIL THE ROOM ANSWERS, and that is the other half. Typing into a
    // document that has not been synced yet would either be lost or, worse, be
    // merged on top of the team's real text a second later.
    for (const name of live.files) editor.write(name, live.server[name] ?? "");
    editor.lock(true);
    editor.attach({
      // WHAT THE CORE ASKS BEFORE SYNCING AN INDIVIDUAL DRAFT. While this session
      // holds the exercise, IT does the saving -- into the TEAM's document, once.
      owns: (id) => id === live.exercise,
      onInput: () => {
        const name = editor.activeFile;
        if (!name || !live.seeded) return;
        applyLocal(live.doc, textOf(live.doc, name), editor.read(name));
        this.#pushCaret(live);
      },
      onCaret: () => this.#pushCaret(live),
      onSwitch: () => this.#pushCaret(live),
    });
    void this.#connect(live);
  }

  /** THE BAND WITHOUT A WORKSPACE. A student who is not on a team must still be
   *  able to read the assignment and practise its exercises alone -- the individual
   *  draft path is untouched -- and must be told why there is no shared editor. */
  #refuse(message: string): void {
    this.#live = null;
    this.context = null;
    this.refusal = message;
    collaborators.clear();
    editor.attach(null);
    editor.lock(false);
  }

  leave(): void {
    const live = this.#live;
    this.#live = null;
    this.context = null;
    this.refusal = "";
    this.fatal = "";
    this.connected = false;
    collaborators.clear();
    editor.attach(null);
    editor.lock(false);
    if (!live) return;
    if (live.saveTimer) clearTimeout(live.saveTimer);
    if (live.retryTimer) clearTimeout(live.retryTimer);
    if (live.armTimer) clearTimeout(live.armTimer);
    try {
      live.socket?.close();
    } catch {
      /* already closed */
    }
    // ONE LAST SAVE, NOT A SCHEDULED ONE. Leaving an exercise is exactly when the
    // 1.5 s timer would be cancelled with a keystroke still unsaved.
    if (live.seeded && session.signedIn) {
      void saveDocument(live.assignment, live.exercise, snapshot(live.doc, live.files));
    }
  }

  // --- The document -----------------------------------------------------------

  #buildDoc(live: Live): void {
    for (const name of live.files) {
      textOf(live.doc, name).observe((event) => this.#onRemoteText(live, name, event));
    }
    live.doc.on("update", (update: Uint8Array, origin: unknown) => {
      if (origin === REMOTE) return; // never echo back what we just applied
      this.#send(live, { t: "update", d: toBase64(update) });
      this.#scheduleSave(live);
    });
  }

  #onRemoteText(live: Live, name: string, event: Y.YTextEvent): void {
    if (event.transaction.origin === LOCAL) return;
    const text = textOf(live.doc, name).toString();
    const zone = editor.element;
    const selection =
      name === editor.activeFile && zone
        ? {
            start: shift(event.delta as never, zone.selectionStart || 0),
            end: shift(event.delta as never, zone.selectionEnd || 0),
          }
        : null;
    editor.write(name, text, selection);
  }

  #paintAll(live: Live): void {
    for (const name of live.files) editor.write(name, textOf(live.doc, name).toString());
  }

  // --- The socket -------------------------------------------------------------

  #send(live: Live, payload: unknown): void {
    if (live.socket && live.socket.readyState === 1) {
      live.socket.send(JSON.stringify(payload));
    }
  }

  async #connect(live: Live): Promise<void> {
    // THE TOKEN GOES IN THE FIRST FRAME, so it has to still be good BEFORE the
    // socket opens: a room refused on 4401 costs a full round trip and a
    // reconnection, where renewing here costs nothing when the token is fresh.
    await ensureValid();
    if (this.#live !== live) return; // the workspace closed while we waited
    let socket: WebSocket;
    try {
      socket = new WebSocket(socketUrl("/team/live"));
    } catch {
      this.#retry(live);
      return;
    }
    live.socket = socket;
    socket.onopen = () => {
      // IN THE FIRST FRAME, NEVER IN THE URL. A browser cannot set an
      // `Authorization` header on a WebSocket, and a token in a query string is a
      // token in every proxy log between here and the Dell.
      socket.send(
        JSON.stringify({
          t: "hello",
          token: session.token,
          assignment: live.assignment,
          exercise: live.exercise,
        }),
      );
    };
    socket.onmessage = (event) => this.#onFrame(live, String(event.data));
    socket.onclose = (event) => {
      if (this.#live !== live) return;
      this.connected = false;
      collaborators.setOnline([]);
      const said = CLOSED[event.code];
      if (said) {
        // AN EXPIRED TOKEN IS THE ONE REFUSAL WE CAN ANSWER OURSELVES. One renewal,
        // one reconnection, and `reauth` stops it there -- cleared only by a room
        // that actually said `ready`, so a server that keeps refusing a freshly
        // minted token ends up as the sentence below instead of an endless loop.
        if (event.code === UNAUTHORIZED && !live.reauth) {
          live.reauth = true;
          void renew().then((ok) => {
            if (this.#live !== live) return;
            if (ok) return this.#connect(live);
            this.fatal = CLOSED[UNAUTHORIZED]!;
            editor.lock(true);
          });
          return;
        }
        // A REFUSAL IS NOT A NETWORK PROBLEM, and retrying it forever would hide
        // the sentence that says what to do about it.
        this.fatal = said;
        editor.lock(true);
        return;
      }
      this.#retry(live);
    };
  }

  #retry(live: Live): void {
    if (this.#live !== live || this.fatal) return;
    const wait = RETRY[Math.min(live.attempts, RETRY.length - 1)]!;
    live.attempts++;
    live.retryTimer = setTimeout(() => {
      if (this.#live === live) void this.#connect(live);
    }, wait);
  }

  #onFrame(live: Live, raw: string): void {
    let frame: Record<string, unknown> | null = null;
    try {
      frame = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      return;
    }
    if (!frame || this.#live !== live) return;
    const kind = frame.t;
    if (kind === "ready") {
      this.#onReady(live, frame);
      return;
    }
    if (kind === "presence") {
      collaborators.setOnline(Array.isArray(frame.online) ? (frame.online as string[]) : []);
      return;
    }
    if (kind === "update" && typeof frame.d === "string") {
      // APPLIED WITH A FOREIGN ORIGIN, which is what tells the observer this did NOT
      // come from the textarea -- and therefore that the caret has to be transformed
      // rather than left where it is.
      try {
        Y.applyUpdate(live.doc, fromBase64(frame.d), REMOTE);
      } catch {
        /* a malformed update is not worth an exception */
      }
      // THE FIRST UPDATE IS WHAT OPENS THE EDITOR when we joined a room that already
      // had members: until it lands our document is empty, and text typed into an
      // empty document would be MERGED ON TOP of the team's real text a moment later
      // rather than replaced by it.
      this.#arm(live, false);
      return;
    }
    if (kind === "sync" && typeof frame.d === "string") {
      // SOMEBODY ASKED WHAT WE HAVE THAT THEY DO NOT. We answer with exactly that
      // difference -- never the whole document -- and, if they asked us to ask back,
      // we do so once. That terminates: the reply carries `ask: false`.
      try {
        const missing = Y.encodeStateAsUpdate(live.doc, fromBase64(frame.d));
        this.#send(live, { t: "update", d: toBase64(missing) });
        if (frame.ask) {
          this.#send(live, {
            t: "sync",
            d: toBase64(Y.encodeStateVector(live.doc)),
            ask: false,
          });
        }
      } catch {
        /* see above */
      }
      return;
    }
    if (kind === "cursor" && typeof frame.from === "string") {
      collaborators.setCaret(frame.from, this.#decodeCaret(live, frame));
    }
  }

  #onReady(live: Live, frame: Record<string, unknown>): void {
    live.attempts = 0;
    this.connected = true;
    // THE ROOM ACCEPTED US, so the next expiry -- an hour into a lab -- gets its own
    // renewal. Without this line a session could only ever be renewed once.
    live.reauth = false;
    collaborators.set(this.context?.team.members ?? [], typeof frame.me === "string" ? frame.me : "");
    const epoch = String(frame.epoch ?? "");
    const peers = Number(frame.peers ?? 0);
    // THE EPOCH IS THE SEAM. The server drops a room as soon as its last member
    // leaves and rebuilds it -- with a new epoch -- for whoever arrives next. A
    // client coming back to a REBUILT room must throw its local document away and
    // start from the server's text: merging a stale CRDT into a freshly seeded one
    // would leave the file written twice, which is the one failure this whole design
    // has to make impossible.
    if (live.epoch && live.epoch !== epoch) {
      void this.#reseed(live, epoch, peers);
      return;
    }
    live.epoch = epoch;
    this.#startSync(live, peers);
  }

  /**
   * HOW A CLIENT GETS A DOCUMENT, and the whole rule is `peers`.
   *
   * An EMPTY room means the server's plain text is the truth, so we seed from it. A
   * room that already has somebody means THEY have the document and we do not, so we
   * ask and stay read-only until their answer lands.
   *
   * Two clients cannot both see an empty room: join order is decided in one process,
   * under one event loop, before either `ready` is written.
   */
  #startSync(live: Live, peers: number): void {
    if (live.armTimer) clearTimeout(live.armTimer);
    if (peers === 0 && !live.seeded) {
      seed(live.doc, live.files, live.server);
      this.#paintAll(live);
      this.#arm(live, false);
      return;
    }
    this.#send(live, { t: "sync", d: toBase64(Y.encodeStateVector(live.doc)), ask: true });
    if (live.seeded) {
      this.#arm(live, false); // a reconnect: we already have it
      return;
    }
    this.note = "synchronisation avec ton équipe…";
    live.armTimer = setTimeout(() => this.#arm(live, true), SYNC_DEADLINE);
  }

  /**
   * Opens the editor once the document is real: when a peer's state lands, or on the
   * deadline. Idempotent -- an update arriving after we already armed must not seed
   * a second time.
   */
  #arm(live: Live, expired: boolean): void {
    if (this.#live !== live) return;
    if (live.armTimer) clearTimeout(live.armTimer);
    if (!live.seeded) {
      // ON THE DEADLINE the server's own text is the fallback, exactly as for a
      // first arrival.
      if (expired) {
        seed(live.doc, live.files, live.server);
        this.#paintAll(live);
      }
      live.seeded = true;
      editor.lock(false);
    }
    this.note = "";
    this.#pushCaret(live);
  }

  async #reseed(live: Live, epoch: string, peers: number): Promise<void> {
    // Everything local goes, including anything typed while disconnected: the room
    // was rebuilt from the server's copy, and there is no honest way to merge into a
    // document whose history no longer exists. The save that follows every keystroke
    // is what makes this cost seconds rather than work.
    live.epoch = epoch;
    live.seeded = false;
    editor.lock(true);
    const fresh = await fetchDocument(live.assignment, live.exercise);
    if (this.#live !== live) return;
    live.server = fresh?.sources ?? {};
    live.doc = new Y.Doc();
    // A REBUILT ROOM'S CARETS point into a document that no longer exists.
    collaborators.carets = {};
    this.#buildDoc(live);
    this.#startSync(live, peers);
  }

  // --- Cursors ----------------------------------------------------------------
  // RELATIVE POSITIONS, NOT OFFSETS. An offset means something different the moment
  // a teammate inserts a line above it; a Yjs relative position survives concurrent
  // edits, which is exactly the case a caret has to survive.

  #pushCaret(live: Live): void {
    const name = editor.activeFile;
    const zone = editor.element;
    if (!name || !live.seeded || !zone) return;
    const ytext = textOf(live.doc, name);
    try {
      const anchor = Y.createRelativePositionFromTypeIndex(
        ytext,
        Math.min(zone.selectionStart || 0, ytext.length),
      );
      const head = Y.createRelativePositionFromTypeIndex(
        ytext,
        Math.min(zone.selectionEnd || 0, ytext.length),
      );
      this.#send(live, {
        t: "cursor",
        file: name,
        a: toBase64(Y.encodeRelativePosition(anchor)),
        h: toBase64(Y.encodeRelativePosition(head)),
      });
    } catch {
      /* a caret is never worth an exception */
    }
  }

  #decodeCaret(live: Live, frame: Record<string, unknown>): CaretPosition {
    const at = (value: unknown): number => {
      if (typeof value !== "string") return 0;
      try {
        const absolute = Y.createAbsolutePositionFromRelativePosition(
          Y.decodeRelativePosition(fromBase64(value)),
          live.doc,
        );
        return absolute ? absolute.index : 0;
      } catch {
        return 0;
      }
    };
    return { file: String(frame.file ?? ""), anchor: at(frame.a), head: at(frame.h) };
  }

  // --- Persistence ------------------------------------------------------------

  #scheduleSave(live: Live): void {
    if (live.saveTimer) clearTimeout(live.saveTimer);
    live.saveTimer = setTimeout(() => void this.#save(live), SAVE_DELAY);
  }

  async #save(live: Live): Promise<void> {
    if (this.#live !== live || !session.signedIn) return;
    const answer = await saveDocument(
      live.assignment,
      live.exercise,
      snapshot(live.doc, live.files),
    );
    this.saved = answer.ok;
    // "NOT SAVED" IS THE ONLY MESSAGE ON THIS LINE THAT MATTERS, so it is the one
    // that stays: a green tick that flickers teaches nobody anything, a red one is
    // why somebody stops typing and checks.
    drafts.say(
      answer.ok
        ? "partagé avec ton équipe · " + clockNow()
        : "NON enregistré — garde une copie de ton code",
      !answer.ok,
    );
  }

  /** A restored revision, applied as an ORDINARY LOCAL EDIT so teammates receive it
   *  the way they receive any other change. The server pushes nothing into the CRDT
   *  -- it does not know what a CRDT is, and that is what keeps the relay dumb. */
  applyRestored(files: Record<string, string>): void {
    const live = this.#live;
    if (!live) return;
    for (const name of live.files) {
      applyLocal(live.doc, textOf(live.doc, name), files[name] ?? "");
    }
    this.#paintAll(live);
  }

  forget(): void {
    this.leave();
  }
}

export const room = new Room();
