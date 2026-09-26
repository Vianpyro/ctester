import type { ShortcutId } from "./shortcuts";

export interface Edit {
  from: number;
  to: number;
  insert: string;
  caret: number;
  caretEnd?: number;
}

export const INDENT = 4;

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

const lineStart = (value: string, pos: number): number => value.lastIndexOf("\n", pos - 1) + 1;

function lineEnd(value: string, pos: number): number {
  const nl = value.indexOf("\n", pos);
  return nl === -1 ? value.length : nl;
}

function dedentLine(line: string): string {
  if (line.startsWith("\t")) return line.slice(1);
  const m = /^ {1,4}/.exec(line);
  return m ? line.slice(m[0].length) : line;
}

function indentOf(value: string, pos: number): string {
  const head = value.slice(lineStart(value, pos), pos);
  return /^[ \t]*/.exec(head)![0];
}

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

function tab(shift: boolean, value: string, start: number, end: number): Edit {
  const multi = start !== end && value.slice(start, end).includes("\n");
  const from = lineStart(value, start);

  if (multi) {
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

  const width = INDENT - ((start - from) % INDENT);
  return {
    from: start,
    to: end,
    insert: " ".repeat(width),
    caret: start + width,
  };
}

function enter(value: string, start: number, end: number): Edit | null {
  const indent = indentOf(value, start);
  const before = value[start - 1];
  const after = value[end];

  if (before === "{") {
    const inner = indent + " ".repeat(INDENT);
    const insert = after === "}" ? "\n" + inner + "\n" + indent : "\n" + inner;
    return { from: start, to: end, insert, caret: start + 1 + inner.length };
  }
  if (!indent && start === end) return null;
  return {
    from: start,
    to: end,
    insert: "\n" + indent,
    caret: start + 1 + indent.length,
  };
}

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

function typed(key: string, value: string, start: number, end: number): Edit | null {
  if (start === end && CLOSERS.has(key) && value[start] === key) {
    return { from: start, to: start, insert: "", caret: start + 1 };
  }

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

  if (isWord(value[start])) return null;
  if (QUOTES.has(key)) {
    const before = value[start - 1];
    // No pair after a letter, so apostrophes in French comments stay single.
    if (isWord(before) || before === key) return null;
  }

  return { from: start, to: end, insert: key + close, caret: start + 1 };
}

function blockRange(value: string, start: number, end: number): { from: number; to: number } {
  const trimmed = end > start && end === lineStart(value, end) ? end - 1 : end;
  return { from: lineStart(value, start), to: lineEnd(value, trimmed) };
}

export function lineSpan(value: string, line: number): { from: number; to: number } {
  const lines = value.split("\n");
  const wanted = Math.min(Math.max(line, 1), lines.length);
  let from = 0;
  for (let i = 0; i < wanted - 1; i++) from += lines[i]!.length + 1;
  return { from, to: from + lines[wanted - 1]!.length };
}

export function parseLine(text: string, lineCount: number): number | null {
  const trimmed = text.trim();
  if (!/^[0-9]+$/.test(trimmed)) return null;
  const n = Number(trimmed);
  if (n < 1) return null;
  return Math.min(n, lineCount);
}

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

const COMMENTED = /^([ \t]*)\/\//;

function commentLines(value: string, start: number, end: number): Edit | null {
  const { from, to } = blockRange(value, start, end);
  const lines = value.slice(from, to).split("\n");

  const filled = lines.filter((line) => /\S/.test(line));
  const bodies = filled.length ? filled : lines;

  const uncomment = bodies.every((line) => COMMENTED.test(line));
  let insert: string;

  if (uncomment) {
    insert = lines
      .map((line) => {
        const m = COMMENTED.exec(line);
        if (!m) return line;
        const rest = line.slice(m[0].length);
        return m[1] + (rest.startsWith(" ") ? rest.slice(1) : rest);
      })
      .join("\n");
  } else {
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

function commentBlock(value: string, start: number, end: number): Edit | null {
  if (start === end) {
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

function duplicate(value: string, start: number, end: number): Edit | null {
  if (start === end) {
    const { from, to } = blockRange(value, start, end);
    const line = value.slice(from, to);
    return { from: to, to, insert: "\n" + line, caret: start + line.length + 1 };
  }
  const whole = start === lineStart(value, start) && end === lineEnd(value, end);
  if (whole) {
    const block = value.slice(start, end);
    return { from: end, to: end, insert: "\n" + block, caret: end + 1, caretEnd: end + 1 + block.length };
  }
  const inner = value.slice(start, end);
  return { from: end, to: end, insert: inner, caret: end, caretEnd: end + inner.length };
}

function deleteLine(value: string, start: number, end: number): Edit | null {
  const { from, to } = blockRange(value, start, end);
  if (to < value.length) return { from, to: to + 1, insert: "", caret: from };
  if (from > 0) return { from: from - 1, to, insert: "", caret: from - 1 };
  if (!to) return null;
  return { from: 0, to, insert: "", caret: 0 };
}

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

const HEADS = /^(#|if\b|for\b|while\b|switch\b|else\b|do\b)/;

function completeStatement(value: string, start: number, end: number): Edit | null {
  const to = lineEnd(value, end);
  const from = lineStart(value, start);
  const line = value.slice(from, to);
  const body = line.trim();
  const needs = body.length > 0 && !/[;{},:]$/.test(body) && !HEADS.test(body);
  const indent = /^[ \t]*/.exec(line)![0];
  const inner = body.endsWith("{") ? indent + " ".repeat(INDENT) : indent;
  const insert = (needs ? ";" : "") + "\n" + inner;
  return { from: to, to, insert, caret: to + insert.length };
}

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
