// LA FORME CANONIQUE, CÔTÉ PAGE. Les deux fonctions sont pures, donc elles
// s'éprouvent en les appelant.
//
// LES ATTENTES NE SONT PAS ÉCRITES ICI. Elles vivent dans
// `fixtures/source.json`, que `test_ctester.py` lit AUSSI pour éprouver
// `app/services/source.py`. C'est ce qui remplace l'appel croisé qu'un jumeau
// dans le même langage permettrait : deux implémentations dans deux langages
// ne peuvent pas s'appeler l'une l'autre, mais elles peuvent répondre de la
// même table. Une copie locale d'un cas, et la divergence redevient muette.

import { describe, expect, it } from "vitest";
import cases from "./fixtures/source.json";
import { canonicalize, canonicalizeFiles, decodeImported } from "../src/lib/domain/source";

describe("la forme canonique d'une source", () => {
  it("LIT VRAIMENT LE FIXTURE PARTAGÉ", () => {
    // Sans ce contrôle, un fixture renommé ou vidé ferait passer toute la
    // suite en n'éprouvant rien -- le même piège que `bundle.test.ts` et
    // `markdown.test.ts` gardent chacun de leur côté.
    expect(cases.encodage.length).toBeGreaterThanOrEqual(6);
    expect(cases.espaces_morts.length).toBeGreaterThanOrEqual(5);
    expect(cases.silences.length).toBeGreaterThanOrEqual(7);
  });

  it("retire le BOM et remet les fins de ligne en LF", () => {
    for (const c of cases.encodage) {
      expect(canonicalize(c.in), c.why).toBe(c.out);
      expect(decodeImported(c.in), c.why).toBe(c.out);
    }
  });

  it("coupe les espaces morts en fin de ligne, sauf sur un raccord", () => {
    for (const c of cases.espaces_morts) expect(canonicalize(c.in), c.why).toBe(c.out);
  });

  it("SE TAIT SUR TOUT LE RESTE -- c'est la moitié qui la rend invisible", () => {
    for (const c of cases.silences) {
      expect(c.out, "ce cas doit être un point fixe").toBe(c.in);
      expect(canonicalize(c.in), c.why).toBe(c.in);
    }
  });

  it("« ouvrir un fichier » EN FAIT MOINS, délibérément", () => {
    // Couper les espaces morts À L'IMPORT modifierait le fichier de
    // l'étudiant à l'instant où il le regarde arriver. Le serveur les coupe à
    // l'écriture, ce qui ne se voit pas.
    for (const c of cases.espaces_morts) expect(decodeImported(c.in), c.why).toBe(c.in);
  });

  it("NE CHANGE JAMAIS LE NOMBRE DE LIGNES, et ne peut que raccourcir", () => {
    // La gouttière de `CodeSurface.svelte` est `value.split("\n").length` : un
    // `\n` de plus ou de moins est un NUMÉRO DE LIGNE qui apparaît ou
    // disparaît sous les yeux de l'étudiant -- et un numéro de ligne de gcc
    // qui ne désigne plus la même chose.
    for (const c of [...cases.encodage, ...cases.espaces_morts, ...cases.silences]) {
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
