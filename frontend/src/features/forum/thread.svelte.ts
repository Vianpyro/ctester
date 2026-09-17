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
import { unread } from "../../lib/state/unread.svelte";
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
  key = $state("");
  mode = $state<ChannelMode>("chat-ex");
  messages = $state<ForumMessage[] | null>(null);
  error = $state("");
  isChat = $state(true);
  moderator = $state(false);
  max = $state(0);
  steps = $state<Legend[]>([]);
  blockedKinds = $state<Legend[]>([]);
  state = $state<ThreadState | null>(null);
  said = $state("");

  replyTo = $state<string | null>(null);
  permalink = $state<string | null>(null);
  results = $state<SearchResult[] | null>(null);
  duplicates = $state<SearchResult[] | null>(null);
  forcedExercise = $state("");
  typing = $state("");
  renderable = $state(false);

  reports = $state<ModerationPayload["reports"] | null>(null);
  reportedNames = $state<ModerationPayload["reported_names"] | null>(null);
  help = $state<HelpPayload | null>(null);
  top = $state<TopPayload | null>(null);

  #socket: WebSocket | null = null;
  #backoff = 1000;
  #reauth = false;
  #watchers = 0;

  get currentExercise(): string {
    const bare = bareExercise(this.key);
    const target =
      this.forcedExercise || bare || editor.exerciseId || catalog.selectedId;
    const found = catalog.catalog.find((t) => t.id === target) ?? catalog.catalog[0];
    return found ? found.id : "";
  }

  threadKey(): string {
    if (this.mode === "chat-general") return CHAT_GENERAL;
    const ex = this.currentExercise;
    if (!ex) return this.mode === "chat-ex" ? CHAT_GENERAL : "";
    return this.mode === "forum" ? ex : CHAT_PREFIX + ex;
  }

  get canAskPrivately(): boolean {
    return this.isChat && !this.replyTo && this.mode === "chat-ex" && !!this.currentExercise;
  }

  async loadThread(key: string): Promise<boolean> {
    this.messages = null;
    this.reports = null;
    this.reportedNames = null;
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
    void unread.see(key);
    return true;
  }

  async loadExtras(): Promise<void> {
    if (this.moderator) {
      const queue = await fetchModeration();
      this.reports = queue && Array.isArray(queue.reports) ? queue.reports : null;
      this.reportedNames =
        queue && Array.isArray(queue.reported_names) ? queue.reported_names : null;
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

  async openChannel(mode: ChannelMode, base?: string): Promise<void> {
    this.mode = mode;
    this.said = "";
    this.permalink = null;
    if (base !== undefined) this.forcedExercise = base;
    await this.load(this.threadKey());
    void this.connect();
  }

  async #write(
    call: () => Promise<ApiResult<{ ok: boolean }>>,
    good: string,
    bad: string,
  ): Promise<boolean> {
    const answer = await call();
    const ok = !!answer?.ok;
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

  openToGroup = (id: string) =>
    this.#write(
      () => openToGroupCall(id),
      "Ta question est maintenant visible par ton groupe.",
      "Impossible de l'ouvrir à ton groupe",
    );

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

  async search(terms: string): Promise<SearchResult[]> {
    return await searchCall(terms);
  }

  async runSearch(terms: string): Promise<void> {
    this.results = await this.search(terms);
  }

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
      }
    }
  }

  async connect(resumed = false): Promise<void> {
    this.disconnect();
    if (!resumed) this.#reauth = false;
    if (!session.signedIn || !this.key) return;
    const { socketUrl } = await import("../../lib/config");
    const { ensureValid, renew } = await import("../../lib/auth/session.svelte");
    await ensureValid();
    const aimedAt = this.key;
    if (this.#socket || !session.signedIn || aimedAt !== this.key) return;
    let socket: WebSocket;
    try {
      socket = new WebSocket(socketUrl("/forum/live"));
    } catch {
      return;
    }
    this.#socket = socket;
    socket.onopen = () => {
      this.#backoff = 1000;
      try {
        socket.send(JSON.stringify({ t: "hello", token: session.token, thread: aimedAt }));
      } catch {
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
      if (this.#socket !== socket) return;
      this.#socket = null;
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

  static signature(messages: ForumMessage[] | null): string {
    return (messages ?? [])
      .map(
        (m) =>
          m.id + ":" + (m.hidden ? 1 : 0) + ":" + m.upvotes + ":" + m.downvotes +
          ":" + m.my_vote + ":" + (m.retained ? 1 : 0),
      )
      .join(",");
  }

  async refresh(): Promise<void> {
    if (this.permalink || !session.signedIn || !this.key) return;
    const before = Thread.signature(this.messages);
    const answer = await fetchThread(this.key);
    if (!answer || !Array.isArray(answer.messages)) return;
    if (Thread.signature(answer.messages) === before) return;
    this.messages = answer.messages;
    this.state = answer.state ?? null;
    void unread.see(this.key);
  }

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
