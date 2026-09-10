// THE PRESENCE COUNTER, FOR EVERYONE -- the anonymous visitor included. It is THE
// ONLY REQUEST THE ANONYMOUS PATH EVER EMITS, and the exception is assumed: the
// heartbeat reaches an in-memory dict server-side, never the database and never an
// account, and it carries no token.
//
// POLLING, NOT A WEBSOCKET. One uvicorn worker in front of a single Postgres
// connection: 200 persistent sockets have no business there. One beat every 60 s
// times 200 students is ~3 req/s on a dict operation.
// ponytail: back to a WebSocket the day "live" has to mean something finer than
// "to the minute".
//
// A FAILURE IS INVISIBLE, deliberately: the counter stays hidden. It must never
// get in the way of an exercise.

import { fetchPresence } from "../api/public";
import { randomId, sessionGet, sessionSet } from "../storage";

const BEAT = 60_000;
const ID_KEY = "ctester.live";

function windowId(): string {
  const held = sessionGet(ID_KEY);
  if (held) return held;
  const fresh = randomId();
  sessionSet(ID_KEY, fresh);
  return fresh;
}

class Presence {
  /** null while unknown -- the counter is then not drawn at all. */
  count = $state<number | null>(null);

  get label(): string {
    const n = this.count;
    if (n === null) return "";
    return n > 1 ? n + " personnes en ligne" : "1 personne en ligne";
  }

  async beat(): Promise<void> {
    const answer = await fetchPresence(windowId());
    if (answer && typeof answer.n === "number") this.count = answer.n;
  }

  /** Returns the stop function, so a test can shut the interval down. */
  start(): () => void {
    void this.beat();
    const timer = setInterval(() => void this.beat(), BEAT);
    return () => clearInterval(timer);
  }
}

export const presence = new Presence();
