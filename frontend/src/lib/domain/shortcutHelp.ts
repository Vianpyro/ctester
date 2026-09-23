import type { ShortcutId } from "./shortcuts";

// Each row names locale keys, not text: the panel words them in the current language.
// A cap is printed as is unless key.<cap> exists (Shift reads "Maj" in French).
export interface HelpRow {
  caps: string[];
  label: string;
  note?: string;
}

const row = (caps: string[], id: string, note = false): HelpRow => ({
  caps,
  label: `shortcuts.${id}`,
  ...(note ? { note: `shortcuts.${id}.note` } : {}),
});

export const HELP: Record<ShortcutId, HelpRow> = {
  commentLine: row(["Ctrl", "/"], "commentLine", true),
  commentBlock: row(["Ctrl", "Shift", "/"], "commentBlock", true),
  duplicate: row(["Ctrl", "D"], "duplicate"),
  deleteLine: row(["Ctrl", "Shift", "K"], "deleteLine", true),
  moveUp: row(["Alt", "Shift", "↑"], "moveUp"),
  moveDown: row(["Alt", "Shift", "↓"], "moveDown"),
  completeStatement: row(["Ctrl", "Shift", "Enter"], "completeStatement"),
  nextIssue: row(["F2"], "nextIssue"),
  gotoLine: row(["Ctrl", "G"], "gotoLine"),
  save: row(["Ctrl", "S"], "save", true),
  run: row(["Ctrl", "Enter"], "run"),
  help: row(["F1"], "help"),
  catalog: row(["Ctrl", "K"], "catalog"),
  escape: row(["Esc"], "escape"),
};

export const GROUPS: { title: string; ids: ShortcutId[] }[] = [
  {
    title: "shortcuts.group.write",
    ids: [
      "commentLine",
      "commentBlock",
      "duplicate",
      "deleteLine",
      "moveUp",
      "moveDown",
      "completeStatement",
    ],
  },
  { title: "shortcuts.group.move", ids: ["nextIssue", "gotoLine", "catalog", "escape"] },
  { title: "shortcuts.group.act", ids: ["save", "run", "help"] },
];

export const NATIVE: HelpRow[] = [
  row(["Ctrl", "Z"], "undo"),
  row(["Ctrl", "Shift", "Z"], "redo", true),
  row(["Ctrl", "F"], "find"),
  row(["Ctrl", "C"], "clipboard"),
  row(["Ctrl", "←"], "word"),
];

export const ALREADY: HelpRow[] = [
  row(["Tab"], "indent"),
  row(["Shift", "Tab"], "outdent"),
  row(["(", "[", "{", "\""], "autoclose", true),
  row(["Esc", "then", "Tab"], "leave", true),
];
