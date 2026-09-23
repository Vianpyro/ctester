import { describe, expect, it } from "vitest";
import {
  EDITOR_COMMANDS,
  TEXT_COMMANDS,
  matchShortcut,
  type Chord,
  type ShortcutId,
} from "../src/lib/domain/shortcuts";

function chord(key: string, mods: Partial<Omit<Chord, "key">> = {}): Chord {
  return {
    key,
    shiftKey: false,
    ctrlKey: false,
    metaKey: false,
    altKey: false,
    ...mods,
  };
}

const ctrl = (key: string, mods: Partial<Omit<Chord, "key">> = {}) =>
  chord(key, { ctrlKey: true, ...mods });

describe("what is ours", () => {
  it("binds the seven text transformations", () => {
    expect(matchShortcut(ctrl("/"))).toBe("commentLine");
    expect(matchShortcut(ctrl("?", { shiftKey: true }))).toBe("commentBlock");
    expect(matchShortcut(ctrl("d"))).toBe("duplicate");
    expect(matchShortcut(ctrl("k", { shiftKey: true }))).toBe("deleteLine");
    expect(matchShortcut(ctrl("d", { shiftKey: true }))).toBe("deleteLine");
    expect(matchShortcut(chord("ArrowUp", { altKey: true, shiftKey: true }))).toBe("moveUp");
    expect(matchShortcut(chord("ArrowDown", { altKey: true, shiftKey: true }))).toBe("moveDown");
    expect(matchShortcut(ctrl("Enter", { shiftKey: true }))).toBe("completeStatement");
  });

  it("binds navigation and the page", () => {
    expect(matchShortcut(chord("F2"))).toBe("nextIssue");
    expect(matchShortcut(ctrl("g"))).toBe("gotoLine");
    expect(matchShortcut(ctrl("s"))).toBe("save");
    expect(matchShortcut(ctrl("Enter"))).toBe("run");
    expect(matchShortcut(chord("F1"))).toBe("help");
    expect(matchShortcut(ctrl("k"))).toBe("catalog");
    expect(matchShortcut(chord("Escape"))).toBe("escape");
  });

  it("accepts ⌘ wherever Ctrl is accepted", () => {
    expect(matchShortcut(chord("s", { metaKey: true }))).toBe("save");
    expect(matchShortcut(chord("d", { metaKey: true }))).toBe("duplicate");
    expect(matchShortcut(chord("Enter", { metaKey: true }))).toBe("run");
  });
});

describe("the keyboard layout", () => {
  it("comments the line whether Shift is held or not", () => {
    expect(matchShortcut(ctrl("/"))).toBe("commentLine");
    expect(matchShortcut(ctrl("/", { shiftKey: true }))).toBe("commentLine");
  });

  it("`?` is never the line comment, and vice versa", () => {
    expect(matchShortcut(ctrl("?"))).toBe("commentBlock");
    expect(matchShortcut(ctrl("?", { shiftKey: true }))).toBe("commentBlock");
    expect(matchShortcut(ctrl("/"))).not.toBe("commentBlock");
  });

  it("treats AltGr as typing, not as Ctrl", () => {
    expect(matchShortcut(ctrl("/", { altKey: true }))).toBeNull();
    expect(matchShortcut(ctrl("?", { altKey: true }))).toBeNull();
    expect(matchShortcut(ctrl("d", { altKey: true }))).toBeNull();
  });

  it("a bare key is never a shortcut", () => {
    expect(matchShortcut(chord("/"))).toBeNull();
    expect(matchShortcut(chord("?"))).toBeNull();
    expect(matchShortcut(chord("d"))).toBeNull();
    expect(matchShortcut(chord("Enter"))).toBeNull();
  });
});

describe("Shift tells them apart, and Caps Lock tells nothing apart", () => {
  it("separates the catalogue from deleting a line", () => {
    expect(matchShortcut(ctrl("k"))).toBe("catalog");
    expect(matchShortcut(ctrl("k", { shiftKey: true }))).toBe("deleteLine");
  });

  it("separates Test from \"complete the statement\"", () => {
    expect(matchShortcut(ctrl("Enter"))).toBe("run");
    expect(matchShortcut(ctrl("Enter", { shiftKey: true }))).toBe("completeStatement");
  });

  it("separates duplicate from delete", () => {
    expect(matchShortcut(ctrl("d"))).toBe("duplicate");
    expect(matchShortcut(ctrl("d", { shiftKey: true }))).toBe("deleteLine");
  });

  it("opens the catalogue with Caps Lock on", () => {
    expect(matchShortcut(ctrl("K"))).toBe("catalog");
    expect(matchShortcut(ctrl("D"))).toBe("duplicate");
    expect(matchShortcut(ctrl("S"))).toBe("save");
  });
});

describe("what stays with the browser and the student", () => {
  it("touches nothing an editor owes the browser", () => {
    for (const key of ["z", "y", "c", "v", "x", "a", "f", "p", "r", "w", "t"]) {
      expect(matchShortcut(ctrl(key)), "Ctrl+" + key).toBeNull();
    }
    expect(matchShortcut(ctrl("z", { shiftKey: true }))).toBeNull();
    expect(matchShortcut(ctrl("y"))).toBeNull();
  });

  it("does not claim an arrow that lacks a modifier", () => {
    expect(matchShortcut(chord("ArrowUp"))).toBeNull();
    expect(matchShortcut(chord("ArrowUp", { shiftKey: true }))).toBeNull();
    expect(matchShortcut(chord("ArrowUp", { altKey: true }))).toBeNull();
    expect(matchShortcut(chord("ArrowUp", { ctrlKey: true, altKey: true, shiftKey: true }))).toBeNull();
    expect(matchShortcut(chord("ArrowDown", { ctrlKey: true, shiftKey: true }))).toBeNull();
  });

  it("does not claim Escape as soon as a modifier is held", () => {
    expect(matchShortcut(ctrl("Escape"))).toBeNull();
    expect(matchShortcut(chord("Escape", { shiftKey: true }))).toBeNull();
    expect(matchShortcut(chord("Escape", { altKey: true }))).toBeNull();
  });

  it("leaves Tab and ordinary keys to `keyEdit`", () => {
    for (const key of ["Tab", "Backspace", "a", "(", "{", '"', "'"]) {
      expect(matchShortcut(chord(key)), key).toBeNull();
    }
  });
});

describe("the two sets", () => {
  it("files every text transformation under the editor's commands", () => {
    for (const id of TEXT_COMMANDS) {
      expect(EDITOR_COMMANDS.has(id), id).toBe(true);
    }
    expect(EDITOR_COMMANDS.has("nextIssue")).toBe(true);
    expect(EDITOR_COMMANDS.has("gotoLine")).toBe(true);
    expect(TEXT_COMMANDS.has("nextIssue")).toBe(false);
    expect(TEXT_COMMANDS.has("gotoLine")).toBe(false);
  });

  it("keeps the page commands out of the editing surface", () => {
    for (const id of ["save", "run", "help", "catalog", "escape"] as ShortcutId[]) {
      expect(EDITOR_COMMANDS.has(id), id).toBe(false);
    }
  });
});
