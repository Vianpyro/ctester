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
    return this.current === name ? "Retour à l'exercice" : closed;
  }
}

export const view = new ViewState();
