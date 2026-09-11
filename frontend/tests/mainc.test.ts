// THE ONE-PIECE `main.c`. Four details here were each paid for once, and every one of
// them is a way a hand-in silently comes out wrong.
//
// The produced TEXT is what matters, so it is checked directly -- no click, no blob, no
// DOM. That is why `build()` and the download were split in the first place.

import { describe, expect, it } from "vitest";
import {
  build,
  codeOf,
  disassemble,
  labelForNumbers,
  numberOf,
  today,
  trim,
} from "../src/lib/domain/mainc";
import type { Exercise } from "../src/lib/domain/catalog";

const exercise = (id: string, short: string, files = ["submission.c"]): Exercise => ({
  id,
  mode: "io",
  short,
  group: "TP 2",
  label: "TP2 : " + short,
  verification: false,
  bonus: false,
  assignment: "",
  files: files.map((name) => ({ name })),
  learning: {},
  access: "available",
  available_from: "",
});

describe("disassemble", () => {
  it("hoists a top-level include and keeps the student's own comment on it", () => {
    const piece = disassemble('#include <stdio.h>  // pour printf\nint main(void){}');
    expect(piece.includes).toEqual([
      { cle: "<stdio.h>", ligne: "#include <stdio.h>  // pour printf" },
    ]);
    expect(piece.corps).toBe("int main(void){}");
  });

  it("does NOT hoist an include already inside a student `#if`", () => {
    // It is there FOR that condition: hoisting it would make it unconditional and change
    // the meaning of their code.
    const piece = disassemble("#ifdef X\n#include <math.h>\n#endif\nint main(void){}");
    expect(piece.includes).toEqual([]);
    expect(piece.corps).toContain("#include <math.h>");
  });

  it("leaves `#define` where it is -- the `#if` is what keeps two labs from clashing", () => {
    const piece = disassemble("#define DIMANCHE 0\nint main(void){}");
    expect(piece.corps).toContain("#define DIMANCHE 0");
  });

  it("removes only `_CRT_SECURE_NO_WARNINGS`, which the file already sets at the top", () => {
    const piece = disassemble("#define _CRT_SECURE_NO_WARNINGS\nint main(void){}");
    expect(piece.corps).not.toContain("_CRT_SECURE_NO_WARNINGS");
  });
});

describe("trim", () => {
  it("folds the hole the hoisted includes left behind", () => {
    // Removing three lines from a header block leaves three blanks in their place, and the
    // handed-in file opens on an accordion of them.
    expect(trim("\n\n\n\nint main(void){}\n\n\n\nreturn 0;\n\n")).toBe(
      "int main(void){}\n\nreturn 0;",
    );
  });
});

describe("numberOf", () => {
  it("takes the number from the ID, never from the rank", () => {
    // `tp2-ex0` is the statement's exercise 0: numbering it 1 shifts the whole file by one
    // compared to what the instructor reads.
    expect(numberOf(exercise("tp2-ex0", "ex.0"), 1)).toBe(0);
    expect(numberOf(exercise("tp2-ex7", "ex.7"), 1)).toBe(7);
  });

  it("falls back to the rank for an id that does not end in -exN", () => {
    expect(numberOf(exercise("preambule", "préambule"), 3)).toBe(3);
  });
});

describe("labelForNumbers", () => {
  it("says a range when contiguous and a list otherwise", () => {
    expect(labelForNumbers([0, 1, 2])).toBe("Exercices 0 à 2");
    expect(labelForNumbers([1, 3])).toBe("Exercices 1, 3");
    expect(labelForNumbers([2])).toBe("Exercice 2");
    expect(labelForNumbers([])).toBe("Aucun exercice");
  });
});

describe("codeOf", () => {
  it("glues a two-file exercise back with its names rather than dropping one", () => {
    const module_ = exercise("tp5-ex1", "ex.1", ["calendrier.h", "calendrier.c"]);
    const out = codeOf(module_, { "calendrier.h": "int f(void);", "calendrier.c": "int f(void){}" });
    expect(out).toContain("/* calendrier.h */");
    expect(out).toContain("/* calendrier.c */");
  });

  it("skips a file that holds only whitespace", () => {
    expect(codeOf(exercise("tp2-ex1", "ex.1"), { "submission.c": "   \n" })).toBe("");
  });
});

describe("build", () => {
  const AT = new Date(2026, 8, 9, 21, 30); // an evening in Montreal

  it("opens on the first exercise that HAS code, not simply the first", () => {
    // A file that opens on an empty block does not compile, and the student concludes the
    // export is broken.
    const built = build(
      [exercise("tp2-ex0", "ex.0"), exercise("tp2-ex1", "ex.1")],
      { "tp2-ex1": { "submission.c": "int main(void){return 0;}" } },
      "Vianney",
      "TP 2",
      AT,
    );
    expect(built.texte).toContain("#define exercice 1");
    expect(built.vides).toEqual([0]);
    expect(built.total).toBe(2);
  });

  it("treats exercise 0 as a real exercise, not as `nothing found yet`", () => {
    // With a counter starting at zero, `if (!first)` took the preamble for "nothing found".
    const built = build(
      [exercise("tp2-ex0", "ex.0"), exercise("tp2-ex1", "ex.1")],
      { "tp2-ex0": { "submission.c": "int main(void){return 0;}" } },
      "",
      "TP 2",
      AT,
    );
    expect(built.texte).toContain("#define exercice 0");
  });

  it("keeps an exercise with no draft, with a comment saying so", () => {
    // Removing it would shift the whole numbering away from the statement.
    const built = build([exercise("tp2-ex3", "ex.3")], {}, "", "TP 2", AT);
    expect(built.texte).toContain("#if exercice == 3");
    expect(built.texte).toContain("Aucun code enregistré");
    expect(built.vides).toEqual([3]);
  });

  it("deduplicates on the HEADER, not on the line", () => {
    const built = build(
      [exercise("tp2-ex0", "ex.0"), exercise("tp2-ex1", "ex.1")],
      {
        "tp2-ex0": { "submission.c": "#include <stdio.h>  // pour printf\nint main(void){}" },
        "tp2-ex1": { "submission.c": "#include <stdio.h>\nint main(void){}" },
      },
      "",
      "TP 2",
      AT,
    );
    const includes = built.texte.match(/#include <stdio\.h>/g) ?? [];
    expect(includes).toHaveLength(1);
    // The line kept is the student's own, comment included.
    expect(built.texte).toContain("#include <stdio.h>  // pour printf");
  });

  it("dates the file in the READER's zone, not in UTC", () => {
    // `toISOString()` on a Montreal evening dates the file to the next day, and a hand-in
    // dated one day ahead is exactly the kind of detail that comes up out loud.
    expect(today(AT)).toBe("2026-09-09");
    const built = build([exercise("tp2-ex1", "ex.1")], {}, "", "TP 2", AT);
    expect(built.texte).toContain("Date : 2026-09-09");
  });

  it("pre-fills the author without imposing it, and stays empty when unknown", () => {
    expect(build([exercise("tp2-ex1", "ex.1")], {}, "Vianney", "TP 2", AT).texte).toContain(
      "Auteur : Vianney",
    );
    expect(build([exercise("tp2-ex1", "ex.1")], {}, "", "TP 2", AT).texte).toContain("Auteur : ");
  });

  it("sets the preprocessor preamble the course expects", () => {
    const built = build([exercise("tp2-ex1", "ex.1")], {}, "", "TP 2", AT);
    expect(built.texte).toContain("#define _CRT_SECURE_NO_WARNINGS");
    expect(built.texte).toContain("Description : Exercice 1 — TP 2 — TCH009");
  });
});
