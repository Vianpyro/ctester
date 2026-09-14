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

const SAVE_DELAY = 1500;
const RETRY = [500, 1000, 2000, 5000, 10_000];
const SYNC_DEADLINE = 3000;

const UNAUTHORIZED = 4401;

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
  context = $state<TeamContext | null>(null);
  refusal = $state("");
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
    for (const name of live.files) editor.write(name, live.server[name] ?? "");
    editor.lock(true);
    editor.attach({
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
    }
    if (live.seeded && session.signedIn) {
      void saveDocument(live.assignment, live.exercise, snapshot(live.doc, live.files));
    }
  }

  #buildDoc(live: Live): void {
    for (const name of live.files) {
      textOf(live.doc, name).observe((event) => this.#onRemoteText(live, name, event));
    }
    live.doc.on("update", (update: Uint8Array, origin: unknown) => {
      if (origin === REMOTE) return;
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

  #send(live: Live, payload: unknown): void {
    if (live.socket && live.socket.readyState === 1) {
      live.socket.send(JSON.stringify(payload));
    }
  }

  async #connect(live: Live): Promise<void> {
    await ensureValid();
    if (this.#live !== live) return;
    let socket: WebSocket;
    try {
      socket = new WebSocket(socketUrl("/team/live"));
    } catch {
      this.#retry(live);
      return;
    }
    live.socket = socket;
    socket.onopen = () => {
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
      try {
        Y.applyUpdate(live.doc, fromBase64(frame.d), REMOTE);
      } catch {
      }
      this.#arm(live, false);
      return;
    }
    if (kind === "sync" && typeof frame.d === "string") {
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
    live.reauth = false;
    collaborators.set(this.context?.team.members ?? [], typeof frame.me === "string" ? frame.me : "");
    const epoch = String(frame.epoch ?? "");
    const peers = Number(frame.peers ?? 0);
    // A new epoch means the room was rebuilt: drop the local document instead of merging it.
    if (live.epoch && live.epoch !== epoch) {
      void this.#reseed(live, epoch, peers);
      return;
    }
    live.epoch = epoch;
    this.#startSync(live, peers);
  }

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
      this.#arm(live, false);
      return;
    }
    this.note = "synchronisation avec ton équipe…";
    live.armTimer = setTimeout(() => this.#arm(live, true), SYNC_DEADLINE);
  }

  #arm(live: Live, expired: boolean): void {
    if (this.#live !== live) return;
    if (live.armTimer) clearTimeout(live.armTimer);
    if (!live.seeded) {
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
    live.epoch = epoch;
    live.seeded = false;
    editor.lock(true);
    const fresh = await fetchDocument(live.assignment, live.exercise);
    if (this.#live !== live) return;
    live.server = fresh?.sources ?? {};
    live.doc = new Y.Doc();
    collaborators.carets = {};
    this.#buildDoc(live);
    this.#startSync(live, peers);
  }

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
    drafts.say(
      answer.ok
        ? "partagé avec ton équipe · " + clockNow()
        : "NON enregistré — garde une copie de ton code",
      !answer.ok,
    );
  }

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
