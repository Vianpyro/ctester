// WHETHER THE CHAT DOCK IS OPEN, AND WHETHER IT WAS LEFT OPEN.
//
// IT LIVES IN THE CORE, NOT IN THE FORUM CHUNK, for two reasons that both matter:
//
//   * the remembered flag is what decides whether the forum chunk has to be FETCHED at
//     startup, so it must be readable before that chunk exists;
//   * whether the dock is open changes the WORKBENCH GRID (one class on one element), and
//     that is a layout fact the shell owns.
//
// A constant copied into both places would eventually drift, and the symptom would be a
// panel that never comes back.
//
// `localStorage` AND NOT `sessionStorage`: the panel must be there in the second tab as
// well as tomorrow. ponytail: per device, not on the account. The theme earned a route
// (`/preferences`) because it is visible before the first paint; an open panel is not
// worth an SQL round trip.

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

  /** Opening at startup without rewriting what is remembered. */
  restore(): void {
    this.open = true;
  }
}

export const dock = new Dock();
