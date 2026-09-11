// THE CHECKER'S TESTS, AND HALF OF THEM GUARD A SILENCE. A rule that fires on
// correct code is worse than no rule: the student learns to ignore the panel,
// and the message that mattered goes with it. So every heuristic here has a
// twin -- the case it must catch, and the correct code it must not touch.
//
// It is called, not driven through a DOM: `check()` is pure, which is the whole
// reason it lives in `domain/`.

import { describe, expect, it } from "vitest";
import { check, nextIssue, type Issue } from "../src/lib/domain/syntax";

/** The messages, so a test reads like the panel does. */
const said = (src: string): string[] => check(src).map((i) => i.message);
const levels = (src: string): string[] => check(src).map((i) => i.level);

describe("nothing to say", () => {
  it("stays quiet on a correct program", () => {
    expect(
      check(
        '#include <stdio.h>\n\nint main(void) {\n    int x = 3;\n    printf("%d\\n", x);\n    return 0;\n}\n',
      ),
    ).toEqual([]);
  });

  it("stays quiet on empty text", () => {
    expect(check("")).toEqual([]);
  });
});

describe("what is blanked, and what it protects", () => {
  it("does not read the // of an URL as a comment", () => {
    // If it did, the `;` would be swallowed and a semicolon reported.
    expect(check('int main(void) {\n    puts("http://exemple.com");\n    return 0;\n}\n')).toEqual(
      [],
    );
  });

  it("ignores braces and semicolons inside a comment", () => {
    expect(check("int main(void) {\n    // { ; ) unbalanced on purpose\n    return 0;\n}\n")).toEqual(
      [],
    );
  });

  it("ignores braces and semicolons inside a string", () => {
    expect(check('int main(void) {\n    puts("{ ; )");\n    return 0;\n}\n')).toEqual([]);
  });

  it("does not take a French apostrophe in a comment for a character literal", () => {
    // The trap `keys.ts` already pays for: "aujourd'hui" in a course comment.
    expect(check("int main(void) {\n    // rien aujourd'hui\n    return 0;\n}\n")).toEqual([]);
  });

  it("does not take an apostrophe inside a string for a character literal", () => {
    expect(check('int main(void) {\n    puts("aujourd\'hui");\n    return 0;\n}\n')).toEqual([]);
  });
});

describe("the certain faults", () => {
  it("reports an unclosed brace AT THE OPENING BRACE", () => {
    const src = "int main(void) {\n    return 0;\n";
    const issues = check(src);
    expect(issues).toHaveLength(1);
    expect(issues[0]!.level).toBe("error");
    expect(issues[0]!.from).toBe(src.indexOf("{"));
    expect(issues[0]!.message).toContain("jamais fermée");
  });

  it("reports a closer that closes nothing", () => {
    const src = "int main(void) {\n    return 0;\n}\n}\n";
    const issues = check(src);
    expect(issues).toHaveLength(1);
    expect(issues[0]!.message).toContain("ne ferme aucune");
  });

  it("reports crossed delimiters", () => {
    expect(said("int t[] = (1];\n").join(" ")).toContain("se croisent");
  });

  it("reports an unterminated string", () => {
    const src = 'int main(void) {\n    puts("salut);\n    return 0;\n}\n';
    const issues = check(src);
    expect(issues[0]!.from).toBe(src.indexOf('"'));
    expect(issues[0]!.message).toContain("guillemet");
  });

  it("reports an unterminated character literal", () => {
    expect(said("char c = 'a;\n").join(" ")).toContain("apostrophe");
  });

  it("reports an unclosed block comment", () => {
    const src = "int main(void) {\n    /* et la suite disparait\n    return 0;\n}\n";
    const issues = check(src);
    expect(issues[0]!.from).toBe(src.indexOf("/*"));
    expect(issues[0]!.message).toContain("commentaire");
  });

  it("keeps an escaped quote inside a string", () => {
    expect(check('int main(void) {\n    puts("il a dit \\"oui\\"");\n    return 0;\n}\n')).toEqual(
      [],
    );
  });
});

describe("= instead of ==", () => {
  it("flags a bare assignment in a condition", () => {
    const issues = check("int main(void) {\n    if (x = 3) return 1;\n    return 0;\n}\n");
    expect(issues).toHaveLength(1);
    expect(issues[0]!.level).toBe("hint");
    expect(issues[0]!.message).toContain("==");
  });

  it("LEAVES THE getchar IDIOM ALONE -- the depth is the guard", () => {
    expect(
      check("int main(void) {\n    while ((c = getchar()) != EOF) putchar(c);\n    return 0;\n}\n"),
    ).toEqual([]);
  });

  it("says nothing about ==, !=, <= or +=", () => {
    expect(check("int main(void) {\n    if (a == b && c != d && e <= f) return 1;\n    return 0;\n}\n")).toEqual(
      [],
    );
  });
});

describe("the if with an empty body", () => {
  it("flags the semicolon that ends the if", () => {
    const issues = check("int main(void) {\n    if (x > 0);\n    return 0;\n}\n");
    expect(issues).toHaveLength(1);
    expect(issues[0]!.message).toContain("termine le if");
  });

  it("says nothing about an empty for or while", () => {
    expect(check("int main(void) {\n    while (attendre());\n    return 0;\n}\n")).toEqual([]);
  });
});

describe("scanf without &", () => {
  it("flags a bare identifier read as a number", () => {
    const issues = check('int main(void) {\n    scanf("%d", x);\n    return 0;\n}\n');
    expect(issues).toHaveLength(1);
    expect(issues[0]!.message).toContain("« x »");
  });

  it("LEAVES %s ALONE -- a char array needs no &", () => {
    expect(check('int main(void) {\n    scanf("%s", nom);\n    return 0;\n}\n')).toEqual([]);
  });

  it("says nothing when the & is there", () => {
    expect(check('int main(void) {\n    scanf("%d %lf", &n, &x);\n    return 0;\n}\n')).toEqual([]);
  });

  it("says nothing about an expression it cannot judge", () => {
    expect(check('int main(void) {\n    scanf("%d", &tab[i]);\n    return 0;\n}\n')).toEqual([]);
  });

  it("does not count %% as a conversion", () => {
    expect(check('int main(void) {\n    scanf("100%% %d", &n);\n    return 0;\n}\n')).toEqual([]);
  });

  it("flags the second argument when only it is bare", () => {
    expect(said('int main(void) {\n    scanf("%d %d", &a, b);\n    return 0;\n}\n')[0]).toContain(
      "« b »",
    );
  });
});

describe("the missing semicolon", () => {
  it("flags a statement that ends on nothing", () => {
    const issues = check("int main(void) {\n    int x = 2\n    return 0;\n}\n");
    expect(issues).toHaveLength(1);
    expect(issues[0]!.message).toContain("; ");
  });

  it("says nothing about a call split over two lines", () => {
    expect(
      check('int main(void) {\n    printf("%d %d\\n",\n           a, b);\n    return 0;\n}\n'),
    ).toEqual([]);
  });

  it("says nothing about a condition split over two lines", () => {
    expect(check("int main(void) {\n    if (a &&\n        b) return 1;\n    return 0;\n}\n")).toEqual(
      [],
    );
  });

  it("says nothing about a preprocessor directive", () => {
    expect(check("#include <stdio.h>\n#define N 10\n\nint main(void) {\n    return 0;\n}\n")).toEqual(
      [],
    );
  });

  it("says nothing about a function header followed by its brace", () => {
    expect(check("int somme(int a, int b)\n{\n    return a + b;\n}\n")).toEqual([]);
  });

  it("says nothing about else, case, or a closing brace", () => {
    expect(
      check(
        "int main(void) {\n    switch (x) {\n    case 1:\n        break;\n    default:\n        break;\n    }\n    if (x)\n        return 1;\n    else\n        return 0;\n}\n",
      ),
    ).toEqual([]);
  });

  it("says nothing about a continuation line starting with an operator", () => {
    expect(check("int main(void) {\n    int t = a\n          + b;\n    return 0;\n}\n")).toEqual([]);
  });
});

describe("the noise rules", () => {
  it("A CERTAIN FAULT SILENCES EVERY HEURISTIC", () => {
    // Without this, an unclosed brace fills the panel with invented semicolons.
    const src = "int main(void) {\n    if (x = 3) return 1;\n    int y = 2\n    return 0;\n";
    expect(levels(src)).toEqual(["error"]);
  });

  it("A LOST QUOTE IS ONE MESSAGE, NOT THREE", () => {
    // `puts("salut);` swallows its own `)`, which then makes the enclosing `{`
    // look unclosed. One typo must not read as three faults.
    const issues = check('int main(void) {\n    puts("salut);\n    return 0;\n}\n');
    expect(issues).toHaveLength(1);
    expect(issues[0]!.message).toContain("guillemet");
  });

  it("never returns more than six", () => {
    const src = "int main(void) {\n" + "    int a = 1\n".repeat(20) + "    return 0;\n}\n";
    expect(check(src)).toHaveLength(6);
  });

  it("returns them in reading order", () => {
    const issues = check("int main(void) {\n    int a = 1\n    int b = 2\n    return 0;\n}\n");
    expect(issues).toHaveLength(2);
    expect(issues[0]!.from).toBeLessThan(issues[1]!.from);
  });
});

describe("la faute suivante (F2)", () => {
  const at = (from: number): Issue => ({ from, to: from + 1, message: "m", level: "error" });

  it("saute à la première faute qui suit le curseur", () => {
    expect(nextIssue([at(10), at(30), at(20)], 12)?.from).toBe(20);
  });

  it("REVIENT à la première une fois la dernière passée", () => {
    // Sans le bouclage, F2 devient inerte dès qu'on a atteint le bas du
    // fichier -- et une touche inerte se lit comme une touche cassée.
    expect(nextIssue([at(10), at(30)], 99)?.from).toBe(10);
  });

  it("part de la première quand le curseur est avant tout", () => {
    expect(nextIssue([at(10), at(30)], 0)?.from).toBe(10);
  });

  it("SILENCE quand il n'y a aucune faute", () => {
    expect(nextIssue([], 0)).toBeNull();
  });

  it("SILENCE sur la faute où le curseur est DÉJÀ posé : il faut avancer", () => {
    // Sinon F2 répété reste collé à la même faute, ce qui ressemble aussi à
    // une touche cassée.
    expect(nextIssue([at(10), at(30)], 10)?.from).toBe(30);
  });
});
