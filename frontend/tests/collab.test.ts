// THE COLLABORATION'S TWO PIECES THAT ARE EASY TO GET SUBTLY WRONG: the diff that turns a
// textarea into CRDT operations, and the transform that decides where a caret lands after
// somebody else's change.
//
// A REAL `Y.Doc`, NO NETWORK. That split is why `collab/document.ts` exists apart from the
// room: the merge rule is testable by calling it.

import { describe, expect, it } from "vitest";
import * as Y from "yjs";
import { LOCAL, applyLocal, seed, snapshot, textOf } from "../src/lib/collab/document";
import { fromBase64, place, rowColumn, selectionBands, shift, toBase64 } from "../src/lib/collab/carets";

const FILES = ["main.c", "matrac_lib.c"];

function room(): Y.Doc {
  return new Y.Doc();
}

describe("applyLocal", () => {
  it("sends ONE contiguous change for a keystroke, not a whole rewrite", () => {
    // Replacing everything -- delete all, insert all -- would technically converge and
    // would destroy every teammate's caret on every keystroke.
    const doc = room();
    const text = textOf(doc, "main.c");
    text.insert(0, "int main(void){}");
    const deltas: unknown[] = [];
    text.observe((event) => deltas.push(event.delta));
    applyLocal(doc, text, "int main(void){ }");
    expect(deltas).toEqual([[{ retain: 15 }, { insert: " " }]]);
  });

  it("finds the common prefix and suffix of a paste in the middle", () => {
    const doc = room();
    const text = textOf(doc, "main.c");
    text.insert(0, "abcdef");
    applyLocal(doc, text, "abcXYZdef");
    expect(text.toString()).toBe("abcXYZdef");
  });

  it("expresses a replaced selection as one delete plus one insert", () => {
    const doc = room();
    const text = textOf(doc, "main.c");
    text.insert(0, "int x = 1;");
    const deltas: unknown[][] = [];
    text.observe((event) => deltas.push(event.delta as unknown[]));
    applyLocal(doc, text, "int y = 1;");
    expect(deltas[0]).toEqual([{ retain: 4 }, { delete: 1 }, { insert: "y" }]);
  });

  it("does nothing at all when the text did not change", () => {
    const doc = room();
    const text = textOf(doc, "main.c");
    text.insert(0, "pareil");
    expect(applyLocal(doc, text, "pareil")).toBe(false);
  });

  it("stamps LOCAL as the origin, which is what tells the observer not to move the caret", () => {
    const doc = room();
    const text = textOf(doc, "main.c");
    let origin: unknown = null;
    text.observe((event) => {
      origin = event.transaction.origin;
    });
    applyLocal(doc, text, "écrit à la main");
    expect(origin).toBe(LOCAL);
  });

  it("converges when two members edit the same line concurrently", () => {
    // This is the case a hand-rolled protocol gets wrong in week three.
    const a = room();
    const b = room();
    const textA = textOf(a, "main.c");
    const textB = textOf(b, "main.c");
    textA.insert(0, "int main(void){}");
    Y.applyUpdate(b, Y.encodeStateAsUpdate(a));
    applyLocal(a, textA, "int main(void){ return 0; }");
    applyLocal(b, textB, "int main(int argc, char **argv){}");
    Y.applyUpdate(b, Y.encodeStateAsUpdate(a, Y.encodeStateVector(b)));
    Y.applyUpdate(a, Y.encodeStateAsUpdate(b, Y.encodeStateVector(a)));
    expect(textA.toString()).toBe(textB.toString());
  });
});

describe("seed and snapshot", () => {
  it("seeds each declared file from the server's plain text", () => {
    const doc = room();
    seed(doc, FILES, { "main.c": "int main(void){}", "matrac_lib.c": "int f(void){}" });
    expect(snapshot(doc, FILES)).toEqual({
      "main.c": "int main(void){}",
      "matrac_lib.c": "int f(void){}",
    });
  });

  it("refuses to seed a document that already has content -- the belt on top of `peers`", () => {
    // Two clients seeding the same text into a CRDT would merge it TWICE, leaving the file
    // written twice. That is the one failure this design has to make impossible.
    const doc = room();
    seed(doc, FILES, { "main.c": "déjà là" });
    seed(doc, FILES, { "main.c": "encore" });
    expect(snapshot(doc, FILES)["main.c"]).toBe("déjà là");
  });

  it("gives an absent file an empty string rather than dropping it", () => {
    const doc = room();
    seed(doc, FILES, {});
    expect(snapshot(doc, FILES)).toEqual({ "main.c": "", "matrac_lib.c": "" });
  });
});

describe("shift -- where the caret lands after somebody else's change", () => {
  it("moves the caret along when text is inserted BEFORE it", () => {
    expect(shift([{ retain: 3 }, { insert: "abc" }], 10)).toBe(13);
  });

  it("leaves it alone when the insertion is AFTER it", () => {
    expect(shift([{ retain: 20 }, { insert: "abc" }], 10)).toBe(10);
  });

  it("pulls it back when text before it is deleted", () => {
    expect(shift([{ retain: 3 }, { delete: 4 }], 10)).toBe(6);
  });

  it("clamps to the start of a deletion that swallowed the caret", () => {
    expect(shift([{ retain: 3 }, { delete: 20 }], 10)).toBe(3);
    expect(shift([{ delete: 100 }], 10)).toBe(0);
  });

  it("never goes negative", () => {
    expect(shift([{ delete: 999 }], 2)).toBe(0);
  });

  it("does nothing on an empty delta", () => {
    expect(shift([], 7)).toBe(7);
  });
});

describe("rowColumn", () => {
  it("turns an offset into a row and a column", () => {
    const text = "int main(void)\n{\n    return 0;\n}";
    expect(rowColumn(text, 0)).toEqual({ row: 0, column: 0 });
    expect(rowColumn(text, 15)).toEqual({ row: 1, column: 0 });
    expect(rowColumn(text, 21)).toEqual({ row: 2, column: 4 });
  });

  it("clamps a negative offset instead of throwing", () => {
    expect(rowColumn("abc", -5)).toEqual({ row: 0, column: 0 });
  });
});

describe("place and selectionBands", () => {
  const box = { char: 8, line: 18, top: 6, left: 10 };

  it("offsets by the scroll, so a caret follows the text rather than the viewport", () => {
    expect(place(box, { left: 0, top: 0 }, 3, 2)).toBe("left:34px;top:42px;");
    expect(place(box, { left: 16, top: 18 }, 3, 2)).toBe("left:18px;top:24px;");
  });

  it("draws nothing when there is no selection", () => {
    expect(selectionBands("abc", 1, 1, box, { left: 0, top: 0 })).toEqual([]);
  });

  it("draws one band per line of a multi-line selection", () => {
    const bands = selectionBands("abcd\nefgh\nijkl", 2, 12, box, { left: 0, top: 0 });
    expect(bands).toHaveLength(3);
    expect(bands[0]).toContain("width:16px"); // "cd" on the first line
  });

  it("skips a line the selection only touches at column zero", () => {
    const bands = selectionBands("abcd\nefgh", 4, 5, box, { left: 0, top: 0 });
    expect(bands).toHaveLength(0);
  });
});

describe("the wire encoding", () => {
  it("round-trips the bytes Yjs produces", () => {
    const doc = room();
    textOf(doc, "main.c").insert(0, "un accent: é, et un octet nul dans la foulée");
    const update = Y.encodeStateAsUpdate(doc);
    expect(fromBase64(toBase64(update))).toEqual(update);
  });

  it("survives every byte value, which a naive text encoding would not", () => {
    const bytes = new Uint8Array(256);
    for (let i = 0; i < 256; i++) bytes[i] = i;
    expect(fromBase64(toBase64(bytes))).toEqual(bytes);
  });
});
