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
