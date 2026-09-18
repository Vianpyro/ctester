import { describe, expect, it } from "vitest";
import { headerTemplate, validHeaderName } from "../src/lib/domain/scratchHeader";

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
