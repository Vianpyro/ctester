import type { TeamMember } from "../api/types";

export interface CaretPosition {
  file: string;
  anchor: number;
  head: number;
}

class Collaborators {
  active = $state(false);
  members = $state<TeamMember[]>([]);
  online = $state<string[]>([]);
  carets = $state<Record<string, CaretPosition>>({});
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
