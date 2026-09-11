// LA TABLE NE PEUT PAS MENTIR, ET C'EST CE QUE CETTE SUITE TIENT.
//
// Un raccourci lié mais absent de l'aide-mémoire est un geste que personne ne
// découvre ; un raccourci affiché mais non lié est une touche qui a l'air
// cassée. Les deux se rattrapent ici, par des assertions qui lisent la table
// plutôt que d'entretenir une liste à côté.
//
// LA MOITIÉ DES CAS GARDENT UN SILENCE, comme `syntax.test.ts` : pour chaque
// frappe qui doit être à nous, son jumeau qui doit rester au navigateur. C'est
// la moitié qui compte -- un matcher trop gourmand vole Ctrl+Z, et une page qui
// vole Ctrl+Z dans un éditeur de code est pire que pas de raccourcis du tout.

import { describe, expect, it } from "vitest";
import {
  EDITOR_COMMANDS,
  TEXT_COMMANDS,
  matchShortcut,
  type Chord,
  type ShortcutId,
} from "../src/lib/domain/shortcuts";

/** Une frappe, écrite comme on la décrit à l'oral. */
function chord(key: string, mods: Partial<Omit<Chord, "key">> = {}): Chord {
  return {
    key,
    shiftKey: false,
    ctrlKey: false,
    metaKey: false,
    altKey: false,
    ...mods,
  };
}

const ctrl = (key: string, mods: Partial<Omit<Chord, "key">> = {}) =>
  chord(key, { ctrlKey: true, ...mods });

describe("ce qui est à nous", () => {
  it("lie les sept transformations de texte", () => {
    expect(matchShortcut(ctrl("/"))).toBe("commentLine");
    expect(matchShortcut(ctrl("?", { shiftKey: true }))).toBe("commentBlock");
    expect(matchShortcut(ctrl("d"))).toBe("duplicate");
    expect(matchShortcut(ctrl("k", { shiftKey: true }))).toBe("deleteLine");
    expect(matchShortcut(ctrl("d", { shiftKey: true }))).toBe("deleteLine");
    expect(matchShortcut(chord("ArrowUp", { altKey: true, shiftKey: true }))).toBe("moveUp");
    expect(matchShortcut(chord("ArrowDown", { altKey: true, shiftKey: true }))).toBe("moveDown");
    expect(matchShortcut(ctrl("Enter", { shiftKey: true }))).toBe("completeStatement");
  });

  it("lie la navigation et la page", () => {
    expect(matchShortcut(chord("F2"))).toBe("nextIssue");
    expect(matchShortcut(ctrl("g"))).toBe("gotoLine");
    expect(matchShortcut(ctrl("s"))).toBe("save");
    expect(matchShortcut(ctrl("Enter"))).toBe("run");
    expect(matchShortcut(chord("F1"))).toBe("help");
    expect(matchShortcut(ctrl("k"))).toBe("catalog");
    expect(matchShortcut(chord("Escape"))).toBe("escape");
  });

  it("accepte ⌘ partout où Ctrl est accepté", () => {
    // Un Mac dans la salle, et la moitié du lot serait morte.
    expect(matchShortcut(chord("s", { metaKey: true }))).toBe("save");
    expect(matchShortcut(chord("d", { metaKey: true }))).toBe("duplicate");
    expect(matchShortcut(chord("Enter", { metaKey: true }))).toBe("run");
  });
});

describe("la disposition du clavier", () => {
  // Le cœur du sujet : en canadien-français `/` se tape `Maj+3`, donc il ARRIVE
  // avec Maj tenu. S'il fallait Maj relâché, la moitié de la cohorte n'aurait
  // jamais pu commenter une ligne.
  it("commente la ligne que Maj soit tenu ou non", () => {
    expect(matchShortcut(ctrl("/"))).toBe("commentLine");
    expect(matchShortcut(ctrl("/", { shiftKey: true }))).toBe("commentLine");
  });

  it("SILENCE : `?` n'est jamais le commentaire de LIGNE, et réciproquement", () => {
    // C'est le caractère qui sépare les deux commandes, pas le drapeau Maj.
    expect(matchShortcut(ctrl("?"))).toBe("commentBlock");
    expect(matchShortcut(ctrl("?", { shiftKey: true }))).toBe("commentBlock");
    expect(matchShortcut(ctrl("/"))).not.toBe("commentBlock");
  });

  it("SILENCE : AltGr n'est pas Ctrl, et il doit continuer d'écrire son caractère", () => {
    // Sous Windows AltGr se rapporte `ctrlKey && altKey`. Sans la garde, taper un
    // caractère AltGr commenterait la ligne au lieu de l'écrire.
    expect(matchShortcut(ctrl("/", { altKey: true }))).toBeNull();
    expect(matchShortcut(ctrl("?", { altKey: true }))).toBeNull();
    expect(matchShortcut(ctrl("d", { altKey: true }))).toBeNull();
  });

  it("SILENCE : une touche nue n'est jamais un raccourci", () => {
    expect(matchShortcut(chord("/"))).toBeNull();
    expect(matchShortcut(chord("?"))).toBeNull();
    expect(matchShortcut(chord("d"))).toBeNull();
    expect(matchShortcut(chord("Enter"))).toBeNull();
  });
});

describe("Maj départage, et Verr.Maj ne départage rien", () => {
  it("sépare le catalogue de la suppression de ligne", () => {
    expect(matchShortcut(ctrl("k"))).toBe("catalog");
    expect(matchShortcut(ctrl("k", { shiftKey: true }))).toBe("deleteLine");
  });

  it("sépare Tester de « compléter l'instruction »", () => {
    expect(matchShortcut(ctrl("Enter"))).toBe("run");
    expect(matchShortcut(ctrl("Enter", { shiftKey: true }))).toBe("completeStatement");
  });

  it("sépare dupliquer de supprimer", () => {
    expect(matchShortcut(ctrl("d"))).toBe("duplicate");
    expect(matchShortcut(ctrl("d", { shiftKey: true }))).toBe("deleteLine");
  });

  it("ouvre le catalogue même avec Verr.Maj -- le bogue que la table répare", () => {
    // L'ancienne condition écrite à la main comparait `event.key !== "k"`, et
    // `Ctrl+K` ne faisait donc rien du tout quand Verr.Maj était actif.
    expect(matchShortcut(ctrl("K"))).toBe("catalog");
    expect(matchShortcut(ctrl("D"))).toBe("duplicate");
    expect(matchShortcut(ctrl("S"))).toBe("save");
  });
});

describe("SILENCE : ce qui reste au navigateur et à l'étudiant", () => {
  it("ne touche à rien de ce qu'un éditeur doit au navigateur", () => {
    for (const key of ["z", "y", "c", "v", "x", "a", "f", "p", "r", "w", "t"]) {
      expect(matchShortcut(ctrl(key)), "Ctrl+" + key).toBeNull();
    }
    // Refaire, dans ses deux écritures.
    expect(matchShortcut(ctrl("z", { shiftKey: true }))).toBeNull();
    expect(matchShortcut(ctrl("y"))).toBeNull();
  });

  it("ne réclame pas une flèche à qui il manque un modificateur", () => {
    expect(matchShortcut(chord("ArrowUp"))).toBeNull();
    expect(matchShortcut(chord("ArrowUp", { shiftKey: true }))).toBeNull();
    expect(matchShortcut(chord("ArrowUp", { altKey: true }))).toBeNull();
    expect(matchShortcut(chord("ArrowUp", { ctrlKey: true, altKey: true, shiftKey: true }))).toBeNull();
    expect(matchShortcut(chord("ArrowDown", { ctrlKey: true, shiftKey: true }))).toBeNull();
  });

  it("ne réclame pas Échap dès qu'un modificateur est tenu", () => {
    expect(matchShortcut(ctrl("Escape"))).toBeNull();
    expect(matchShortcut(chord("Escape", { shiftKey: true }))).toBeNull();
    expect(matchShortcut(chord("Escape", { altKey: true }))).toBeNull();
  });

  it("laisse Tab et les touches ordinaires à `keyEdit`", () => {
    // Les paires auto-fermées et l'indentation vivent dans `keys.ts` et n'ont
    // rien à faire dans cette table.
    for (const key of ["Tab", "Backspace", "a", "(", "{", '"', "'"]) {
      expect(matchShortcut(chord(key)), key).toBeNull();
    }
  });
});

describe("les deux ensembles", () => {
  it("range chaque transformation de texte dans les commandes de l'éditeur", () => {
    // `TEXT_COMMANDS` est un sous-ensemble strict : `F2` et `Ctrl+G` sont de
    // l'éditeur sans transformer une ligne, et c'est exactement ce qui les
    // laisse marcher sur un document verrouillé.
    for (const id of TEXT_COMMANDS) {
      expect(EDITOR_COMMANDS.has(id), id).toBe(true);
    }
    expect(EDITOR_COMMANDS.has("nextIssue")).toBe(true);
    expect(EDITOR_COMMANDS.has("gotoLine")).toBe(true);
    expect(TEXT_COMMANDS.has("nextIssue")).toBe(false);
    expect(TEXT_COMMANDS.has("gotoLine")).toBe(false);
  });

  it("garde les commandes de la PAGE hors de la surface d'édition", () => {
    // Si la surface les réclamait, elle les `preventDefault()`erait et la
    // fenêtre ne les verrait jamais : Ctrl+S et Ctrl+Entrée seraient morts
    // précisément là où le curseur de l'étudiant se trouve.
    for (const id of ["save", "run", "help", "catalog", "escape"] as ShortcutId[]) {
      expect(EDITOR_COMMANDS.has(id), id).toBe(false);
    }
  });
});
