export interface Chord {
  key: string;
  shiftKey: boolean;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
}

export type ShortcutId =
  | "commentLine"
  | "commentBlock"
  | "duplicate"
  | "deleteLine"
  | "moveUp"
  | "moveDown"
  | "completeStatement"
  | "nextIssue"
  | "gotoLine"
  | "save"
  | "run"
  | "help"
  | "catalog"
  | "escape";

interface Binding {
  id: ShortcutId;
  keys: string[];
  ctrl?: boolean;
  shift?: boolean | "any";
  alt?: boolean;
}

// Keys are the produced characters, not event.code: on a Canadian French layout
// the Slash key types "é". AltGr reports Ctrl+Alt on Windows, hence the exact alt match.
const BINDINGS: Binding[] = [
  { id: "commentLine", keys: ["/"], ctrl: true, shift: "any" },
  { id: "commentBlock", keys: ["?"], ctrl: true, shift: "any" },
  { id: "duplicate", keys: ["d"], ctrl: true },
  // Ctrl+Shift+K for VS Code habits, Ctrl+Shift+D because Firefox keeps the former.
  { id: "deleteLine", keys: ["k", "d"], ctrl: true, shift: true },
  { id: "moveUp", keys: ["ArrowUp"], alt: true, shift: true },
  { id: "moveDown", keys: ["ArrowDown"], alt: true, shift: true },
  { id: "completeStatement", keys: ["Enter"], ctrl: true, shift: true },
  { id: "nextIssue", keys: ["F2"] },
  { id: "gotoLine", keys: ["g"], ctrl: true },
  { id: "save", keys: ["s"], ctrl: true },
  { id: "run", keys: ["Enter"], ctrl: true },
  { id: "help", keys: ["F1"] },
  { id: "catalog", keys: ["k"], ctrl: true },
  { id: "escape", keys: ["Escape"] },
];

export const EDITOR_COMMANDS: ReadonlySet<ShortcutId> = new Set<ShortcutId>([
  "commentLine",
  "commentBlock",
  "duplicate",
  "deleteLine",
  "moveUp",
  "moveDown",
  "completeStatement",
  "nextIssue",
  "gotoLine",
]);

export const TEXT_COMMANDS: ReadonlySet<ShortcutId> = new Set<ShortcutId>([
  "commentLine",
  "commentBlock",
  "duplicate",
  "deleteLine",
  "moveUp",
  "moveDown",
  "completeStatement",
]);

export function matchShortcut(chord: Chord): ShortcutId | null {
  const key = chord.key.length === 1 ? chord.key.toLowerCase() : chord.key;
  const ctrl = chord.ctrlKey || chord.metaKey;
  for (const binding of BINDINGS) {
    if (!binding.keys.includes(key)) continue;
    if ((binding.ctrl ?? false) !== ctrl) continue;
    if ((binding.alt ?? false) !== chord.altKey) continue;
    const shift = binding.shift ?? false;
    if (shift !== "any" && shift !== chord.shiftKey) continue;
    return binding.id;
  }
  return null;
}
