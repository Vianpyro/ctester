import { describe, expect, it } from "vitest";
import { check, nextIssue, type Issue } from "../src/lib/domain/syntax";

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
    expect(check('#include <stdio.h>\nint main(void) {\n    puts("http://exemple.com");\n    return 0;\n}\n')).toEqual(
      [],
    );
  });

  it("ignores braces and semicolons inside a comment", () => {
    expect(check("int main(void) {\n    // { ; ) unbalanced on purpose\n    return 0;\n}\n")).toEqual(
      [],
    );
  });

  it("ignores braces and semicolons inside a string", () => {
    expect(check('#include <stdio.h>\nint main(void) {\n    puts("{ ; )");\n    return 0;\n}\n')).toEqual([]);
  });

  it("does not take a French apostrophe in a comment for a character literal", () => {
    expect(check("int main(void) {\n    // rien aujourd'hui\n    return 0;\n}\n")).toEqual([]);
  });

  it("does not take an apostrophe inside a string for a character literal", () => {
    expect(check('#include <stdio.h>\nint main(void) {\n    puts("aujourd\'hui");\n    return 0;\n}\n')).toEqual([]);
  });
});

describe("the certain faults", () => {
  it("reports an unclosed brace at the opening brace", () => {
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
    expect(check('#include <stdio.h>\nint main(void) {\n    puts("il a dit \\"oui\\"");\n    return 0;\n}\n')).toEqual(
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

  it("leaves the getchar idiom alone", () => {
    expect(
      check("#include <stdio.h>\nint main(void) {\n    while ((c = getchar()) != EOF) putchar(c);\n    return 0;\n}\n"),
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
    const issues = check('#include <stdio.h>\nint main(void) {\n    scanf("%d", x);\n    return 0;\n}\n');
    expect(issues).toHaveLength(1);
    expect(issues[0]!.message).toContain("« x »");
  });

  it("leaves %s alone: a char array needs no &", () => {
    expect(check('#include <stdio.h>\nint main(void) {\n    scanf("%s", nom);\n    return 0;\n}\n')).toEqual([]);
  });

  it("says nothing when the & is there", () => {
    expect(check('#include <stdio.h>\nint main(void) {\n    scanf("%d %lf", &n, &x);\n    return 0;\n}\n')).toEqual([]);
  });

  it("says nothing about an expression it cannot judge", () => {
    expect(check('#include <stdio.h>\nint main(void) {\n    scanf("%d", &tab[i]);\n    return 0;\n}\n')).toEqual([]);
  });

  it("does not count %% as a conversion", () => {
    expect(check('#include <stdio.h>\nint main(void) {\n    scanf("100%% %d", &n);\n    return 0;\n}\n')).toEqual([]);
  });

  it("flags the second argument when only it is bare", () => {
    expect(said('#include <stdio.h>\nint main(void) {\n    scanf("%d %d", &a, b);\n    return 0;\n}\n')[0]).toContain(
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
      check('#include <stdio.h>\nint main(void) {\n    printf("%d %d\\n",\n           a, b);\n    return 0;\n}\n'),
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

  it("flags i++ at the end of a line: it ends a statement, it does not continue one", () => {
    expect(said("int main(void) {\n    int i = 0;\n    i++\n    return i;\n}\n")).toHaveLength(1);
  });

  it("flags the last statement of a block, right before its brace", () => {
    const issues = check("int main(void) {\n    return 0\n}\n");
    expect(issues).toHaveLength(1);
    expect(issues[0]!.from).toBe("int main(void) {\n    return ".length);
  });

  it("says nothing about the last item of an initializer or an enum", () => {
    expect(check("int t[3] = {\n    1, 2,\n    3\n};\nenum Couleur {\n    ROUGE,\n    VERT\n};\n")).toEqual(
      [],
    );
  });

  it("flags every line of a program that forgot them all", () => {
    const src =
      '#include <stdio.h>\n\nint main(void) {\n    int n\n    int i = 1\n    int fact = 1\n\n' +
      '    (void)scanf("%d", &n)\n\n    while (i <= n) {\n        fact *= i\n        i++\n    }\n\n' +
      '    printf("Factorielle : %d", fact)\n\n    return 0\n}\n';
    const rows = check(src).map((i) => src.slice(0, i.from).split("\n").length);
    expect(rows).toEqual([4, 5, 6, 8, 11, 12, 15, 17]);
  });

  it("says nothing about a continuation line starting with an operator", () => {
    expect(check("int main(void) {\n    int t = a\n          + b;\n    return 0;\n}\n")).toEqual([]);
  });
});

describe("the noise rules", () => {
  it("A certain fault silences every heuristic", () => {
    const src = "int main(void) {\n    if (x = 3) return 1;\n    int y = 2\n    return 0;\n";
    expect(levels(src)).toEqual(["error"]);
  });

  it("A lost quote is one message, not three", () => {
    const issues = check('int main(void) {\n    puts("salut);\n    return 0;\n}\n');
    expect(issues).toHaveLength(1);
    expect(issues[0]!.message).toContain("guillemet");
  });

  it("never returns more than ten", () => {
    const src = "int main(void) {\n" + "    int a = 1\n".repeat(20) + "    return 0;\n}\n";
    expect(check(src)).toHaveLength(10);
  });

  it("returns them in reading order", () => {
    const issues = check("int main(void) {\n    int a = 1\n    int b = 2\n    return 0;\n}\n");
    expect(issues).toHaveLength(2);
    expect(issues[0]!.from).toBeLessThan(issues[1]!.from);
  });
});

describe("the next error (F2)", () => {
  const at = (from: number): Issue => ({ from, to: from + 1, message: "m", level: "error" });

  it("jumps to the first error after the caret", () => {
    expect(nextIssue([at(10), at(30), at(20)], 12)?.from).toBe(20);
  });

  it("wraps back to the first once the last is passed", () => {
    expect(nextIssue([at(10), at(30)], 99)?.from).toBe(10);
  });

  it("starts from the first when the caret is before everything", () => {
    expect(nextIssue([at(10), at(30)], 0)?.from).toBe(10);
  });

  it("says nothing when there is no error", () => {
    expect(nextIssue([], 0)).toBeNull();
  });

  it("moves past the error the caret is already on", () => {
    expect(nextIssue([at(10), at(30)], 10)?.from).toBe(30);
  });
});

// A program the new rules must all leave alone, so each case below differs by one line.
const inMain = (body: string, head = "#include <stdio.h>\n") =>
  head + "int main(void) {\n" + body + "    return 0;\n}\n";
const saysKey = (src: string, words: string): boolean => said(src).some((m) => m.includes(words));

describe("pasted typography", () => {
  it("flags a curly quote as a certain fault", () => {
    const src = inMain("    printf(\u201cBonjour\u201d);\n");
    expect(levels(src)).toContain("error");
    expect(saysKey(src, "typographique")).toBe(true);
  });

  it("flags a non-breaking space in the code", () => {
    expect(saysKey(inMain("    int\u00a0x = 1;\n"), "typographique")).toBe(true);
  });

  it("leaves them alone inside a string or a comment", () => {
    expect(check(inMain('    printf("\u00ab Bonjour \u00bb\\n"); // \u2019\n'))).toEqual([]);
  });
});

describe("the for with commas", () => {
  it("flags a for whose parts are separated by commas", () => {
    const src = inMain("    int i;\n    for (i = 0, i < 3, i++) {\n    }\n");
    expect(levels(src)).toEqual(["error"]);
    expect(saysKey(src, "« ; »")).toBe(true);
  });

  it("accepts a comma inside one part", () => {
    expect(check(inMain("    int i, j;\n    for (i = 0, j = 3; i < j; i++, j--) {\n    }\n"))).toEqual([]);
  });
});

describe("the struct without its semicolon", () => {
  it("flags the closing brace", () => {
    const src = "struct Point {\n    int x;\n}\n\nint f(void) {\n    return 0;\n}\n";
    expect(levels(src)).toEqual(["error"]);
    expect(saysKey(src, "struct")).toBe(true);
  });

  it("accepts a typedef name or a variable after the brace", () => {
    expect(check("typedef struct {\n    int x;\n} Point;\nstruct P {\n    int y;\n} p;\n")).toEqual([]);
  });
});

describe("the missing #include", () => {
  it("names the header a function needs", () => {
    const src = inMain('    printf("%d\\n", 1);\n', "");
    expect(saysKey(src, "stdio.h")).toBe(true);
  });

  it("names math.h for sqrt, even with stdio.h there", () => {
    expect(saysKey(inMain('    printf("%f\\n", sqrt(2.0));\n'), "math.h")).toBe(true);
  });

  it("says nothing in a file without main: its header may be elsewhere", () => {
    expect(said('int f(void) {\n    printf("x");\n    return 0;\n}\n')).toEqual([]);
  });

  it("says nothing when the student includes a header of their own", () => {
    expect(check(inMain('    printf("x");\n', '#include "outils.h"\n'))).toEqual([]);
  });
});

describe("printf and scanf formats", () => {
  it("counts the values the format announces", () => {
    expect(saysKey(inMain('    int a = 1;\n    printf("%d %d\\n", a);\n'), "annonce 2 valeurs")).toBe(true);
  });

  it("does not count %% or a correct call", () => {
    expect(check(inMain('    int a = 1;\n    printf("%d %%\\n", a);\n'))).toEqual([]);
  });

  it("asks for %lf to read a double", () => {
    const src = inMain('    double d;\n    scanf("%f", &d);\n');
    expect(saysKey(src, "« %lf »")).toBe(true);
  });

  it("accepts %lf for a double and %f for a float", () => {
    expect(check(inMain('    double d;\n    float f;\n    scanf("%lf %f", &d, &f);\n'))).toEqual([]);
  });

  it("flags %d for a double in printf", () => {
    expect(saysKey(inMain('    double d = 1.5;\n    printf("%d\\n", d);\n'), "« %f »")).toBe(true);
  });

  it("drops a name declared with two types", () => {
    const src = inMain('    int x = 1;\n    {\n        double x = 2;\n        printf("%f\\n", x);\n    }\n');
    expect(check(src)).toEqual([]);
  });
});

describe("the empty loop", () => {
  it("flags for (...); and while (...); followed by the block meant to repeat", () => {
    expect(saysKey(inMain("    int i;\n    for (i = 0; i < 3; i++);\n    {\n    }\n"), "boucle")).toBe(true);
    expect(saysKey(inMain("    int i = 0;\n    while (i < 3);\n    {\n        i++;\n    }\n"), "boucle")).toBe(
      true,
    );
  });

  it("leaves the empty loop that drains the input alone", () => {
    expect(check(inMain("    int c;\n    while ((c = getchar()) != '\\n' && c != -1);\n"))).toEqual([]);
  });

  it("leaves the while of a do ... while alone", () => {
    expect(check(inMain("    int i = 0;\n    do {\n        i++;\n    } while (i < 3);\n"))).toEqual([]);
  });
});

describe("comparisons a beginner writes like in maths", () => {
  it("flags == on a string", () => {
    expect(saysKey(inMain('    char s[8] = "oui";\n    if (s == "oui") return 1;\n'), "strcmp")).toBe(
      true,
    );
  });

  it("flags 0 < x < 10", () => {
    expect(saysKey(inMain("    int x = 3;\n    if (0 < x < 10) return 1;\n"), "&&")).toBe(true);
  });

  it("leaves two comparisons joined by && alone, and shifts too", () => {
    expect(check(inMain("    int x = 3;\n    if (0 < x && x < 10) return x << 2;\n"))).toEqual([]);
  });

  it("flags ^ used as a power", () => {
    expect(saysKey(inMain("    int x = 3;\n    int y = x ^ 2;\n"), "pow")).toBe(true);
  });

  it("flags a division that truncates, not one that is exact or real", () => {
    expect(saysKey(inMain("    double v = 4 / 3 * 3.14;\n"), "4.0 / 3")).toBe(true);
    expect(check(inMain("    double v = 4.0 / 3 + 10 / 2;\n"))).toEqual([]);
  });
});

describe("arrays, keywords and literals", () => {
  it("flags <= N on an array of N cells", () => {
    expect(saysKey(inMain("    int t[5];\n    int i;\n    for (i = 0; i <= 5; i++) t[i] = 0;\n"), "< »")).toBe(
      true,
    );
  });

  it("leaves a loop from 1 to N alone: that is a sum, not an index", () => {
    expect(check(inMain("    int t[5];\n    int i, s = 0;\n    for (i = 1; i <= 5; i++) s += i;\n"))).toEqual([]);
  });

  it("flags a capitalised keyword", () => {
    expect(saysKey(inMain("    int x = 1;\n    If (x) return 1;\n"), "« if »")).toBe(true);
  });

  it("flags several characters between apostrophes, not an escape", () => {
    expect(saysKey(inMain("    char c = 'oui';\n"), "guillemets")).toBe(true);
    expect(check(inMain("    char c = '\\n';\n    char z = '\\0';\n"))).toEqual([]);
  });

  it("flags void main", () => {
    expect(saysKey("#include <stdio.h>\nvoid main(void) {\n}\n", "int main")).toBe(true);
  });
});
