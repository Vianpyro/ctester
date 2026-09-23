import { t } from "../i18n.svelte";

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

  show(name: ViewName): void {
    this.current = name;
  }

  label(name: ViewName, closed: string): string {
    return this.current === name ? t("view.back") : closed;
  }
}

export const view = new ViewState();
