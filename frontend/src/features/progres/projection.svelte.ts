// "MES PROGRÈS": a signed-in account's PRIVATE projection.
//
// NOTHING IS COMPUTED HERE. The balance, the level, the skills, the achievements and the
// recommendation arrive ready-made from `GET /progres`, which derives them from facts the
// server itself wrote. A page that computed its own XP would be a page where one gives
// it to oneself from the console -- that is the mistake a browser-declared verdict
// already cost, in smaller.
//
// A MISSING PROJECTION IS NOT A ZERO, and the two are DISTINCT: `null` with an error
// means "we do not know". Announcing "0 XP" to somebody whose database is down tells
// them their work is gone.

import { fetchProgress } from "../../lib/api/account";
import { whenSignedOut } from "../../lib/auth/session.svelte";
import { view } from "../../lib/state/view.svelte";
import type { ProgressPayload } from "../../lib/api/types";

class Projection {
  payload = $state<ProgressPayload | null>(null);
  error = $state("");

  async load(): Promise<void> {
    const answer = await fetchProgress();
    if (!answer || typeof answer.xp !== "number") {
      this.payload = null;
      this.error =
        "Tes progrès ne sont pas disponibles pour l'instant. L'exercice et le bouton " +
        "« Tester », eux, fonctionnent normalement.";
      return;
    }
    this.payload = answer;
    this.error = "";
  }

  /** AFTER A VERDICT. Redone even when the view is closed: opening it afterwards must
   *  not show the second-to-last submission. */
  async refreshIfOpen(): Promise<void> {
    if (this.payload === null && view.current !== "progres") return;
    await this.load();
  }

  forget(): void {
    this.payload = null;
    this.error = "";
    if (view.current === "progres") view.show("");
  }
}

export const projection = new Projection();

whenSignedOut(() => projection.forget());
