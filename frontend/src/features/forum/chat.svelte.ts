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
    if (view.current === "forum" || view.current === "moderation") {
      view.show("");
      return;
    }
    dock.set(!dock.open);
    if (!dock.open) return;
    await this.#openDock();
  }

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

  async followExercise(): Promise<void> {
    if (!this.dockOpen || thread.mode === "chat-general") return;
    const open = editor.exerciseId;
    if (!open) return;
    thread.forcedExercise = open;
    const aimed = thread.threadKey();
    if (!aimed || aimed === thread.key) return;
    thread.said = "";
    await thread.loadThread(aimed);
    void thread.connect();
  }

  forget(): void {
    dock.set(false);
  }
}

export const chat = new Chat();

whenSignedOut(() => chat.forget());

whenChatReady(() => chat.followExercise());
