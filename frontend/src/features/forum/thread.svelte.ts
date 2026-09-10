// THE THREAD, AND THERE IS ONE STATE FOR THREE SURFACES: the chat dock, the wide view
// and the moderation screen. Two states would have diverged at the first message
// posted from one while the other was open.
//
// `messages === null` WITH AN ERROR MEANS "WE DO NOT KNOW". It must never display as
// an empty thread: announcing "nobody has written here" during an outage tells
// somebody nobody answered them, and that would be false.
//
// THIS MODULE DECIDES NOTHING about permissions. Who is a moderator, which messages
// are visible, who may delete or hide: the API settles all of it from the
// authenticated `sub`, and every route recomputes it.
//
// TWO CHANNELS AND A CHECKBOX. `# général` and `# <exercice>` are the channels; asking
// the instructor privately is a BOX UNDER THE FIELD, and it does not ask the server for
// an exception -- it changes the THREAD KEY sent (`tp2-ex3` instead of
// `@chat:tp2-ex3`), which `threadKey()` already knows how to produce. Zero routes, zero
// schema, and "in the chat everything is public" stays true to the letter.

import {
  CHAT_GENERAL,
  CHAT_PREFIX,
  bareExercise,
  fetchConversation,
  fetchHelp,
  fetchModeration,
  fetchThread,
  fetchTop,
  moderate as moderateCall,
  openToGroup as openToGroupCall,
  post as postCall,
  remove as removeCall,
  report as reportCall,
  search as searchCall,
  vote as voteCall,
  type PostExtra,
} from "../../lib/api/forum";
import { refusal, type ApiResult } from "../../lib/api/client";
import { session, whenSignedOut } from "../../lib/auth/session.svelte";
import { catalog } from "../../lib/state/catalog.svelte";
import { editor } from "../../lib/state/editor.svelte";
import { view } from "../../lib/state/view.svelte";
import { renderAvailable } from "../../lib/domain/markdown";
import type {
  ForumMessage,
  HelpPayload,
  Legend,
  ModerationPayload,
  SearchResult,
  ThreadState,
  TopPayload,
} from "../../lib/api/types";

export type ChannelMode = "chat-general" | "chat-ex" | "forum";

const UNREACHABLE =
  "Les discussions ne sont pas disponibles pour l'instant. L'exercice et le bouton " +
  "« Tester », eux, fonctionnent normalement.";

class Thread {
  /** The thread key being read: `@chat:general`, `@chat:<id>` or a bare exercise id. */
  key = $state("");
  mode = $state<ChannelMode>("chat-ex");
  /** `null` means "we do not know". Never render it as an empty thread. */
  messages = $state<ForumMessage[] | null>(null);
  error = $state("");
  /** The server says which space this is; the page never re-derives it. */
  isChat = $state(true);
  moderator = $state(false);
  max = $state(0);
  steps = $state<Legend[]>([]);
  blockedKinds = $state<Legend[]>([]);
  state = $state<ThreadState | null>(null);
  /** What just happened, or its refusal. The only link between click and outcome. */
  said = $state("");

  /** The root being replied to, or null. */
  replyTo = $state<string | null>(null);
  /** A conversation opened from the search: one thread, out of any window. */
  permalink = $state<string | null>(null);
  results = $state<SearchResult[] | null>(null);
  duplicates = $state<SearchResult[] | null>(null);
  /** The exercise chosen IN the view, if it was. `currentExercise` is sticky. */
  forcedExercise = $state("");
  /** The draft in the composer, kept across redraws. */
  typing = $state("");
  renderable = $state(false);

  // The moderator's own reads. `null` is NOT "nobody": during an outage those are
  // opposite claims, and the wrong one sends an instructor home.
  reports = $state<ModerationPayload["reports"] | null>(null);
  reportedNames = $state<ModerationPayload["reported_names"] | null>(null);
  help = $state<HelpPayload | null>(null);
  top = $state<TopPayload | null>(null);

  #socket: WebSocket | null = null;
  #backoff = 1000;
  #reauth = false;
  /**
   * HOW MANY SURFACES ARE WATCHING. The dock and the wide view each claim one while
   * they are on screen, and the socket only reconnects while at least one does -- a
   * room held per open tab and per thread while somebody codes would be the load the
   * presence counter already refused. It is a COUNT rather than a reference to the
   * dock: this module then needs to know nothing about who is watching.
   */
  #watchers = 0;

  /**
   * THE EXERCISE THE THREAD IS ABOUT, never the thread key. `key` carries
   * `@chat:tp2-ex3` as well as `tp2-ex3`: looking it up as-is would find nothing and
   * fall silently back to the first exercise in the list.
   */
  get currentExercise(): string {
    const bare = bareExercise(this.key);
    const target =
      this.forcedExercise || bare || editor.exerciseId || catalog.selectedId;
    const found = catalog.catalog.find((t) => t.id === target) ?? catalog.catalog[0];
    return found ? found.id : "";
  }

  /** THE THREAD KEY IS COMPUTED IN ONE PLACE, so no prefix is ever built elsewhere. */
  threadKey(): string {
    if (this.mode === "chat-general") return CHAT_GENERAL;
    const ex = this.currentExercise;
    if (!ex) return this.mode === "chat-ex" ? CHAT_GENERAL : "";
    return this.mode === "forum" ? ex : CHAT_PREFIX + ex;
  }

  /** THE BOX IS ONLY OFFERED WHERE IT WORKS: `# général` has no exercise to attach a
   *  private question to, and one that worked half the time is worse than absent. */
  get canAskPrivately(): boolean {
    return this.isChat && !this.replyTo && this.mode === "chat-ex" && !!this.currentExercise;
  }

  // --- Reading -----------------------------------------------------------------

  /** THE THREAD ALONE, without the profile or the moderator's queues: the full open
   *  adds up to five requests, acceptable once, not on EVERY exercise change with the
   *  dock open. */
  async loadThread(key: string): Promise<boolean> {
    this.messages = null;
    this.reports = null;
    this.reportedNames = null;
    // ONE DOES NOT REPLY TO A MESSAGE IN ANOTHER THREAD. Changing threads drops the
    // target: without this, `reply_to` would name a root the server refuses (its
    // `WHERE` requires the same thread) and the student would read "message
    // introuvable" without understanding why.
    if (key !== this.key) {
      this.replyTo = null;
      this.permalink = null;
    }
    this.key = key;
    if (!session.signedIn) {
      this.error = "Reconnecte-toi pour ouvrir le chat.";
      return false;
    }
    if (!key) {
      this.error = "Aucun exercice n'est publié pour l'instant.";
      return false;
    }
    const answer = await fetchThread(key);
    if (!answer || !Array.isArray(answer.messages)) {
      this.error = UNREACHABLE;
      return false;
    }
    this.messages = answer.messages;
    this.isChat = !!answer.chat;
    this.moderator = !!answer.moderator;
    this.max = answer.max || 0;
    this.steps = Array.isArray(answer.steps) ? answer.steps : [];
    this.blockedKinds = Array.isArray(answer.blocked_kinds) ? answer.blocked_kinds : [];
    this.state = answer.state ?? null;
    this.error = "";
    return true;
  }

  /** The report queue is only ever requested BY a moderator, and the server refuses
   *  everyone else: this check just avoids a needless 403, it protects nothing. */
  async loadExtras(): Promise<void> {
    if (this.moderator) {
      const queue = await fetchModeration();
      this.reports = queue && Array.isArray(queue.reports) ? queue.reports : null;
      this.reportedNames =
        queue && Array.isArray(queue.reported_names) ? queue.reported_names : null;
      // "QUI A BESOIN D'AIDE" IS READ WITH THE QUEUE, not on its own tab: an
      // instructor opening moderation during a lab wants both, and two clicks for two
      // halves of the same question is one click too many.
      const helped = await fetchHelp();
      this.help = helped && Array.isArray(helped.rows) ? helped : null;
      const topped = await fetchTop();
      this.top = topped && Array.isArray(topped.rows) ? topped : null;
    }
    const { identity } = await import("./identity.svelte");
    await identity.load();
  }

  async load(key: string): Promise<void> {
    if (!(await this.loadThread(key))) return;
    await this.loadExtras();
  }

  /** Open a channel. `base` forces which exercise the channel is about. */
  async openChannel(mode: ChannelMode, base?: string): Promise<void> {
    this.mode = mode;
    this.said = "";
    this.permalink = null;
    if (base !== undefined) this.forcedExercise = base;
    await this.load(this.threadKey());
    void this.connect();
  }

  // --- Writing -----------------------------------------------------------------

  async #write(
    call: () => Promise<ApiResult<{ ok: boolean }>>,
    good: string,
    bad: string,
  ): Promise<boolean> {
    const answer = await call();
    const ok = !!answer?.ok;
    // THE API'S MESSAGE IS REUSED AS-IS when there is one -- "message trop long",
    // "trop de messages d'un coup". Replacing it with "échec" makes somebody try the
    // exact same thing again.
    this.said = ok ? good : bad + " : " + refusal(answer, "refusé");
    if (ok) await this.load(this.key);
    return ok;
  }

  async post(text: string, extra: PostExtra = {}): Promise<boolean> {
    const ok = await this.#write(
      () => postCall(this.key, text, extra),
      "Message publié.",
      "Message non publié",
    );
    // CLEARED AFTERWARD, AND ONLY IF IT WENT THROUGH. A refusal -- too long, quota --
    // must leave the text on screen: losing it makes somebody retype the same thing
    // with the rule no longer in front of them.
    if (ok) this.typing = "";
    return ok;
  }

  remove = (id: string) =>
    this.#write(() => removeCall(id), "Ton message a été supprimé.", "Suppression impossible");

  report = (id: string) =>
    this.#write(
      () => reportCall(id),
      "Signalé. Un responsable du cours va le lire.",
      "Signalement impossible",
    );

  reportName = (id: string) =>
    this.#write(
      () => reportCall(id, "name"),
      "Nom signalé. Un responsable du cours va le lire.",
      "Signalement impossible",
    );

  /** THE ONE TRANSITION: private -> group, on one's own message. The server holds the
   *  rule in its `WHERE`; this only asks. */
  openToGroup = (id: string) =>
    this.#write(
      () => openToGroupCall(id),
      "Ta question est maintenant visible par ton groupe.",
      "Impossible de l'ouvrir à ton groupe",
    );

  /** IT GRANTS NOTHING: no XP, no achievement, no card. */
  vote = (id: string, value: -1 | 0 | 1) =>
    this.#write(
      () => voteCall(id, value),
      value === 0 ? "Vote retiré." : "Merci — ça aide les suivants.",
      "Impossible de voter",
    );

  moderate = (id: string, action: "hide" | "restore" | "retain" | "unretain") =>
    this.#write(
      () => moderateCall(id, action),
      action === "hide" ? "Message masqué." : action === "restore" ? "Message rétabli." : "C'est noté.",
      "Action impossible",
    );

  clearName = (id: string) =>
    this.#write(() => moderateCall(id, "clear-name"), "Nom effacé.", "Action impossible");

  // --- Search and permalinks ---------------------------------------------------

  async search(terms: string): Promise<SearchResult[]> {
    return await searchCall(terms);
  }

  async runSearch(terms: string): Promise<void> {
    this.results = await this.search(terms);
  }

  /** THE PERMALINK: a search result three thousand messages old is in the window of no
   *  thread, so without it the search shows excerpts one cannot open. */
  async openPermalink(id: string): Promise<void> {
    const answer = await fetchConversation(id);
    if (!answer || !Array.isArray(answer.messages)) {
      this.said = "Cette conversation n'est pas disponible.";
      return;
    }
    this.messages = answer.messages;
    this.isChat = !!answer.chat;
    this.permalink = id;
    this.state = null;
  }

  async backToThread(): Promise<void> {
    this.permalink = null;
    await this.load(this.threadKey());
  }

  // --- The bell -----------------------------------------------------------------
  // THE SOCKET IS A DOORBELL, NOT A TRANSPORT. It sends `{"t":"new"}` and nothing
  // else; the client re-reads `GET /forum`. That is what keeps `can_see()`, the quota,
  // the length bound, the closed lists and the alias draw in ONE place. Free
  // consequence: a reader with no right on a message gets the bell and redraws the same
  // thing -- even the EXISTENCE of the message does not leak.
  //
  // DEGRADE, NEVER BLOCK: a dead socket means the thread reloads on action, as before.
  // That is the opposite of the team room, where a missing Yjs must LOCK the editor --
  // there a "best effort" would destroy work, here it costs a click.

  get socketOpen(): boolean {
    return !!this.#socket;
  }

  disconnect(): void {
    const old = this.#socket;
    this.#socket = null;
    if (old) {
      try {
        old.close();
      } catch {
        /* already closed */
      }
    }
  }

  /** `resumed` tells a reconnection from a gesture, and that is what bounds the token
   *  renewal to one per chain: a student's action starts from a clean slate, an
   *  automatic reconnection inherits the previous attempt. */
  async connect(resumed = false): Promise<void> {
    this.disconnect();
    if (!resumed) this.#reauth = false;
    if (!session.signedIn || !this.key) return;
    const { socketUrl } = await import("../../lib/config");
    const { ensureValid, renew } = await import("../../lib/auth/session.svelte");
    // THE TOKEN GOES IN THE FIRST FRAME, so it has to still be good before opening --
    // otherwise the bell is refused on 4401 and the panel stays mute for a reconnection.
    await ensureValid();
    const aimedAt = this.key;
    if (this.#socket || !session.signedIn || aimedAt !== this.key) return;
    let socket: WebSocket;
    try {
      socket = new WebSocket(socketUrl("/forum/live"));
    } catch {
      return; // no live updates: everything else works
    }
    this.#socket = socket;
    socket.onopen = () => {
      this.#backoff = 1000;
      // IN THE FIRST FRAME, NEVER IN THE URL: a browser cannot set an `Authorization`
      // header on a WebSocket, and a token in a query string is a token in every proxy
      // log on the path.
      try {
        socket.send(JSON.stringify({ t: "hello", token: session.token, thread: aimedAt }));
      } catch {
        /* closed in between */
      }
    };
    socket.onmessage = (event) => {
      let frame: { t?: string } | null = null;
      try {
        frame = JSON.parse(String(event.data)) as { t?: string };
      } catch {
        return;
      }
      if (frame?.t === "new") void this.refresh();
    };
    socket.onclose = (event) => {
      if (this.#socket !== socket) return; // replaced: nothing to reconnect
      this.#socket = null;
      // THE DOCK COUNTS AS MUCH AS THE VIEW. Without this half, a one-second outage
      // left the side panel mute for the rest of the session, with nothing saying so.
      if (this.#watchers === 0) return;
      if (event.code === UNAUTHORIZED && !this.#reauth) {
        this.#reauth = true;
        void renew().then((ok) => {
          if (ok) void this.connect(true);
        });
        return;
      }
      setTimeout(() => void this.connect(true), this.#backoff);
      this.#backoff = Math.min(this.#backoff * 2, 30_000);
    };
  }

  /**
   * THE SIGNATURE AVOIDS REDRAWING FOR NOTHING. Without it, every bell would recreate
   * the composer and throw the caret to the end while somebody is typing. It carries
   * what changes on screen: the ids, the hiding and the votes.
   */
  static signature(messages: ForumMessage[] | null): string {
    return (messages ?? [])
      .map(
        (m) =>
          m.id + ":" + (m.hidden ? 1 : 0) + ":" + m.upvotes + ":" + m.downvotes +
          ":" + m.my_vote + ":" + (m.retained ? 1 : 0),
      )
      .join(",");
  }

  /** THE THREAD ALONE, not `load()`: that one chains the moderation queue and the help
   *  aggregate for a moderator -- two extra requests per message posted in the room. */
  async refresh(): Promise<void> {
    if (this.permalink || !session.signedIn || !this.key) return;
    const before = Thread.signature(this.messages);
    const answer = await fetchThread(this.key);
    if (!answer || !Array.isArray(answer.messages)) return;
    if (Thread.signature(answer.messages) === before) return;
    this.messages = answer.messages;
    this.state = answer.state ?? null;
  }

  /** A surface starts watching. Returns the release, so a component can call it from
   *  its own teardown and cannot forget. */
  watch(): () => void {
    this.#watchers++;
    return () => {
      this.#watchers = Math.max(0, this.#watchers - 1);
      if (this.#watchers === 0) this.disconnect();
    };
  }

  async prepareRendering(): Promise<void> {
    this.renderable = renderAvailable();
  }

  forget(): void {
    // THE SOCKET LEAVES WITH THE SESSION. Without this, signing out would leave a room
    // open on a token that is no longer valid.
    this.disconnect();
    this.messages = null;
    this.reports = null;
    this.reportedNames = null;
    this.help = null;
    this.top = null;
    this.state = null;
    this.steps = [];
    this.blockedKinds = [];
    this.moderator = false;
    this.replyTo = null;
    this.permalink = null;
    this.results = null;
    this.duplicates = null;
    this.forcedExercise = "";
    this.typing = "";
    this.error = "";
    this.said = "";
    this.#watchers = 0;
    if (view.current === "forum" || view.current === "moderation") view.show("");
  }
}

const UNAUTHORIZED = 4401;

export const thread = new Thread();

whenSignedOut(() => thread.forget());
