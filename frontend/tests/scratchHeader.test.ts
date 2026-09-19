import { describe, expect, it } from "vitest";
import { consoleFiles, headerTemplate, validHeaderName } from "../src/lib/domain/scratchHeader";

describe("copying an exercise into the Console", () => {
  it("keeps a full program as it is", () => {
    const code = "int main(void)\n{\n    return 0;\n}\n";
    expect(consoleFiles([{ name: "submission.c" }], { "submission.c": code })).toEqual({
      code,
      headerName: "",
      header: "",
    });
  });

  it("gives a module its header and a main() to call it from", () => {
    const moved = consoleFiles([{ name: "fonctions.h" }, { name: "fonctions.c" }], {
      "fonctions.h": "int carre(int x);\n",
      "fonctions.c": '#include "fonctions.h"\nint carre(int x) { return x * x; }\n',
    });
    if (typeof moved === "string") throw new Error(moved);
    expect(moved.headerName).toBe("fonctions.h");
    expect(moved.header).toBe("int carre(int x);\n");
    expect(moved.code.startsWith('#include "fonctions.h"\nint carre')).toBe(true);
    expect(moved.code).toContain("int main(void)");
  });

  it("joins every .c file into main.c without adding a second main()", () => {
    const moved = consoleFiles(
      [{ name: "matrac_lib.h" }, { name: "matrac_lib.c" }, { name: "main.c" }],
      { "matrac_lib.h": "", "matrac_lib.c": "int f(void) { return 1; }", "main.c": "int main(void) { return f(); }" },
    );
    if (typeof moved === "string") throw new Error(moved);
    expect(moved.code).toContain("/* matrac_lib.c */\nint f(void)");
    expect(moved.code).toContain("/* main.c */\nint main(void)");
    expect(moved.code.match(/\bmain\s*\(/g)).toHaveLength(1);
  });

  it("refuses what the Console cannot hold", () => {
    expect(typeof consoleFiles([{ name: "a.h" }, { name: "b.h" }, { name: "a.c" }], { "a.c": "x" })).toBe(
      "string",
    );
    expect(typeof consoleFiles([{ name: "submission.c" }], { "submission.c": "  \n" })).toBe("string");
  });
});

describe("the Console's header", () => {
  it("accepts the same names as the server and the judge", () => {
    for (const good of ["pile.h", "pile_2.h", "a".repeat(32) + ".h"]) {
      expect(validHeaderName(good), good).toBe(true);
    }
    for (const bad of [
      "",
      ".h",
      "pile.c",
      "pile.H",
      "../pile.h",
      "a/b.h",
      "pi le.h",
      "é.h",
      "pile.h\n",
      "a".repeat(33) + ".h",
    ]) {
      expect(validHeaderName(bad), bad).toBe(false);
    }
  });

  it("suggests an include guard that is a C identifier", () => {
    const pile = headerTemplate("pile.h");
    expect(pile.startsWith("#ifndef PILE_H\n#define PILE_H\n")).toBe(true);
    expect(pile.trimEnd().endsWith("#endif /* PILE_H */")).toBe(true);
    expect(headerTemplate("2d_outils.h")).toContain("#define H_2D_OUTILS_H\n");
  });
});
