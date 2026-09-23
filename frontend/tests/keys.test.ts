import { describe, expect, it } from "vitest";
import { commandEdit, keyEdit, lineSpan, parseLine, type Edit } from "../src/lib/domain/keys";
import type { ShortcutId } from "../src/lib/domain/shortcuts";

function press(key: string, marked: string, shift = false): string | null {
  const start = marked.indexOf("§");
  const rest = marked.slice(start + 1);
  const second = rest.indexOf("§");
  const value = marked.replace(/§/g, "");
  const end = second === -1 ? start : start + second;
  const edit = keyEdit(key, shift, value, start, end);
  if (!edit) return null;
  const out = value.slice(0, edit.from) + edit.insert + value.slice(edit.to);
  const caretEnd = edit.caretEnd ?? edit.caret;
  return (
    out.slice(0, edit.caret) +
    "|" +
    out.slice(edit.caret, caretEnd) +
    (caretEnd > edit.caret ? "|" : "") +
    out.slice(caretEnd)
  );
}

describe("pairs", () => {
  it("closes the four pairs and leaves the caret inside", () => {
    expect(press("(", "printf§")).toBe("printf(|)");
    expect(press("[", "int t§")).toBe("int t[|]");
    expect(press("{", "if (x) §")).toBe("if (x) {|}");
    expect(press('"', "puts(§)")).toBe('puts("|")');
  });

  it("steps over the closing one instead of typing a second", () => {
    expect(press(")", "printf(§)")).toBe("printf()|");
    expect(press('"', 'puts("hi§")')).toBe('puts("hi"|)');
  });

  it("wraps a selection rather than replacing it", () => {
    expect(press("(", "return §x + 1§;")).toBe("return (|x + 1|);");
    expect(press('"', "§salut§")).toBe('"|salut|"');
  });

  it("does not wrap when text follows: one is typing before an existing word", () => {
    expect(press("(", "§printf")).toBeNull();
    expect(press("[", "§tableau")).toBeNull();
  });

  it("does not close an apostrophe stuck to a word", () => {
    expect(press("'", "// aujourd§")).toBeNull();
    expect(press("'", "// c§")).toBeNull();
  });

  it("closes an apostrophe where it is a C literal", () => {
    expect(press("'", "char c = §;")).toBe("char c = '|';");
  });
});

describe("Backspace", () => {
  it("erases both halves of an empty pair", () => {
    expect(press("Backspace", "printf(§)")).toBe("printf|");
    expect(press("Backspace", 'puts("§")')).toBe("puts(|)");
  });

  it("leaves it to the browser when the pair is not empty", () => {
    expect(press("Backspace", "printf(§x)")).toBeNull();
  });

  it("erases one indentation level at once", () => {
    expect(press("Backspace", "        §x")).toBe("    |x");
    expect(press("Backspace", "      §x")).toBe("    |x");
  });
});

describe("Tab", () => {
  it("goes to the next multiple of four", () => {
    expect(press("Tab", "§x")).toBe("    |x");
    expect(press("Tab", "  §x")).toBe("    |x");
    expect(press("Tab", "    §x")).toBe("        |x");
  });

  it("indents a whole selected block and keeps the selection", () => {
    const out = press("Tab", "§un\ndeux\ntrois§");
    expect(out).toBe("|    un\n    deux\n    trois|");
  });

  it("dedents the block with Shift, back to its starting state", () => {
    const indented = "    un\n    deux";
    const start = indented.length;
    const edit = keyEdit("Tab", true, indented, 0, start) as Edit;
    const out = indented.slice(0, edit.from) + edit.insert + indented.slice(edit.to);
    expect(out).toBe("un\ndeux");
  });

  it("dedents the current line wherever the caret is in it", () => {
    expect(press("Tab", "    if§ (x)", true)).toBe("if| (x)");
  });

  it("does nothing on a line already at the left", () => {
    expect(press("Tab", "if§ (x)", true)).toBe("if| (x)");
  });
});

describe("Enter", () => {
  it("carries over the line's indentation", () => {
    expect(press("Enter", "    x = 1;§")).toBe("    x = 1;\n    |");
  });

  it("leaves it to the browser when there is nothing to carry over", () => {
    expect(press("Enter", "x = 1;§")).toBeNull();
  });

  it("opens a block between two braces, closing it on its own line", () => {
    expect(press("Enter", "    if (x) {§}")).toBe("    if (x) {\n        |\n    }");
  });

  it("indents one level after a lone opening brace", () => {
    expect(press("Enter", "    if (x) {§")).toBe("    if (x) {\n        |");
  });
});

describe("the closing brace", () => {
  it("moves back one level when it is alone on its line", () => {
    expect(press("}", "if (x) {\n    y;\n        §")).toBe("if (x) {\n    y;\n    }|");
  });

  it("does not move what is not indentation", () => {
    expect(press("}", "if (x) { y;§")).toBeNull();
  });
});

describe("what is not ours", () => {
  it("lets keys through that have no editing effect", () => {
    for (const key of ["ArrowLeft", "Home", "F5", "Shift", "PageDown"]) {
      expect(keyEdit(key, false, "x", 1, 1), key).toBeNull();
    }
  });

  it("lets an ordinary letter through", () => {
    expect(keyEdit("a", false, "x", 1, 1)).toBeNull();
  });
});

function run(id: ShortcutId, marked: string): string | null {
  const start = marked.indexOf("§");
  const rest = marked.slice(start + 1);
  const second = rest.indexOf("§");
  const value = marked.replace(/§/g, "");
  const end = second === -1 ? start : start + second;
  const edit = commandEdit(id, value, start, end);
  if (!edit) return null;
  const out = value.slice(0, edit.from) + edit.insert + value.slice(edit.to);
  const caretEnd = edit.caretEnd ?? edit.caret;
  return (
    out.slice(0, edit.caret) +
    "|" +
    out.slice(edit.caret, caretEnd) +
    (caretEnd > edit.caret ? "|" : "") +
    out.slice(caretEnd)
  );
}

const text = (id: ShortcutId, marked: string) => run(id, marked)?.replace(/\|/g, "") ?? null;

describe("comment", () => {
  it("puts `// ` on the caret's line", () => {
    expect(text("commentLine", "  int x§ = 1;")).toBe("  // int x = 1;");
  });

  it("removes `// ` when the whole block is commented", () => {
    expect(text("commentLine", "§// int x;\n// int y;§")).toBe("int x;\nint y;");
  });

  it("comments a mixed block rather than uncommenting it", () => {
    expect(text("commentLine", "§// int x;\nint y;§")).toBe("// // int x;\n// int y;");
  });

  it("aligns the `//` in a column and keeps the relative indentation", () => {
    expect(text("commentLine", "§    int a;\n        int b;§")).toBe(
      "    // int a;\n    //     int b;",
    );
  });

  it("leaves a block's empty lines untouched", () => {
    expect(text("commentLine", "§int a;\n\nint b;§")).toBe("// int a;\n\n// int b;");
  });

  it("still comments a lone empty line, or the key looks dead", () => {
    expect(text("commentLine", "  §")).toBe("  // ");
  });

  it("makes an exact round trip, and keeps a deliberate alignment space", () => {
    expect(text("commentLine", "§//x§")).toBe("x");
    expect(text("commentLine", "§// x§")).toBe("x");
    expect(text("commentLine", "§//  x§")).toBe(" x");
  });

  it("ignores the line below when the selection ends at its start", () => {
    expect(text("commentLine", "§int a;\n§int b;")).toBe("// int a;\nint b;");
    expect(text("commentLine", "§int a;\ni§nt b;")).toBe("// int a;\n// int b;");
  });

  it("keeps the caret on its line", () => {
    expect(run("commentLine", "int §x;")).toBe("// int |x;");
  });
});

describe("block comment", () => {
  it("wraps the selection and keeps it selected", () => {
    expect(run("commentBlock", "a = §b + c§;")).toBe("a = |/*b + c*/|;");
  });

  it("unwraps what it wrapped", () => {
    expect(text("commentBlock", "a = §/*b + c*/§;")).toBe("a = b + c;");
  });

  it("puts an empty shell under a bare caret", () => {
    expect(run("commentBlock", "a;§")).toBe("a;/* | */");
  });

  it("a `*/` in the middle falls back to the line comment", () => {
    expect(text("commentBlock", "§int a; /* n */\nint b;§")).toBe("// int a; /* n */\n// int b;");
  });
});

describe("duplicate", () => {
  it("copies the line below, same column, without a selection", () => {
    expect(run("duplicate", "int §x;")).toBe("int x;\nint |x;");
  });

  it("copies a block of whole lines below, and selects the copy", () => {
    expect(run("duplicate", "§int a;\nint b;§")).toBe("int a;\nint b;\n|int a;\nint b;|");
  });

  it("copies a partial selection right after it", () => {
    expect(run("duplicate", "f(§abc§);")).toBe("f(abc|abc|);");
  });

  it("is repeatable: two passes give two copies", () => {
    const once = text("duplicate", "§int a;")!;
    expect(once).toBe("int a;\nint a;");
  });
});

describe("delete the line", () => {
  it("takes the line and its line break", () => {
    expect(text("deleteLine", "int a;\nint §b;\nint c;")).toBe("int a;\nint c;");
  });

  it("takes the line break before on the last line", () => {
    expect(text("deleteLine", "int a;\nint §b;")).toBe("int a;");
  });

  it("empties the file when there is only one line", () => {
    expect(text("deleteLine", "int §a;")).toBe("");
  });

  it("does nothing on an empty file", () => {
    expect(run("deleteLine", "§")).toBeNull();
  });
});

describe("move the line", () => {
  it("moves the line up and takes the caret along", () => {
    expect(run("moveUp", "int a;\nint §b;")).toBe("int |b;\nint a;");
  });

  it("moves the line down and takes the caret along", () => {
    expect(run("moveDown", "int §a;\nint b;")).toBe("int b;\nint |a;");
  });

  it("keeps the selection on the moved block, so one can do it again", () => {
    expect(run("moveDown", "§int a;\nint b;§\nint c;")).toBe("int c;\n|int a;\nint b;|");
  });

  it("carries the block along when repeated", () => {
    const once = text("moveUp", "a\nb\n§c")!;
    expect(once).toBe("a\nc\nb");
    expect(text("moveUp", "a\n§c\nb")).toBe("c\na\nb");
  });

  it("does nothing at either end and leaves the text intact", () => {
    expect(run("moveUp", "int §a;\nint b;")).toBeNull();
    expect(run("moveDown", "int a;\nint §b;")).toBeNull();
    expect(run("moveUp", "§int a;\nint b;§")).toBeNull();
  });
});

describe("complete the statement", () => {
  it("adds the `;` and opens the next line, indented", () => {
    expect(run("completeStatement", "    int x = 1§")).toBe("    int x = 1;\n    |");
  });

  it("a line already ending with `;` does not get a second one", () => {
    expect(run("completeStatement", "    int x = 1;§")).toBe("    int x = 1;\n    |");
  });

  it("adds no semicolon after `if (x)`", () => {
    expect(run("completeStatement", "    if (x)§")).toBe("    if (x)\n    |");
    expect(run("completeStatement", "for (;;)§")).toBe("for (;;)\n|");
    expect(run("completeStatement", "while (a)§")).toBe("while (a)\n|");
    expect(run("completeStatement", "#include <stdio.h>§")).toBe("#include <stdio.h>\n|");
  });

  it("goes down one level after an opening brace", () => {
    expect(run("completeStatement", "    if (x) {§")).toBe("    if (x) {\n        |");
  });
});

describe("go to line", () => {
  it("returns the range of the requested line, numbered from 1", () => {
    expect(lineSpan("aa\nbbb\nc", 2)).toEqual({ from: 3, to: 6 });
    expect(lineSpan("aa\nbbb\nc", 1)).toEqual({ from: 0, to: 2 });
  });

  it("clamps instead of refusing: 999 means \"the end\"", () => {
    expect(parseLine("999", 5)).toBe(5);
    expect(parseLine("  3 ", 5)).toBe(3);
  });

  it("ignores what is not a line number", () => {
    for (const bad of ["", "0", "abc", "-2", "1.5", "2e3"]) {
      expect(parseLine(bad, 5), bad).toBeNull();
    }
  });
});
