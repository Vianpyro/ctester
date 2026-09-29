import { api } from "../config";
import { localGet, localSet } from "../storage";

// How long "the server is back" stays up once an update is over.
const BACK_MS = 10_000;
const RETRY_MIN = 2_000;
const RETRY_MAX = 30_000;

export type Phase = "idle" | "down" | "back";
export type Announcement = { id: string; text: string };

const DISMISSED_KEY = "ctester.announcement.dismissed";

class Maintenance {
  phase = $state<Phase>("idle");
  announcement = $state<Announcement | null>(null);
  dismissed = $state(localGet(DISMISSED_KEY));

  #source: EventSource | null = null;
  #retry: ReturnType<typeof setTimeout> | null = null;
  #settle: ReturnType<typeof setTimeout> | null = null;
  #delay = RETRY_MIN;

  apply(on: boolean): void {
    if (on) {
      this.#clearSettle();
      this.phase = "down";
    } else if (this.phase === "down") {
      this.phase = "back";
      this.#settle = setTimeout(() => {
        this.#settle = null;
        this.phase = "idle";
      }, BACK_MS);
    }
  }

  get shown(): Announcement | null {
    return this.announcement && this.announcement.id !== this.dismissed ? this.announcement : null;
  }

  dismiss(): void {
    if (!this.announcement) return;
    this.dismissed = this.announcement.id;
    localSet(DISMISSED_KEY, this.dismissed);
  }

  start(): () => void {
    if (typeof EventSource === "undefined") return () => {};
    this.#open();
    return () => {
      this.#source?.close();
      this.#source = null;
      if (this.#retry) clearTimeout(this.#retry);
      this.#retry = null;
      this.#clearSettle();
    };
  }

  #open(): void {
    const source = new EventSource(api("events"));
    this.#source = source;
    source.addEventListener("state", (event) => {
      this.#delay = RETRY_MIN;
      try {
        const data = JSON.parse((event as MessageEvent).data);
        this.apply(!!data.maintenance);
        this.announcement = data.announcement || null;
      } catch {
        // A malformed event changes nothing.
      }
    });
    source.onerror = () => {
      // An error answer (the proxy's 502 during a restart) ends EventSource's own retries.
      if (source.readyState !== EventSource.CLOSED || this.#source !== source) return;
      source.close();
      this.#retry = setTimeout(() => {
        this.#retry = null;
        if (this.#source === source) this.#open();
      }, this.#delay);
      this.#delay = Math.min(this.#delay * 2, RETRY_MAX);
    };
  }

  #clearSettle(): void {
    if (this.#settle) clearTimeout(this.#settle);
    this.#settle = null;
  }
}

export const maintenance = new Maintenance();
