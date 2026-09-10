// ONE SCREEN AT A TIME, AND THE ARBITRATION LIVES HERE.
//
// "Mes progrès", the discussions, the leaderboard, the collection and the Console
// are five separately loaded modules. If each hid the others on its own, opening
// the second over the first would leave both halves on screen, or neither. So
// there is one value, and the shell reads it.
//
// THE EXERCISE IS `""`, and going back to it does NOT re-open the exercise: that
// is what keeps the editor and the verdict exactly where they were left.
//
// THE CHAT DOCK IS NOT ONE OF THESE. It is a COLUMN inside the exercise screen,
// not a destination -- which is why it disappears on its own when another view
// takes the screen, and comes back unchanged on return.

export type ViewName =
  | ""
  | "progres"
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

  /** A view's own button doubles as "Retour à l'exercice" when it is open. */
  label(name: ViewName, closed: string): string {
    return this.current === name ? "Retour à l'exercice" : closed;
  }
}

export const view = new ViewState();
