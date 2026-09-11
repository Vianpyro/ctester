// LES TOUCHES DE L'ÉDITEUR. `keyEdit()` est pure, donc elle s'éprouve en
// l'appelant -- il n'y a pas de faux DOM à piloter, et `execCommand` (que le
// composant utilise pour garder la pile d'annulation) n'existe pas dans jsdom :
// une raison de plus pour que la décision vive dehors.

import { describe, expect, it } from "vitest";
import { commandEdit, keyEdit, lineSpan, parseLine, type Edit } from "../src/lib/domain/keys";
import type { ShortcutId } from "../src/lib/domain/shortcuts";

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

// --- LES COMMANDES D'UN IDE ------------------------------------------------
//
// Même idiome que `press()` juste au-dessus : `§` marque le curseur, `|` le
// rend. La moitié des cas gardent un SILENCE -- pour chaque geste qui doit
// agir, celui qui doit laisser le texte intact.

/** Le jumeau de `press()`, pour une commande plutôt qu'une touche. */
function run(id: ShortcutId, marked: string): string | null {
  const start = marked.indexOf("§");
  const rest = marked.slice(start + 1);
  const second = rest.indexOf("§");
  const value = marked.replace(/§/g, "");
  const end = second === -1 ? start : start + second;
  const edit = commandEdit(id, value, start, end);
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

/** Le texte seul, sans les marques -- pour les cas où seule la forme compte. */
const text = (id: ShortcutId, marked: string) => run(id, marked)?.replace(/\|/g, "") ?? null;

describe("commenter", () => {
  it("pose `// ` sur la ligne du curseur", () => {
    expect(text("commentLine", "  int x§ = 1;")).toBe("  // int x = 1;");
  });

  it("retire `// ` quand tout le bloc est commenté", () => {
    expect(text("commentLine", "§// int x;\n// int y;§")).toBe("int x;\nint y;");
  });

  it("SILENCE sur le sens : un bloc MIXTE se fait commenter, pas décommenter", () => {
    // Décommenter sur la foi de la première ligne laisserait la seconde
    // commentée sans que personne ne le voie.
    expect(text("commentLine", "§// int x;\nint y;§")).toBe("// // int x;\n// int y;");
  });

  it("aligne les `//` en COLONNE et garde l'indentation relative", () => {
    // Un `//` posé à l'indentation propre de chaque ligne les mettrait en
    // escalier ; posé au début de chaque ligne, il écraserait l'escalier du
    // code. La colonne commune garde les deux lisibles -- et c'est ce que fait
    // CLion. Ici `int b;` reste décalé de quatre espaces APRÈS son `//`.
    expect(text("commentLine", "§    int a;\n        int b;§")).toBe(
      "    // int a;\n    //     int b;",
    );
  });

  it("SILENCE sur les lignes vides d'un bloc : elles ne reçoivent rien", () => {
    expect(text("commentLine", "§int a;\n\nint b;§")).toBe("// int a;\n\n// int b;");
  });

  it("commente quand même une ligne vide SEULE, sinon la touche a l'air morte", () => {
    expect(text("commentLine", "  §")).toBe("  // ");
  });

  it("fait un aller-retour EXACT, et garde une espace d'alignement voulue", () => {
    expect(text("commentLine", "§//x§")).toBe("x");
    expect(text("commentLine", "§// x§")).toBe("x");
    expect(text("commentLine", "§//  x§")).toBe(" x");
  });

  it("SILENCE sur la ligne d'en dessous quand la sélection finit à son début", () => {
    // Une sélection à la souris de UNE ligne finit au début de la deuxième.
    expect(text("commentLine", "§int a;\n§int b;")).toBe("// int a;\nint b;");
    // Un caractère dedans, et la deuxième compte vraiment.
    expect(text("commentLine", "§int a;\ni§nt b;")).toBe("// int a;\n// int b;");
  });

  it("garde le curseur sur sa ligne", () => {
    expect(run("commentLine", "int §x;")).toBe("// int |x;");
  });
});

describe("commentaire de bloc", () => {
  it("encadre la sélection et la garde sélectionnée", () => {
    expect(run("commentBlock", "a = §b + c§;")).toBe("a = |/*b + c*/|;");
  });

  it("désencadre ce qu'il a encadré", () => {
    expect(text("commentBlock", "a = §/*b + c*/§;")).toBe("a = b + c;");
  });

  it("pose une coquille vide sous le curseur nu", () => {
    expect(run("commentBlock", "a;§")).toBe("a;/* | */");
  });

  it("SILENCE : un `*/` au milieu fait retomber sur le commentaire de ligne", () => {
    // C n'imbrique pas les blocs : encadrer fermerait au premier `*/` et
    // rendrait du code qui ne compile plus, en silence.
    expect(text("commentBlock", "§int a; /* n */\nint b;§")).toBe("// int a; /* n */\n// int b;");
  });
});

describe("dupliquer", () => {
  it("copie la ligne en dessous, même colonne, sans sélection", () => {
    expect(run("duplicate", "int §x;")).toBe("int x;\nint |x;");
  });

  it("copie un bloc de lignes ENTIÈRES en dessous, et sélectionne la COPIE", () => {
    // Sans ce cas, on obtiendrait `int a;int a;\nint b;` -- la copie recollée
    // au milieu du texte.
    expect(run("duplicate", "§int a;\nint b;§")).toBe("int a;\nint b;\n|int a;\nint b;|");
  });

  it("copie une sélection partielle juste après elle", () => {
    expect(run("duplicate", "f(§abc§);")).toBe("f(abc|abc|);");
  });

  it("est répétable : deux passes donnent deux copies", () => {
    const once = text("duplicate", "§int a;")!;
    expect(once).toBe("int a;\nint a;");
  });
});

describe("supprimer la ligne", () => {
  it("emporte la ligne et son saut de ligne", () => {
    expect(text("deleteLine", "int a;\nint §b;\nint c;")).toBe("int a;\nint c;");
  });

  it("prend le saut de ligne D'AVANT sur la dernière ligne", () => {
    // Sinon le fichier garde une dernière ligne vide, qui s'accumule.
    expect(text("deleteLine", "int a;\nint §b;")).toBe("int a;");
  });

  it("vide le fichier quand il n'y a qu'une ligne", () => {
    expect(text("deleteLine", "int §a;")).toBe("");
  });

  it("SILENCE sur un fichier déjà vide", () => {
    expect(run("deleteLine", "§")).toBeNull();
  });
});

describe("déplacer la ligne", () => {
  it("monte la ligne et emmène le curseur avec elle", () => {
    expect(run("moveUp", "int a;\nint §b;")).toBe("int |b;\nint a;");
  });

  it("descend la ligne et emmène le curseur avec elle", () => {
    expect(run("moveDown", "int §a;\nint b;")).toBe("int b;\nint |a;");
  });

  it("garde la SÉLECTION sur le bloc déplacé, pour qu'on puisse recommencer", () => {
    expect(run("moveDown", "§int a;\nint b;§\nint c;")).toBe("int c;\n|int a;\nint b;|");
  });

  it("promène le bloc quand on répète", () => {
    // La propriété qui rend le geste utilisable : tenir le chord fait monter.
    const once = text("moveUp", "a\nb\n§c")!;
    expect(once).toBe("a\nc\nb");
    expect(text("moveUp", "a\n§c\nb")).toBe("c\na\nb");
  });

  it("SILENCE aux deux bouts, et le texte reste INTACT", () => {
    expect(run("moveUp", "int §a;\nint b;")).toBeNull();
    expect(run("moveDown", "int a;\nint §b;")).toBeNull();
    expect(run("moveUp", "§int a;\nint b;§")).toBeNull();
  });
});

describe("compléter l'instruction", () => {
  it("ajoute le `;` et ouvre la ligne suivante, indentée", () => {
    expect(run("completeStatement", "    int x = 1§")).toBe("    int x = 1;\n    |");
  });

  it("SILENCE : une ligne qui finit déjà par `;` n'en gagne pas un second", () => {
    expect(run("completeStatement", "    int x = 1;§")).toBe("    int x = 1;\n    |");
  });

  it("SILENCE SUR `if (x)`, et c'est le point-virgule le plus cher du cours", () => {
    // `if (x);` compile, tourne, et fait le contraire de ce qu'il se lit.
    expect(run("completeStatement", "    if (x)§")).toBe("    if (x)\n    |");
    expect(run("completeStatement", "for (;;)§")).toBe("for (;;)\n|");
    expect(run("completeStatement", "while (a)§")).toBe("while (a)\n|");
    expect(run("completeStatement", "#include <stdio.h>§")).toBe("#include <stdio.h>\n|");
  });

  it("descend d'un niveau après une accolade ouvrante", () => {
    expect(run("completeStatement", "    if (x) {§")).toBe("    if (x) {\n        |");
  });
});

describe("aller à la ligne", () => {
  it("rend la plage de la ligne demandée, numérotée depuis 1", () => {
    expect(lineSpan("aa\nbbb\nc", 2)).toEqual({ from: 3, to: 6 });
    expect(lineSpan("aa\nbbb\nc", 1)).toEqual({ from: 0, to: 2 });
  });

  it("BORNE au lieu de refuser : 999 veut dire « la fin »", () => {
    expect(parseLine("999", 5)).toBe(5);
    expect(parseLine("  3 ", 5)).toBe(3);
  });

  it("SILENCE sur ce qui n'est pas un numéro de ligne", () => {
    for (const bad of ["", "0", "abc", "-2", "1.5", "2e3"]) {
      expect(parseLine(bad, 5), bad).toBeNull();
    }
  });
});
