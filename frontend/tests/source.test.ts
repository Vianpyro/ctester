import { describe, expect, it } from "vitest";
import cases from "./fixtures/source.json";
import { canonicalize, canonicalizeFiles, decodeImported } from "../src/lib/domain/source";

describe("la forme canonique d'une source", () => {
  it("LIT VRAIMENT LE FIXTURE PARTAGÉ", () => {
    expect(cases.encoding.length).toBeGreaterThanOrEqual(6);
    expect(cases.dead_whitespace.length).toBeGreaterThanOrEqual(5);
    expect(cases.untouched.length).toBeGreaterThanOrEqual(7);
  });

  it("retire le BOM et remet les fins de ligne en LF", () => {
    for (const c of cases.encoding) {
      expect(canonicalize(c.in), c.why).toBe(c.out);
      expect(decodeImported(c.in), c.why).toBe(c.out);
    }
  });

  it("coupe les espaces morts en fin de ligne, sauf sur un raccord", () => {
    for (const c of cases.dead_whitespace) expect(canonicalize(c.in), c.why).toBe(c.out);
  });

  it("SE TAIT SUR TOUT LE RESTE -- c'est la moitié qui la rend invisible", () => {
    for (const c of cases.untouched) {
      expect(c.out, "ce cas doit être un point fixe").toBe(c.in);
      expect(canonicalize(c.in), c.why).toBe(c.in);
    }
  });

  it("« ouvrir un fichier » EN FAIT MOINS, délibérément", () => {
    for (const c of cases.dead_whitespace) expect(decodeImported(c.in), c.why).toBe(c.in);
  });

  it("NE CHANGE JAMAIS LE NOMBRE DE LIGNES, et ne peut que raccourcir", () => {
    for (const c of [...cases.encoding, ...cases.dead_whitespace, ...cases.untouched]) {
      const got = canonicalize(c.in);
      if (!c.in.includes("\r")) {
        expect(got.split("\n").length, c.why).toBe(c.in.split("\n").length);
      }
      expect(got.length, c.why).toBeLessThanOrEqual(c.in.length);
      expect(canonicalize(got), "idempotence: " + c.why).toBe(got);
    }
  });

  it("s'applique fichier par fichier, dans un NOUVEL objet", () => {
    const source = { "calendrier.h": "int f(void);  \n", "calendrier.c": "int f(void){\r\n}\r\n" };
    const out = canonicalizeFiles(source);
    expect(out).toEqual({ "calendrier.h": "int f(void);\n", "calendrier.c": "int f(void){\n}\n" });
    expect(source["calendrier.h"]).toBe("int f(void);  \n");
  });
});
