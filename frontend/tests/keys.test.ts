// LES TOUCHES DE L'ÉDITEUR. `keyEdit()` est pure, donc elle s'éprouve en
// l'appelant -- il n'y a pas de faux DOM à piloter, et `execCommand` (que le
// composant utilise pour garder la pile d'annulation) n'existe pas dans jsdom :
// une raison de plus pour que la décision vive dehors.

import { describe, expect, it } from "vitest";
import { keyEdit, type Edit } from "../src/lib/domain/keys";

/**
 * Applique une modification à un texte et rend le résultat avec le curseur
 * marqué par `|` (ou la sélection encadrée), pour que les cas se lisent.
 * `§` marque le curseur dans l'entrée.
 */
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

describe("les paires", () => {
  it("ferme les quatre paires et laisse le curseur dedans", () => {
    expect(press("(", "printf§")).toBe("printf(|)");
    expect(press("[", "int t§")).toBe("int t[|]");
    expect(press("{", "if (x) §")).toBe("if (x) {|}");
    expect(press('"', "puts(§)")).toBe('puts("|")');
  });

  it("survole le fermant au lieu d'en écrire un second", () => {
    expect(press(")", "printf(§)")).toBe("printf()|");
    expect(press('"', 'puts("hi§")')).toBe('puts("hi"|)');
  });

  it("encadre une sélection plutôt que de la remplacer", () => {
    expect(press("(", "return §x + 1§;")).toBe("return (|x + 1|);");
    expect(press('"', "§salut§")).toBe('"|salut|"');
  });

  it("N'ENCADRE PAS quand du texte suit : on tape devant un mot existant", () => {
    expect(press("(", "§printf")).toBeNull();
    expect(press("[", "§tableau")).toBeNull();
  });

  // LE PIÈGE QUI COÛTERAIT UNE SESSION : les commentaires du cours sont en
  // français, et « aujourd'hui » ne doit pas devenir « aujourd''hui ».
  it("ne ferme pas une apostrophe collée à un mot", () => {
    expect(press("'", "// aujourd§")).toBeNull();
    expect(press("'", "// c§")).toBeNull();
  });

  it("ferme une apostrophe là où c'est un littéral C", () => {
    expect(press("'", "char c = §;")).toBe("char c = '|';");
  });
});

describe("Backspace", () => {
  it("efface les deux moitiés d'une paire vide", () => {
    expect(press("Backspace", "printf(§)")).toBe("printf|");
    expect(press("Backspace", 'puts("§")')).toBe("puts(|)");
  });

  it("laisse le navigateur faire quand la paire n'est pas vide", () => {
    expect(press("Backspace", "printf(§x)")).toBeNull();
  });

  it("efface un niveau d'indentation d'un seul coup", () => {
    expect(press("Backspace", "        §x")).toBe("    |x");
    // Un décalage de deux espaces retombe sur le multiple de quatre.
    expect(press("Backspace", "      §x")).toBe("    |x");
  });
});

describe("Tab", () => {
  it("va jusqu'au prochain multiple de quatre", () => {
    expect(press("Tab", "§x")).toBe("    |x");
    expect(press("Tab", "  §x")).toBe("    |x");
    expect(press("Tab", "    §x")).toBe("        |x");
  });

  it("indente tout un bloc sélectionné en gardant la sélection", () => {
    const out = press("Tab", "§un\ndeux\ntrois§");
    expect(out).toBe("|    un\n    deux\n    trois|");
  });

  it("désindente le bloc avec Maj, et le rend à son état de départ", () => {
    const indented = "    un\n    deux";
    const start = indented.length;
    const edit = keyEdit("Tab", true, indented, 0, start) as Edit;
    const out = indented.slice(0, edit.from) + edit.insert + indented.slice(edit.to);
    expect(out).toBe("un\ndeux");
  });

  it("désindente la ligne courante où que soit le curseur dedans", () => {
    expect(press("Tab", "    if§ (x)", true)).toBe("if| (x)");
  });

  it("ne fait rien sur une ligne déjà à gauche", () => {
    expect(press("Tab", "if§ (x)", true)).toBe("if| (x)");
  });
});

describe("Entrée", () => {
  it("recopie l'indentation de la ligne", () => {
    expect(press("Enter", "    x = 1;§")).toBe("    x = 1;\n    |");
  });

  it("laisse le navigateur faire quand il n'y a rien à recopier", () => {
    expect(press("Enter", "x = 1;§")).toBeNull();
  });

  it("ouvre un bloc entre deux accolades, le fermant sur sa propre ligne", () => {
    expect(press("Enter", "    if (x) {§}")).toBe("    if (x) {\n        |\n    }");
  });

  it("indente d'un niveau après une accolade ouvrante seule", () => {
    expect(press("Enter", "    if (x) {§")).toBe("    if (x) {\n        |");
  });
});

describe("l'accolade fermante", () => {
  it("se recale d'un niveau quand elle est seule sur sa ligne", () => {
    expect(press("}", "if (x) {\n    y;\n        §")).toBe("if (x) {\n    y;\n    }|");
  });

  it("ne bouge pas ce qui n'est pas de l'indentation", () => {
    expect(press("}", "if (x) { y;§")).toBeNull();
  });
});

describe("ce qui n'est pas à nous", () => {
  it("laisse passer les touches sans effet d'édition", () => {
    for (const key of ["ArrowLeft", "Home", "F5", "Shift", "PageDown"]) {
      expect(keyEdit(key, false, "x", 1, 1), key).toBeNull();
    }
  });

  it("laisse passer une lettre ordinaire", () => {
    expect(keyEdit("a", false, "x", 1, 1)).toBeNull();
  });
});
