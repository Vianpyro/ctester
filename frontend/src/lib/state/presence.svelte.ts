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

  start(): () => void {
    void this.beat();
    const timer = setInterval(() => void this.beat(), BEAT);
    return () => clearInterval(timer);
  }
}

export const presence = new Presence();
