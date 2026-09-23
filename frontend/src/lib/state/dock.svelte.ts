import { localGet, localSet } from "../storage";

const KEY = "ctester.chat.open";

class Dock {
  open = $state(false);
  // The top bar's dot; lib/state/unread.svelte.ts sets it once signed in.
  unread = $state(false);
  // Keeps the chat column from the first paint, so the grid does not shift when the dock
  // arrives. App.svelte drops it if the dock is not coming.
  reserved = $state(localGet(KEY) === "1");

  remembered(): boolean {
    return localGet(KEY) === "1";
  }

  set(open: boolean): void {
    this.open = open;
    this.reserved = open;
    localSet(KEY, open ? "1" : "");
  }

  restore(): void {
    this.open = true;
    this.reserved = true;
  }
}

export const dock = new Dock();
