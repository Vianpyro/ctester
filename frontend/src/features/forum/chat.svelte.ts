// THE CHAT IS A COLUMN, NOT A FIFTH SCREEN.
//
// It used to live in a view that REPLACED the exercise: asking for help meant leaving
// one's code at the precise moment one has to look at it. The dock is the third child
// of the workbench grid; the editor SHRINKS, it is never covered -- a floating panel
// would hide the line being discussed. Under 900 px the grid goes back to a block flow
// and the dock becomes a sheet from the bottom.
//
// THE WIDE VIEW STILL EXISTS -- search, permalinks, the moderation door -- and it opens
// FROM the dock, by "⤢". Two buttons in the bar for two sizes of the same thing were
// two words to learn for one idea.
//
// THE "IS THE DOCK OPEN" KEY LIVES IN THE CORE (`lib/state/dock.ts`), not here: it is
// what decides whether this chunk has to be FETCHED at startup, so it must be readable
// before this module exists. A constant copied into both files would drift, and the
// symptom would be a panel that never comes back.

import { whenSignedOut } from "../../lib/auth/session.svelte";
import { editor } from "../../lib/state/editor.svelte";
import { whenChatReady } from "../../lib/state/exercise.svelte";
import { view } from "../../lib/state/view.svelte";
import { dock } from "../../lib/state/dock.svelte";
import { thread } from "./thread.svelte";

class Chat {
  get dockOpen(): boolean {
    return dock.open;
  }

  /** Opening without toggling: at startup, when the core remembers it was open. A chat
   *  that closes itself on every reload is a chat one loses interest in within two
   *  days. */
  async restoreDock(): Promise<void> {
    if (this.dockOpen) return;
    dock.restore();
    await this.#openDock();
  }

  async #openDock(): Promise<void> {
    await thread.prepareRendering();
    const open = editor.exerciseId;
    if (open && thread.mode !== "chat-general") thread.forcedExercise = open;
    await thread.load(thread.threadKey());
    void thread.connect();
  }

  async toggleDock(): Promise<void> {
    // THE BUTTON SAYS "Retour à l'exercice" WHEN A VIEW IS OPEN, and it must then do
    // that: close it, and leave the dock as it was. Without this branch the bar's one
    // button would have two meanings depending on the screen -- exactly the defect
    // this replaces.
    if (view.current === "forum" || view.current === "moderation") {
      view.show("");
      return;
    }
    dock.set(!dock.open);
    if (!dock.open) return;
    await this.#openDock();
  }

  /** The wide view: search, permalinks and the moderation door. */
  async toggleWide(): Promise<void> {
    if (view.current === "forum") {
      view.show("");
      return;
    }
    thread.said = "";
    await thread.prepareRendering();
    await thread.load(thread.threadKey());
    void thread.connect();
    view.show("forum");
  }

  async openModeration(): Promise<void> {
    if (view.current === "moderation") {
      await this.toggleWide();
      return;
    }
    await thread.load(thread.key || thread.threadKey());
    view.show("moderation");
  }

  /**
   * THE CHANNEL FOLLOWS THE EDITOR, and that is what allowed the second exercise menu
   * to be removed from the screen. It goes through `loadThread` and not `load`: the
   * profile and the moderator's queues do not depend on the thread, and re-reading them
   * on every exercise opened would be four requests for nothing.
   */
  async followExercise(): Promise<void> {
    if (!this.dockOpen || thread.mode === "chat-general") return;
    const open = editor.exerciseId;
    if (!open) return;
    // `currentExercise` IS STICKY ON PURPOSE: it keeps the thread being read. Here the
    // opposite is wanted, so it is forced.
    thread.forcedExercise = open;
    const aimed = thread.threadKey();
    if (!aimed || aimed === thread.key) return;
    thread.said = "";
    await thread.loadThread(aimed);
    void thread.connect();
  }

  /** THE DOCK LEAVES WITH THE SESSION: it carries signed-in accounts' messages, and
   *  leaving it on screen after a sign-out would show them to whoever follows. */
  forget(): void {
    dock.set(false);
  }
}

export const chat = new Chat();

// The session leaving takes the dock with it; the thread registers its own forgetting.
whenSignedOut(() => chat.forget());

// AND THE CHANNEL FOLLOWS THE EDITOR FROM NOW ON. Registered here rather than called from
// the core, so the core never has to import this chunk to know it exists.
whenChatReady(() => chat.followExercise());
