import { localGet, localSet } from "../storage";

const KEY = "ctester.chat.open";

class Dock {
  open = $state(false);
  // The dot in the top bar. Only the flag is eager: the polling that sets it comes with
  // the account, in lib/state/unread.svelte.ts.
  unread = $state(false);
  // Holds the third column from the first paint for someone who left the chat open: the
  // dock itself arrives four chunks and a sign-in later, and the grid would recompose.
  // App.svelte drops it if the dock turns out not to be coming.
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
