import { fetchActivity } from "../api/forum";
import { session, whenSignedOut } from "../auth/session.svelte";
import { localGet, localSet } from "../storage";
import { dock } from "./dock.svelte";

const KEY = "ctester.chat.seen";
const EVERY = 60_000;

// ponytail: a poll, not a push. /forum/live only rings the room of the thread a client is
// watching; waking every tab on every message would need a global room and per-account memory.
class Unread {
  activity = $state<Record<string, string>>({});
  seen = $state<Record<string, string>>(read());

  #timer: ReturnType<typeof setInterval> | null = null;

  get any(): boolean {
    return Object.keys(this.activity).some((key) => this.has(key));
  }

  has(key: string): boolean {
    return !!key && this.activity[key] > (this.seen[key] ?? "");
  }

  /** The marker is always the server's own timestamp, never the browser's clock. */
  markSeen(key: string): void {
    const last = this.activity[key];
    if (!key || !last || this.seen[key] === last) return;
    this.seen = { ...this.seen, [key]: last };
    localSet(KEY, JSON.stringify(this.seen));
    dock.unread = this.any;
  }

  async refresh(): Promise<void> {
    if (!session.signedIn) return;
    const answer = await fetchActivity();
    if (answer && answer.threads) this.activity = answer.threads;
    dock.unread = this.any;
  }

  /** Reading a thread clears its dot: re-poll first, so a message that landed since the
   * last poll is not marked seen without ever having been shown. */
  async see(key: string): Promise<void> {
    if (!key || !session.signedIn) return;
    await this.refresh();
    this.markSeen(key);
  }

  start(): void {
    if (this.#timer) return;
    this.#timer = setInterval(() => {
      if (!document.hidden) void this.refresh();
    }, EVERY);
    document.addEventListener("visibilitychange", this.#wake);
    void this.refresh();
  }

  stop(): void {
    if (this.#timer) clearInterval(this.#timer);
    this.#timer = null;
    document.removeEventListener("visibilitychange", this.#wake);
    this.activity = {};
    dock.unread = false;
  }

  #wake = (): void => {
    if (!document.hidden) void this.refresh();
  };
}

function read(): Record<string, string> {
  try {
    const kept = JSON.parse(localGet(KEY) || "{}");
    return kept && typeof kept === "object" ? kept : {};
  } catch {
    return {};
  }
}

export const unread = new Unread();

whenSignedOut(() => unread.stop());
