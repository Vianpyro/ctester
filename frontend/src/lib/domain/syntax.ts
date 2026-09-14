export type Level = "error" | "hint";

export interface Issue {
  from: number;
  to: number;
  level: Level;
  message: string;
}

const MAX_ISSUES = 6;

const OPENERS: Record<string, string> = { "(": ")", "[": "]", "{": "}" };
const CLOSERS: Record<string, string> = { ")": "(", "]": "[", "}": "{" };

interface Literal {
  from: number;
  text: string;
}

interface Scanned {
  blanked: string;
  literals: Literal[];
  issues: Issue[];
}

function derailed(chars: string[], literals: Literal[], issues: Issue[]): Scanned {
  return { blanked: chars.join(""), literals, issues };
}

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

function matching(text: string, open: number): number {
  let depth = 0;
  for (let i = open; i < text.length; i++) {
    if (text[i] === "(") depth++;
    else if (text[i] === ")" && --depth === 0) return i;
  }
  return -1;
}

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

const CONVERSION = /%(?:%|[-+ #0]*[0-9*]*(?:\.[0-9*]+)?(?:hh|h|ll|l|L|z|j|t)?(.))/g;

function scanfWithoutAmpersand(blanked: string, literals: Literal[], issues: Issue[]): void {
  for (const m of blanked.matchAll(/\bscanf\s*\(/g)) {
    const open = m.index + m[0].length - 1;
    const close = matching(blanked, open);
    if (close < 0) continue;

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
      if (letter === undefined) continue;
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

const UNFINISHED = /[,;:{}\\?+\-*/%=<>&|!([]$/;
const NO_SEMICOLON =
  /^\s*(?:#|\/\/|(?:if|else|for|while|switch|do|case|default|struct|union|enum|typedef)\b)/;
const CONTINUED = /^\s*[{})\].?:+\-*/%=<>&|,]/;

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
    if (/^\s*[A-Za-z_]\w*\s*:\s*$/.test(code)) continue;
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

export function check(src: string): Issue[] {
  // A certain error silences every heuristic: guesses on broken code only add noise.
  const { blanked, literals, issues } = scan(src);
  if (!issues.length) {
    assignmentInCondition(blanked, issues);
    emptyIfBody(blanked, issues);
    scanfWithoutAmpersand(blanked, literals, issues);
    missingSemicolon(blanked, issues);
  }
  return issues.sort((a, b) => a.from - b.from).slice(0, MAX_ISSUES);
}

export function nextIssue(issues: Issue[], caret: number): Issue | null {
  if (!issues.length) return null;
  const sorted = [...issues].sort((a, b) => a.from - b.from);
  return sorted.find((issue) => issue.from > caret) ?? sorted[0]!;
}
