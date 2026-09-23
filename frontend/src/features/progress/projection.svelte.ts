import { fetchProgress } from "../../lib/api/account";
import { whenSignedOut } from "../../lib/auth/session.svelte";
import { view } from "../../lib/state/view.svelte";
import { t } from "../../lib/i18n.svelte";
import type { ProgressPayload } from "../../lib/api/types";

class Projection {
  payload = $state<ProgressPayload | null>(null);
  error = $state("");

  async load(): Promise<void> {
    const answer = await fetchProgress();
    if (!answer || typeof answer.xp !== "number") {
      this.payload = null;
      this.error = t("progress.unavailable");
      return;
    }
    this.payload = answer;
    this.error = "";
  }

  async refreshIfOpen(): Promise<void> {
    if (this.payload === null && view.current !== "progress") return;
    await this.load();
  }

  forget(): void {
    this.payload = null;
    this.error = "";
    if (view.current === "progress") view.show("");
  }
}

export const projection = new Projection();

whenSignedOut(() => projection.forget());
