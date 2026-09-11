// LES TOUCHES DE L'ÉDITEUR, ET RIEN QUE LEUR LOGIQUE. Aucun DOM, aucun `fetch` :
// cette fonction prend un texte, une sélection et une touche, et rend la
// modification à faire -- ou `null` pour laisser le navigateur faire son travail.
// C'est ce qui la rend éprouvable en l'appelant (`tests/keys.test.ts`), et c'est
// aussi ce qui garde `CodeEditor.svelte` sans une décision dedans.
//
// ponytail: DES HEURISTIQUES DE POSITION, PAS UN LEXEUR. Cette fonction ne sait
// pas si le curseur est dans une chaîne ou dans un commentaire, et ne compte pas
// l'équilibre des parenthèses. Le pire qu'elle puisse faire est une paire de
// trop, que `Backspace` retire du même geste. Le lexeur C existe déjà
// (`domain/highlight.ts`) : c'est lui qu'il faudra brancher ici le jour où un
// mauvais placement se voit vraiment.

import type { ShortcutId } from "./shortcuts";

/** Une modification : la plage remplacée, ce qui la remplace, où va le curseur. */
export interface Edit {
  from: number;
  to: number;
  /** "" veut dire une suppression -- ou, si `from === to`, un simple déplacement. */
  insert: string;
  caret: number;
  /** Pour garder une sélection : l'indentation d'un bloc, l'encadrement d'un mot. */
  caretEnd?: number;
}

/** Quatre espaces, comme le cours et comme le `tab-size` de la feuille. */
const INDENT = 4;

const PAIRS: Record<string, string> = {
  "(": ")",
  "[": "]",
  "{": "}",
  '"': '"',
  "'": "'",
};

const CLOSERS = new Set([")", "]", "}", '"', "'"]);
const QUOTES = new Set(['"', "'"]);

const isWord = (ch: string | undefined): boolean => !!ch && /[A-Za-z0-9_]/.test(ch);

/** Le début de la ligne qui contient `pos`. */
const lineStart = (value: string, pos: number): number => value.lastIndexOf("\n", pos - 1) + 1;

/** La fin de la ligne qui contient `pos`, fin du texte comprise. */
function lineEnd(value: string, pos: number): number {
  const nl = value.indexOf("\n", pos);
  return nl === -1 ? value.length : nl;
}

/** Un niveau de moins : une tabulation, sinon jusqu'à `INDENT` espaces. */
function dedentLine(line: string): string {
  if (line.startsWith("\t")) return line.slice(1);
  const m = /^ {1,4}/.exec(line);
  return m ? line.slice(m[0].length) : line;
}

/** L'indentation de la ligne courante, telle qu'un retour à la ligne la recopie. */
function indentOf(value: string, pos: number): string {
  const head = value.slice(lineStart(value, pos), pos);
  return /^[ \t]*/.exec(head)![0];
}

/**
 * Ce que la touche `key` doit faire, ou `null` pour ne rien faire de spécial.
 * `null` n'est pas un refus : c'est « le comportement du navigateur est le bon »,
 * ce qui vaut mieux qu'une modification programmée pour la pile d'annulation.
 */
export function keyEdit(
  key: string,
  shift: boolean,
  value: string,
  start: number,
  end: number,
): Edit | null {
  if (key === "Tab") return tab(shift, value, start, end);
  if (key === "Enter") return enter(value, start, end);
  if (key === "Backspace") return backspace(value, start, end);
  if (key.length === 1) return typed(key, value, start, end);
  return null;
}

/** Tab indente, Shift+Tab désindente -- une ligne, ou tout un bloc sélectionné. */
function tab(shift: boolean, value: string, start: number, end: number): Edit {
  const multi = start !== end && value.slice(start, end).includes("\n");
  const from = lineStart(value, start);

  if (multi) {
    // Le bloc part du début de la PREMIÈRE ligne : indenter depuis le milieu
    // d'une ligne y laisserait quatre espaces au hasard.
    const lines = value.slice(from, end).split("\n");
    const insert = lines
      .map((line) => (shift ? dedentLine(line) : line === "" ? line : " ".repeat(INDENT) + line))
      .join("\n");
    return {
      from,
      to: end,
      insert,
      caret: from,
      caretEnd: from + insert.length,
    };
  }

  if (shift) {
    // La LIGNE se désindente, pas les espaces devant le curseur : c'est le geste
    // symétrique de Tab, et il marche où que soit le curseur dans la ligne.
    const to = lineEnd(value, from);
    const line = value.slice(from, to);
    const shorter = dedentLine(line);
    const removed = line.length - shorter.length;
    if (!removed) return { from: start, to: end, insert: "", caret: start };
    return {
      from,
      to,
      insert: shorter,
      caret: Math.max(from, start - removed),
    };
  }

  // Jusqu'au prochain multiple de quatre, et pas quatre à l'aveugle : sinon une
  // ligne déjà décalée de deux espaces reste décalée pour toujours.
  const width = INDENT - ((start - from) % INDENT);
  return {
    from: start,
    to: end,
    insert: " ".repeat(width),
    caret: start + width,
  };
}

/** Entrée recopie l'indentation, et ouvre un bloc entre deux accolades. */
function enter(value: string, start: number, end: number): Edit | null {
  const indent = indentOf(value, start);
  const before = value[start - 1];
  const after = value[end];

  if (before === "{") {
    const inner = indent + " ".repeat(INDENT);
    // Entre les deux accolades, le fermant descend sur sa propre ligne.
    const insert = after === "}" ? "\n" + inner + "\n" + indent : "\n" + inner;
    return { from: start, to: end, insert, caret: start + 1 + inner.length };
  }
  // Rien à recopier et rien à fermer : le navigateur fait mieux que nous, parce
  // qu'il garde sa pile d'annulation intacte.
  if (!indent && start === end) return null;
  return {
    from: start,
    to: end,
    insert: "\n" + indent,
    caret: start + 1 + indent.length,
  };
}

/** Backspace efface une paire vide d'un coup, et un niveau d'indentation d'un coup. */
function backspace(value: string, start: number, end: number): Edit | null {
  if (start !== end || start === 0) return null;

  const before = value[start - 1]!;
  if (PAIRS[before] && value[start] === PAIRS[before]) {
    return { from: start - 1, to: start + 1, insert: "", caret: start - 1 };
  }

  const head = value.slice(lineStart(value, start), start);
  if (head.length && /^ +$/.test(head)) {
    const width = ((head.length - 1) % INDENT) + 1;
    return { from: start - width, to: start, insert: "", caret: start - width };
  }
  return null;
}

/** Un caractère : survoler un fermant, encadrer une sélection, ou ouvrir une paire. */
function typed(key: string, value: string, start: number, end: number): Edit | null {
  // SURVOLER LE FERMANT, avant tout le reste : c'est ce qui fait que taper la
  // parenthèse fermante après une paire auto-fermée n'en donne pas deux.
  if (start === end && CLOSERS.has(key) && value[start] === key) {
    return { from: start, to: start, insert: "", caret: start + 1 };
  }

  // Une accolade fermante posée seule sur sa ligne se recale d'un niveau.
  if (key === "}" && start === end) {
    const from = lineStart(value, start);
    const head = value.slice(from, start);
    if (head.length && /^[ \t]+$/.test(head)) {
      const shorter = dedentLine(head);
      if (shorter.length !== head.length) {
        const insert = shorter + "}";
        return { from, to: end, insert, caret: from + insert.length };
      }
    }
  }

  const close = PAIRS[key];
  if (!close) return null;

  // ENCADRER PLUTÔT QUE REMPLACER : une sélection perdue parce qu'on a frôlé une
  // parenthèse est du travail perdu, et c'est le geste qu'on attend d'un éditeur.
  if (start !== end) {
    const inner = value.slice(start, end);
    return {
      from: start,
      to: end,
      insert: key + inner + close,
      caret: start + 1,
      caretEnd: start + 1 + inner.length,
    };
  }

  // LES DEUX REFUS QUI RENDENT LES GUILLEMETS VIVABLES. Sans le second,
  // « aujourd'hui » dans un commentaire donne « aujourd''hui ».
  if (isWord(value[start])) return null;
  if (QUOTES.has(key)) {
    const before = value[start - 1];
    if (isWord(before) || before === key) return null;
  }

  return { from: start, to: end, insert: key + close, caret: start + 1 };
}

// --- LES COMMANDES D'UN IDE ------------------------------------------------
//
// Les gestes qu'un habitué de CLion cherche en premier : commenter, dupliquer,
// supprimer, déplacer une ligne, compléter une instruction. Même contrat que
// `keyEdit` -- un texte, une sélection, et UN `Edit` en retour -- donc même
// `apply()` côté surface, donc la pile d'annulation et le diff CRDT sont
// gardés sans un `if` de plus.
//
// ⚠ `null` N'A PAS LE MÊME SENS ICI QUE DANS `keyEdit`, ET C'EST À SAVOIR.
// Pour `keyEdit`, `null` veut dire « le navigateur fait mieux » : on le laisse
// agir, exprès, parce qu'une frappe native est une entrée de plus dans la pile
// d'annulation. Pour `commandEdit`, `null` veut dire « rien à faire du tout »,
// et l'appelant `preventDefault()` QUAND MÊME -- sinon `Alt+Maj+↑` sur la
// première ligne étendrait la sélection du navigateur et abîmerait le bloc
// qu'on essaie justement de déplacer.
//
// TOUTE COMMANDE REND UNE SEULE PLAGE CONTIGUË, et ce n'est pas un hasard de
// mise en œuvre : `applyLocal()` (`lib/collab/document.ts`) dérive un préfixe
// et un suffixe communs pour émettre UN delete et UN insert. Une commande qui
// rendrait deux `Edit` ferait deux transactions Yjs par frappe et replierait
// les curseurs des coéquipiers à chaque fois.


/**
 * Les lignes ENTIÈRES que la sélection touche.
 *
 * LE ROGNAGE DU SAUT DE LIGNE FINAL EST LA PARTIE QUI COMPTE : une sélection
 * faite à la souris sur trois lignes finit au DÉBUT de la quatrième, et sans
 * ce `end - 1` on commenterait une ligne que l'étudiant n'a jamais choisie.
 */
function blockRange(value: string, start: number, end: number): { from: number; to: number } {
  const trimmed = end > start && end === lineStart(value, end) ? end - 1 : end;
  return { from: lineStart(value, start), to: lineEnd(value, trimmed) };
}

/** Le début et la fin d'une ligne, numérotée à partir de 1 comme la gouttière. */
export function lineSpan(value: string, line: number): { from: number; to: number } {
  const lines = value.split("\n");
  const wanted = Math.min(Math.max(line, 1), lines.length);
  let from = 0;
  for (let i = 0; i < wanted - 1; i++) from += lines[i]!.length + 1;
  return { from, to: from + lines[wanted - 1]!.length };
}

/**
 * Le numéro de ligne saisi, ou `null` si ce n'en est pas un.
 *
 * Un numéro hors du fichier est BORNÉ, pas refusé : taper 999 pour dire « la
 * fin » est un geste, pas une faute de frappe à sanctionner par un champ qui
 * ne fait rien.
 */
export function parseLine(text: string, lineCount: number): number | null {
  const trimmed = text.trim();
  if (!/^[0-9]+$/.test(trimmed)) return null;
  const n = Number(trimmed);
  if (n < 1) return null;
  return Math.min(n, lineCount);
}

/** Ce que la commande `id` doit faire, ou `null` s'il n'y a rien à faire. */
export function commandEdit(
  id: ShortcutId,
  value: string,
  start: number,
  end: number,
): Edit | null {
  if (id === "commentLine") return commentLines(value, start, end);
  if (id === "commentBlock") return commentBlock(value, start, end);
  if (id === "duplicate") return duplicate(value, start, end);
  if (id === "deleteLine") return deleteLine(value, start, end);
  if (id === "moveUp") return moveLines(value, start, end, -1);
  if (id === "moveDown") return moveLines(value, start, end, 1);
  if (id === "completeStatement") return completeStatement(value, start, end);
  return null;
}

/** Le `//` de tête d'une ligne, s'il y en a un : son indentation et sa position. */
const COMMENTED = /^([ \t]*)\/\//;

/**
 * Commenter, ou décommenter si TOUT est déjà commenté.
 *
 * « TOUT », et pas « la première ligne » : un bloc dont huit lignes sur neuf
 * sont commentées se fait COMMENTER en entier, ce qui est réversible du même
 * geste. L'inverse -- décommenter sur la foi de la première ligne -- laisserait
 * la neuvième commentée sans que personne ne le voie.
 */
function commentLines(value: string, start: number, end: number): Edit | null {
  const { from, to } = blockRange(value, start, end);
  const lines = value.slice(from, to).split("\n");

  // LES LIGNES VIDES NE COMPTENT POUR RIEN dans un bloc : ni pour la colonne,
  // ni pour décider du sens, ni à décommenter. Mais une ligne vide SEULE en
  // reçoit un, sinon la touche a l'air morte là où on vient d'ouvrir un bloc.
  const filled = lines.filter((line) => /\S/.test(line));
  const bodies = filled.length ? filled : lines;

  const uncomment = bodies.every((line) => COMMENTED.test(line));
  let insert: string;

  if (uncomment) {
    // ON RETIRE `//` PLUS AU PLUS UNE ESPACE. L'aller-retour est alors exact
    // pour tout ce que cette bascule produit, et un alignement délibéré
    // (`//  x`) garde son décalage au lieu d'être normalisé en douce.
    insert = lines
      .map((line) => {
        const m = COMMENTED.exec(line);
        if (!m) return line;
        const rest = line.slice(m[0].length);
        return m[1] + (rest.startsWith(" ") ? rest.slice(1) : rest);
      })
      .join("\n");
  } else {
    // La colonne est l'indentation la MOINS profonde du bloc : un `//` posé
    // au début de chaque ligne casserait l'escalier d'un bloc imbriqué.
    // ponytail: une longueur, pas une colonne visuelle. L'indentation de cet
    // éditeur est en espaces (`tab()` en insère), donc une tabulation est un
    // artefact de collage -- et sur un collage indenté aux tabulations le `//`
    // peut tomber un caractère à côté. Le jour où ça se voit, c'est ici.
    const column = Math.min(...bodies.map((line) => /^[ \t]*/.exec(line)![0].length));
    insert = lines
      .map((line) =>
        filled.length && !/\S/.test(line) ? line : line.slice(0, column) + "// " + line.slice(column),
      )
      .join("\n");
  }

  if (insert === value.slice(from, to)) return null;
  return selectionAfter(value, from, to, insert, start, end);
}

/**
 * `/* … *\/` autour de la sélection, ou son retrait.
 *
 * UN `*\/` AU MILIEU FAIT RETOMBER SUR LE COMMENTAIRE DE LIGNE, et ce n'est pas
 * une précaution théorique : C n'imbrique pas les commentaires de bloc, donc
 * encadrer fermerait au premier `*\/` rencontré et rendrait en silence du code
 * qui ne compile plus -- au moment précis où l'étudiant croit avoir neutralisé
 * un passage.
 */
function commentBlock(value: string, start: number, end: number): Edit | null {
  if (start === end) {
    // Rien de sélectionné : on pose la coquille et on met le curseur dedans.
    return { from: start, to: end, insert: "/*  */", caret: start + 3 };
  }
  const inner = value.slice(start, end);
  const trimmed = inner.trim();
  if (trimmed.startsWith("/*") && trimmed.endsWith("*/") && trimmed.length >= 4) {
    const opened = inner.indexOf("/*");
    const closed = inner.lastIndexOf("*/");
    const bare = inner.slice(0, opened) + inner.slice(opened + 2, closed) + inner.slice(closed + 2);
    return { from: start, to: end, insert: bare, caret: start, caretEnd: start + bare.length };
  }
  if (inner.slice(0, -2).includes("*/")) return commentLines(value, start, end);
  const insert = "/*" + inner + "*/";
  return { from: start, to: end, insert, caret: start, caretEnd: start + insert.length };
}

/**
 * Dupliquer, et les trois cas ne sont pas un raffinement.
 *
 * SANS LE CAS « LIGNES ENTIÈRES », sélectionner deux lignes et presser Ctrl+D
 * rend `ligne1\nligne2ligne1\nligne2` : la duplication en ligne recolle la
 * copie au milieu du texte au lieu de l'ajouter dessous.
 */
function duplicate(value: string, start: number, end: number): Edit | null {
  if (start === end) {
    // Curseur nu : la ligne descend d'un cran, MÊME COLONNE, aucune sélection.
    // C'est ce qui rend le geste répétable sans lâcher la touche.
    const { from, to } = blockRange(value, start, end);
    const line = value.slice(from, to);
    return { from: to, to, insert: "\n" + line, caret: start + line.length + 1 };
  }
  const whole = start === lineStart(value, start) && end === lineEnd(value, end);
  if (whole) {
    const block = value.slice(start, end);
    // LA COPIE EST SÉLECTIONNÉE, pas l'original : deux Ctrl+D donnent deux
    // lignes puis quatre, et taper remplace ce qu'on vient de créer.
    return { from: end, to: end, insert: "\n" + block, caret: end + 1, caretEnd: end + 1 + block.length };
  }
  const inner = value.slice(start, end);
  return { from: end, to: end, insert: inner, caret: end, caretEnd: end + inner.length };
}

/**
 * Supprimer la ou les lignes touchées.
 *
 * LE SAUT DE LIGNE PART AVEC, ET DU BON CÔTÉ : sur la dernière ligne du fichier
 * il n'y en a pas après, donc on prend CELUI D'AVANT. Le prendre après, ou pas
 * du tout, laisse une dernière ligne vide qui s'accumule à chaque suppression.
 */
function deleteLine(value: string, start: number, end: number): Edit | null {
  const { from, to } = blockRange(value, start, end);
  if (to < value.length) return { from, to: to + 1, insert: "", caret: from };
  if (from > 0) return { from: from - 1, to, insert: "", caret: from - 1 };
  if (!to) return null;
  return { from: 0, to, insert: "", caret: 0 };
}

/**
 * Monter ou descendre le bloc d'une ligne.
 *
 * LE CURSEUR ET LA SÉLECTION VOYAGENT AVEC LUI, inchangés, et c'est tout
 * l'intérêt : on tient le chord et le bloc se promène. Les recalculer à
 * l'arrivée -- ou pire, laisser le curseur derrière -- oblige à re-sélectionner
 * entre chaque pression, c'est-à-dire à ne jamais s'en servir.
 */
function moveLines(value: string, start: number, end: number, step: -1 | 1): Edit | null {
  const { from, to } = blockRange(value, start, end);
  const block = value.slice(from, to);

  if (step < 0) {
    if (from === 0) return null;
    const above = lineStart(value, from - 1);
    const moved = value.slice(above, from - 1);
    const shift = from - above;
    return {
      from: above,
      to,
      insert: block + "\n" + moved,
      caret: start - shift,
      caretEnd: end === start ? undefined : end - shift,
    };
  }

  if (to === value.length) return null;
  const below = lineEnd(value, to + 1);
  const moved = value.slice(to + 1, below);
  const shift = below - to;
  return {
    from,
    to: below,
    insert: moved + "\n" + block,
    caret: start + shift,
    caretEnd: end === start ? undefined : end + shift,
  };
}

/**
 * Le `;` qui manque, puis la ligne suivante déjà indentée.
 *
 * ⚠ LA LISTE DES EN-TÊTES DE CONTRÔLE EST CE QUI REND CE RACCOURCI SÛR. Sans
 * elle, `Ctrl+Maj+Entrée` sur `if (x)` écrit `if (x);` -- le point-virgule le
 * plus cher qu'un étudiant de première session puisse taper, parce que le code
 * compile, tourne, et fait le contraire de ce qu'il lit.
 */
const HEADS = /^(#|if\b|for\b|while\b|switch\b|else\b|do\b)/;

function completeStatement(value: string, start: number, end: number): Edit | null {
  const to = lineEnd(value, end);
  const from = lineStart(value, start);
  const line = value.slice(from, to);
  const body = line.trim();
  const needs = body.length > 0 && !/[;{},:]$/.test(body) && !HEADS.test(body);
  const indent = /^[ \t]*/.exec(line)![0];
  // Une ligne qui OUVRE un bloc fait descendre d'un niveau, comme Entrée.
  const inner = body.endsWith("{") ? indent + " ".repeat(INDENT) : indent;
  const insert = (needs ? ";" : "") + "\n" + inner;
  return { from: to, to, insert, caret: to + insert.length };
}

/**
 * Où va le curseur après une réécriture de bloc.
 *
 * Une sélection revient ENTIÈRE -- la convention que `tab()` utilise déjà pour
 * l'indentation d'un bloc, pour que commenter et indenter se ressemblent.
 *
 * Un curseur nu RESTE SUR SA LIGNE, décalé de ce que la réécriture a posé
 * devant lui et borné à cette ligne. Sans le bornage, décommenter une ligne
 * plus courte que le curseur ne l'était pousserait celui-ci sur la ligne
 * suivante, et la frappe d'après atterrirait ailleurs qu'où on regarde.
 */
function selectionAfter(
  value: string,
  from: number,
  to: number,
  insert: string,
  start: number,
  end: number,
): Edit {
  if (start !== end) {
    return { from, to, insert, caret: from, caretEnd: from + insert.length };
  }
  const was = value.slice(from, to).split("\n");
  const now = insert.split("\n");
  const row = value.slice(from, start).split("\n").length - 1;
  const column = start - from - was.slice(0, row).reduce((n, line) => n + line.length + 1, 0);
  const width = (now[row] ?? "").length;
  const moved = column + width - (was[row] ?? "").length;
  const head = now.slice(0, row).reduce((n, line) => n + line.length + 1, 0);
  return { from, to, insert, caret: from + head + Math.min(Math.max(moved, 0), width) };
}
