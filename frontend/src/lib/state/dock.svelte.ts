import { localGet, localSet } from "../storage";

const KEY = "ctester.chat.ouvert";

class Dock {
  open = $state(false);

  remembered(): boolean {
    return localGet(KEY) === "1";
  }

  set(open: boolean): void {
    this.open = open;
    localSet(KEY, open ? "1" : "");
  }

  restore(): void {
    this.open = true;
  }
}

export const dock = new Dock();
