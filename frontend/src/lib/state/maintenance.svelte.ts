import { api } from "../config";

// How long "the server is back" stays up once an update is over.
const BACK_MS = 10_000;
const RETRY_MIN = 2_000;
const RETRY_MAX = 30_000;

export type Phase = "idle" | "down" | "back";

class Maintenance {
  phase = $state<Phase>("idle");

  #source: EventSource | null = null;
  #retry: ReturnType<typeof setTimeout> | null = null;
  #settle: ReturnType<typeof setTimeout> | null = null;
  #delay = RETRY_MIN;

  // "Back" is only said by a server that answers: the stream dies with the restart, and
  // "down" stays up across the gap.
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
        this.apply(!!JSON.parse((event as MessageEvent).data).maintenance);
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
