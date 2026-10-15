import { t } from "../i18n.svelte";
import { transit } from "../transit";

export type ViewName =
  | ""
  | "progress"
  | "forum"
  | "moderation"
  | "leaderboard"
  | "collection"
  | "scratch";

class ViewState {
  current = $state<ViewName>("");

  // Asynchronous under a View Transition: no caller reads `current` right after.
  show(name: ViewName): void {
    transit(name ? "in" : "out", () => (this.current = name));
  }

  label(name: ViewName, closed: string): string {
    return this.current === name ? t("view.back") : closed;
  }
}

export const view = new ViewState();
