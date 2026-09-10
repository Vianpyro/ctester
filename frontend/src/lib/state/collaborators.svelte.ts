// WHO ELSE IS IN THIS DOCUMENT, AND WHERE THEIR CURSORS ARE.
//
// IT IS IN THE CORE, AND THAT IS THE WHOLE POINT OF ITS EXISTING. The caret overlay
// is drawn inside the editor, which every student sees -- so if it read the room
// directly, Yjs (92 KB) would land in the main bundle and the anonymous path would
// pay for a feature it can never use. The room WRITES here; the overlay READS. Plain
// numbers and plain strings cross, no CRDT type does, and the direction stays
// one-way like everywhere else on this page.
//
// A POSITION, NEVER AN ACCOUNT. `m1`..`m4` is what presence and cursor frames carry;
// the server derives it from the roster, so a client cannot claim to be somebody
// else's caret. It is meaningless outside this team -- there is nothing to correlate
// against another exercise, another assignment or the forum.

import type { TeamMember } from "../api/types";

export interface CaretPosition {
  file: string;
  anchor: number;
  head: number;
}

class Collaborators {
  /** True while a shared document is open. The overlay draws nothing otherwise. */
  active = $state(false);
  members = $state<TeamMember[]>([]);
  /** Position handles currently connected. */
  online = $state<string[]>([]);
  /** Position handle -> where that member's caret is, in character offsets. */
  carets = $state<Record<string, CaretPosition>>({});
  /** This tab's own handle, as the server stamped it. */
  me = $state("");

  set(members: TeamMember[], me: string): void {
    this.members = members;
    this.me = me;
    this.active = true;
  }

  setOnline(handles: string[]): void {
    this.online = handles;
  }

  setCaret(handle: string, at: CaretPosition): void {
    this.carets = { ...this.carets, [handle]: at };
  }

  clear(): void {
    this.active = false;
    this.members = [];
    this.online = [];
    this.carets = {};
    this.me = "";
  }

  /** Everyone but oneself who has a caret in the file being looked at. */
  inFile(file: string | null): { member: TeamMember; caret: CaretPosition }[] {
    if (!this.active || !file) return [];
    const out: { member: TeamMember; caret: CaretPosition }[] = [];
    for (const member of this.members) {
      const caret = this.carets[member.id];
      if (member.you || !caret || caret.file !== file) continue;
      out.push({ member, caret });
    }
    return out;
  }
}

export const collaborators = new Collaborators();
