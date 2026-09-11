// THE CLIENT-SIDE C CHECKER. It is not a compiler and must never pretend to be
// one: the judge is one click away and it is authoritative. What this buys is the
// round trip -- the faults you can see WITHOUT understanding the program, said
// while the student is still looking at the line, instead of after a queue slot,
// a container, and a gcc message that points at the line AFTER the mistake.
//
// A PURE FUNCTION: text in, OFFSETS out. No DOM, no fetch, and deliberately no
// line numbers -- `lib/collab/carets.ts` already turns an offset into a row and a
// column, and a second copy of that arithmetic would be a second one to fix.
//
// WHY NOT REUSE `highlight.ts`. That module is one regular expression returning
// HTML: no positions, no nesting stack, and it is one of the only two outputs in
// this application that reach `innerHTML`. Grafting a token stream onto it, for a
// need that is entirely positional, would touch the most sensitive file here to
// save twenty lines. The accepted cost is two grammars; what catches a drift is
// the `//`-inside-a-string trap, guarded on both sides.

export type Level = "error" | "hint";

export interface Issue {
  from: number;
  to: number;
  /** "error" is certain; "hint" is a heuristic, and its wording says so. */
  level: Level;
  /** Written for the student, in French, like every message in `verdict.ts`. */
  message: string;
}

/** Six is already more than anyone reads. */
const MAX_ISSUES = 6;

const OPENERS: Record<string, string> = { "(": ")", "[": "]", "{": "}" };
const CLOSERS: Record<string, string> = { ")": "(", "]": "[", "}": "{" };

interface Literal {
  from: number;
  text: string;
}

interface Scanned {
  /** The source with comment and literal CONTENTS replaced by spaces. */
  blanked: string;
  /** Every string literal, by the offset of its opening quote. */
  literals: Literal[];
  issues: Issue[];
}

/**
 * A LOST QUOTE OR COMMENT IS A HARD STOP, AND IT REPORTS ONE THING.
 *
 * Once the scanner no longer knows whether it is inside a literal, every
 * delimiter after it is a guess. `puts("salut);` alone would otherwise be three
 * messages -- the quote, the `(` it swallowed, and the `{` that then looks
 * unclosed -- for one typo. The bracket stack is dropped on purpose: it is the
 * same "fix the FIRST one" that governs `check()`.
 */
function derailed(chars: string[], literals: Literal[], issues: Issue[]): Scanned {
  return { blanked: chars.join(""), literals, issues };
}

/**
 * ONE PASS, AND IT PRODUCES THE GROUND EVERYTHING ELSE STANDS ON.
 *
 * Besides the five certain faults, it returns `blanked`: the same text, same
 * length, same newlines, with the inside of every comment and literal turned to
 * spaces. That is what makes the heuristics below both trivial and safe -- no
 * rule can be fooled by a `;`, a `{`, or a French apostrophe ("aujourd'hui") in
 * a comment, nor by the `//` in `printf("http://x")`.
 */
function scan(src: string): Scanned {
  const chars = src.split("");
  const literals: Literal[] = [];
  const issues: Issue[] = [];
  const stack: { at: number; ch: string }[] = [];

  const blank = (from: number, to: number) => {
    for (let k = from; k < to && k < chars.length; k++) if (chars[k] !== "\n") chars[k] = " ";
  };
  const lineEnd = (from: number) => {
    const nl = src.indexOf("\n", from);
    return nl < 0 ? src.length : nl;
  };

  let i = 0;
  while (i < src.length) {
    const c = src[i];

    if (c === "/" && src[i + 1] === "/") {
      // ponytail: a backslash at the end of a `//` line splices it into the next
      // one. Nobody writes that on purpose, and the cost of being wrong here is
      // one line of comment read as code.
      const end = lineEnd(i);
      blank(i, end);
      i = end;
      continue;
    }

    if (c === "/" && src[i + 1] === "*") {
      const end = src.indexOf("*/", i + 2);
      if (end < 0) {
        issues.push({
          from: i,
          to: i + 2,
          level: "error",
          message: "Ce commentaire /* n'est jamais fermé : tout ce qui suit est ignoré.",
        });
        blank(i, src.length);
        return derailed(chars, literals, issues);
      }
      blank(i, end + 2);
      i = end + 2;
      continue;
    }

    if (c === '"' || c === "'") {
      let j = i + 1;
      while (j < src.length && src[j] !== c && src[j] !== "\n") {
        if (src[j] === "\\") {
          if (j + 1 >= src.length || src[j + 1] === "\n") break;
          j += 2;
        } else {
          j++;
        }
      }
      if (j >= src.length || src[j] !== c) {
        issues.push({
          from: i,
          to: i + 1,
          level: "error",
          message:
            c === '"'
              ? 'Ce guillemet " n\'est jamais refermé sur cette ligne.'
              : "Cette apostrophe ' n'est jamais refermée sur cette ligne.",
        });
        blank(i, lineEnd(i));
        return derailed(chars, literals, issues);
      }
      if (c === '"') literals.push({ from: i, text: src.slice(i + 1, j) });
      blank(i, j + 1);
      i = j + 1;
      continue;
    }

    if (OPENERS[c]) {
      stack.push({ at: i, ch: c });
    } else if (CLOSERS[c]) {
      const top = stack.pop();
      if (!top) {
        issues.push({
          from: i,
          to: i + 1,
          level: "error",
          message: "« " + c + " » ne ferme aucune « " + CLOSERS[c] + " ».",
        });
      } else if (top.ch !== CLOSERS[c]) {
        issues.push({
          from: i,
          to: i + 1,
          level: "error",
          message: "« " + c + " » ferme une « " + top.ch + " » : les délimiteurs se croisent.",
        });
      }
    }
    i++;
  }

  // REPORTED AT THE OPENER, not at the end of the file. That is where the fix
  // goes, and it is exactly what gcc cannot tell you.
  for (const open of stack) {
    issues.push({
      from: open.at,
      to: open.at + 1,
      level: "error",
      message: "« " + open.ch + " » ouverte ici n'est jamais fermée.",
    });
  }

  return { blanked: chars.join(""), literals, issues };
}

/** Walks from an opening parenthesis to its match. Returns -1 if there is none. */
function matching(text: string, open: number): number {
  let depth = 0;
  for (let i = open; i < text.length; i++) {
    if (text[i] === "(") depth++;
    else if (text[i] === ")" && --depth === 0) return i;
  }
  return -1;
}

/**
 * `=` WHERE `==` WAS MEANT, AND THE DEPTH IS THE GUARD. `while ((c = getchar())
 * != EOF)` is an idiom this course teaches, and its `=` sits at depth two; only a
 * bare assignment directly in the condition is flagged.
 */
function assignmentInCondition(blanked: string, issues: Issue[]): void {
  for (const m of blanked.matchAll(/\b(?:if|while)\s*\(/g)) {
    const open = m.index + m[0].length - 1;
    let depth = 0;
    for (let i = open; i < blanked.length; i++) {
      const c = blanked[i];
      if (c === "(") {
        depth++;
      } else if (c === ")") {
        if (--depth === 0) break;
      } else if (c === "=" && depth === 1) {
        if (blanked[i + 1] === "=") {
          i++;
          continue;
        }
        if ("=!<>+-*/%&|^".indexOf(blanked[i - 1]) >= 0) continue;
        issues.push({
          from: i,
          to: i + 1,
          level: "hint",
          message: "« = » affecte une valeur ; pour comparer, il faut « == ».",
        });
      }
    }
  }
}

/**
 * `if (...);` -- the body that always runs. Only `if`: `for (...);` and
 * `while (...);` are legitimate empty loops.
 */
function emptyIfBody(blanked: string, issues: Issue[]): void {
  for (const m of blanked.matchAll(/\bif\s*\(/g)) {
    const close = matching(blanked, m.index + m[0].length - 1);
    if (close < 0) continue;
    const rest = blanked.slice(close + 1);
    const gap = rest.length - rest.replace(/^\s*/, "").length;
    if (rest[gap] !== ";") continue;
    issues.push({
      from: close + 1 + gap,
      to: close + 2 + gap,
      level: "hint",
      message: "Ce « ; » termine le if : le bloc qui suit s'exécute toujours.",
    });
  }
}

// `%%` is not a conversion. The letter decides whether an address is needed, so
// it is the only group captured.
const CONVERSION = /%(?:%|[-+ #0]*[0-9*]*(?:\.[0-9*]+)?(?:hh|h|ll|l|L|z|j|t)?(.))/g;

/**
 * `scanf` WITHOUT `&`. `%s` IS EXCLUDED, and that exclusion is what makes the
 * rule usable at all: `scanf("%s", nom)` into a char array is correct and
 * extremely common, and flagging it would discredit every other message on
 * screen. Same for a scanset. Anything that is not a bare identifier -- `&x`,
 * `tab[i]`, `p->champ` -- is left alone.
 */
function scanfWithoutAmpersand(blanked: string, literals: Literal[], issues: Issue[]): void {
  for (const m of blanked.matchAll(/\bscanf\s*\(/g)) {
    const open = m.index + m[0].length - 1;
    const close = matching(blanked, open);
    if (close < 0) continue;

    // Split on the commas of THIS call only.
    const args: { from: number; to: number }[] = [];
    let depth = 0;
    let start = open + 1;
    for (let i = open + 1; i <= close; i++) {
      const c = blanked[i];
      if (i === close) {
        args.push({ from: start, to: i });
        break;
      }
      if (c === "(" || c === "[") depth++;
      else if (c === ")" || c === "]") depth--;
      else if (c === "," && depth === 0) {
        args.push({ from: start, to: i });
        start = i + 1;
      }
    }
    if (args.length < 2) continue;

    const format = literals.find((l) => l.from >= args[0]!.from && l.from < args[0]!.to);
    if (!format) continue;

    let k = 1;
    for (const conv of format.text.matchAll(CONVERSION)) {
      const letter = conv[1];
      if (letter === undefined) continue; // `%%`
      if (k >= args.length) break;
      const arg = args[k++]!;
      if (letter === "s" || letter === "[") continue;
      const slice = blanked.slice(arg.from, arg.to);
      const name = slice.trim();
      if (!/^[A-Za-z_]\w*$/.test(name)) continue;
      issues.push({
        from: arg.from + slice.indexOf(name),
        to: arg.to,
        level: "hint",
        message: "Il manque peut-être « & » devant « " + name + " » dans scanf.",
      });
    }
  }
}

// A line ending on any of these is not finished, so nothing is missing.
const UNFINISHED = /[,;:{}\\?+\-*/%=<>&|!([]$/;
// A control header, a label, or a preprocessor directive takes no `;`.
const NO_SEMICOLON =
  /^\s*(?:#|\/\/|(?:if|else|for|while|switch|do|case|default|struct|union|enum|typedef)\b)/;
// The statement continues on the next line.
const CONTINUED = /^\s*[{})\].?:+\-*/%=<>&|,]/;

/**
 * THE MISSING `;` -- the most useful rule and the most dangerous one, because
 * only a compiler really knows. Every guard below exists to buy silence: a false
 * negative costs nothing, a false positive costs the credibility of the whole
 * panel. It runs on the blanked source, so a trailing comment is already gone.
 */
function missingSemicolon(blanked: string, issues: Issue[]): void {
  const lines = blanked.split("\n");
  let at = 0;
  for (let n = 0; n < lines.length; n++) {
    const line = lines[n]!;
    const offset = at;
    at += line.length + 1;

    const code = line.replace(/\s+$/, "");
    if (!code.trim()) continue;
    if (NO_SEMICOLON.test(code)) continue;
    if (UNFINISHED.test(code)) continue;
    // A label on its own line, and nothing else that looks like one.
    if (/^\s*[A-Za-z_]\w*\s*:\s*$/.test(code)) continue;
    // A line whose own brackets do not balance is half of a longer statement.
    let depth = 0;
    for (const c of code) {
      if (c === "(" || c === "[") depth++;
      else if (c === ")" || c === "]") depth--;
    }
    if (depth !== 0) continue;

    let next = n + 1;
    while (next < lines.length && !lines[next]!.trim()) next++;
    if (next < lines.length && CONTINUED.test(lines[next]!)) continue;

    issues.push({
      from: offset + code.length - 1,
      to: offset + code.length,
      level: "hint",
      message: "Il manque peut-être « ; » à la fin de cette ligne.",
    });
  }
}

/**
 * ONE CERTAIN FAULT SILENCES EVERY HEURISTIC, and that is not a detail. An
 * unclosed brace makes the split into statements meaningless, so the guesses
 * below would fill the panel with fiction at the exact moment the student is
 * least able to sort it out. Same principle as `OUTCOMES.compile_error`: fix the
 * FIRST one.
 */
export function check(src: string): Issue[] {
  const { blanked, literals, issues } = scan(src);
  if (!issues.length) {
    assignmentInCondition(blanked, issues);
    emptyIfBody(blanked, issues);
    scanfWithoutAmpersand(blanked, literals, issues);
    missingSemicolon(blanked, issues);
  }
  return issues.sort((a, b) => a.from - b.from).slice(0, MAX_ISSUES);
}

/**
 * La faute suivante après le curseur, en revenant à la première une fois la
 * dernière passée.
 *
 * SANS ÉTAT, ET C'EST LE POINT. Tenir un index « faute courante » dans le
 * composant obligerait à le remettre à zéro chaque fois que le contrôle
 * débouncé remplace la liste -- c'est-à-dire 600 ms après chaque frappe. Un
 * index périmé fait sauter F2 sur une faute qui n'existe plus, ou en saute une
 * qui vient d'apparaître. Ici la position du curseur EST l'état, et elle est
 * toujours à jour parce que c'est le navigateur qui la tient.
 */
export function nextIssue(issues: Issue[], caret: number): Issue | null {
  if (!issues.length) return null;
  const sorted = [...issues].sort((a, b) => a.from - b.from);
  return sorted.find((issue) => issue.from > caret) ?? sorted[0]!;
}
