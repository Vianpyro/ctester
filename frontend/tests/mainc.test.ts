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
      { key: "<stdio.h>", line: "#include <stdio.h>  // pour printf" },
    ]);
    expect(piece.body).toBe("int main(void){}");
  });

  it("does NOT hoist an include already inside a student `#if`", () => {
    const piece = disassemble("#ifdef X\n#include <math.h>\n#endif\nint main(void){}");
    expect(piece.includes).toEqual([]);
    expect(piece.body).toContain("#include <math.h>");
  });

  it("leaves `#define` where it is -- the `#if` is what keeps two labs from clashing", () => {
    const piece = disassemble("#define DIMANCHE 0\nint main(void){}");
    expect(piece.body).toContain("#define DIMANCHE 0");
  });

  it("removes only `_CRT_SECURE_NO_WARNINGS`, which the file already sets at the top", () => {
    const piece = disassemble("#define _CRT_SECURE_NO_WARNINGS\nint main(void){}");
    expect(piece.body).not.toContain("_CRT_SECURE_NO_WARNINGS");
  });
});

describe("trim", () => {
  it("folds the hole the hoisted includes left behind", () => {
    expect(trim("\n\n\n\nint main(void){}\n\n\n\nreturn 0;\n\n")).toBe(
      "int main(void){}\n\nreturn 0;",
    );
  });
});

describe("numberOf", () => {
  it("takes the number from the ID, never from the rank", () => {
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
  const AT = new Date(2026, 8, 9, 21, 30);

  it("opens on the first exercise that HAS code, not simply the first", () => {
    const built = build(
      [exercise("tp2-ex0", "ex.0"), exercise("tp2-ex1", "ex.1")],
      { "tp2-ex1": { "submission.c": "int main(void){return 0;}" } },
      "Vianney",
      "TP 2",
      AT,
    );
    expect(built.text).toContain("#define exercice 1");
    expect(built.empty).toEqual([0]);
    expect(built.total).toBe(2);
  });

  it("treats exercise 0 as a real exercise, not as `nothing found yet`", () => {
    const built = build(
      [exercise("tp2-ex0", "ex.0"), exercise("tp2-ex1", "ex.1")],
      { "tp2-ex0": { "submission.c": "int main(void){return 0;}" } },
      "",
      "TP 2",
      AT,
    );
    expect(built.text).toContain("#define exercice 0");
  });

  it("keeps an exercise with no draft, with a comment saying so", () => {
    const built = build([exercise("tp2-ex3", "ex.3")], {}, "", "TP 2", AT);
    expect(built.text).toContain("#if exercice == 3");
    expect(built.text).toContain("Aucun code enregistré");
    expect(built.empty).toEqual([3]);
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
    const includes = built.text.match(/#include <stdio\.h>/g) ?? [];
    expect(includes).toHaveLength(1);
    expect(built.text).toContain("#include <stdio.h>  // pour printf");
  });

  it("dates the file in the READER's zone, not in UTC", () => {
    expect(today(AT)).toBe("2026-09-09");
    const built = build([exercise("tp2-ex1", "ex.1")], {}, "", "TP 2", AT);
    expect(built.text).toContain("Date : 2026-09-09");
  });

  it("pre-fills the author without imposing it, and stays empty when unknown", () => {
    expect(build([exercise("tp2-ex1", "ex.1")], {}, "Vianney", "TP 2", AT).text).toContain(
      "Auteur : Vianney",
    );
    expect(build([exercise("tp2-ex1", "ex.1")], {}, "", "TP 2", AT).text).toContain("Auteur : ");
  });

  it("sets the preprocessor preamble the course expects", () => {
    const built = build([exercise("tp2-ex1", "ex.1")], {}, "", "TP 2", AT);
    expect(built.text).toContain("#define _CRT_SECURE_NO_WARNINGS");
    expect(built.text).toContain("Description : Exercice 1 — TP 2 — TCH009");
  });
});
