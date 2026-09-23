import { TITLE } from "../config";
import { t } from "../i18n.svelte";
import type { Exercise } from "./catalog";

// Without a BOM, Visual Studio reads the file in the system code page and mangles accents.
export const UTF8_BOM = "﻿";

const NUM_RE = /-ex(\d+)$/;
const INCLUDE_RE = /^[ \t]*#[ \t]*include\b/;
const HEADER_RE = /^[ \t]*#[ \t]*include[ \t]*(<[^>]*>|"[^"]*")/;
const OPEN_RE = /^[ \t]*#[ \t]*(if|ifdef|ifndef)\b/;
const CLOSE_RE = /^[ \t]*#[ \t]*endif\b/;
const CRT_RE = /^[ \t]*#[ \t]*define[ \t]+_CRT_SECURE_NO_WARNINGS\b/;


const twoDigits = (n: number) => String(n).padStart(2, "0");

export function today(at: Date = new Date()): string {
  return (
    at.getFullYear() + "-" + twoDigits(at.getMonth() + 1) + "-" + twoDigits(at.getDate())
  );
}

export function numberOf(ex: Exercise, rank: number): number {
  const found = NUM_RE.exec(ex.id);
  return found ? Number(found[1]) : rank;
}

export function labelForNumbers(numbers: number[]): string {
  if (!numbers.length) return t("mainc.none");
  if (numbers.length === 1) return t("mainc.one", { n: numbers[0]! });
  const contiguous = numbers.every((n, i) => i === 0 || n === numbers[i - 1]! + 1);
  return contiguous
    ? t("mainc.range", { first: numbers[0]!, last: numbers[numbers.length - 1]! })
    : t("mainc.list", { list: numbers.join(", ") });
}

export interface Disassembled {
  includes: { key: string; line: string }[];
  body: string;
}

// Only top-level #includes are hoisted: one inside the student's #if belongs to that condition.
export function disassemble(code: string): Disassembled {
  const includes: Disassembled["includes"] = [];
  const lines: string[] = [];
  let depth = 0;
  for (const line of code.split(/\r?\n/)) {
    if (CLOSE_RE.test(line)) {
      depth = Math.max(0, depth - 1);
      lines.push(line);
      continue;
    }
    if (depth === 0 && INCLUDE_RE.test(line)) {
      const found = HEADER_RE.exec(line);
      includes.push({ key: found ? found[1]! : line.trim(), line: line.trim() });
      continue;
    }
    if (depth === 0 && CRT_RE.test(line)) continue;
    if (OPEN_RE.test(line)) depth += 1;
    lines.push(line);
  }
  return { includes, body: lines.join("\n") };
}

export const trim = (text: string): string =>
  text
    .replace(/^(?:[ \t]*\r?\n)+/, "")
    .replace(/\s+$/, "")
    .replace(/\n(?:[ \t]*\n){2,}/g, "\n\n");

export function codeOf(ex: Exercise, sources: Record<string, string> | undefined): string {
  const files = ex.files && ex.files.length ? ex.files : [{ name: "submission.c" }];
  const pieces: string[] = [];
  for (const file of files) {
    const text = sources?.[file.name];
    if (typeof text !== "string" || !text.trim()) continue;
    pieces.push(files.length > 1 ? "/* " + file.name + " */\n" + text : text);
  }
  return pieces.join("\n\n");
}

function header(name: string, group: string, numbers: number[], first: number, at?: Date): string {
  return [
    "/*",
    t("mainc.file"),
    t("mainc.author", { name }),
    t("mainc.date", { date: today(at) }),
    t("mainc.description", { what: labelForNumbers(numbers) + " — " + group + " — " + TITLE }),
    "*/",
    "/* *******************************************************",
    t("mainc.preprocessor"),
    "******************************************************* */",
    "#define _CRT_SECURE_NO_WARNINGS",
    t("mainc.choose"),
    "#define exercice " + first,
  ].join("\n");
}

export interface Built {
  text: string;
  empty: number[];
  total: number;
}

export function build(
  exercises: Exercise[],
  sources: Record<string, Record<string, string> | undefined>,
  name: string,
  group: string,
  at?: Date,
): Built {
  const includes: { key: string; line: string }[] = [];
  const blocks: string[] = [];
  const numbers: number[] = [];
  const empty: number[] = [];
  let first: number | null = null;
  exercises.forEach((ex, rank) => {
    const number = numberOf(ex, rank + 1);
    numbers.push(number);
    const code = codeOf(ex, sources[ex.id]);
    const title = t("mainc.block", { n: number, name: ex.short || ex.id });
    if (!code) {
      empty.push(number);
      blocks.push(title + "\n#if exercice == " + number + "\n" + t("mainc.no_code") + "\n#endif");
      return;
    }
    if (first === null) first = number;
    const piece = disassemble(code);
    for (const inc of piece.includes) {
      if (!includes.some((seen) => seen.key === inc.key)) includes.push(inc);
    }
    blocks.push(title + "\n#if exercice == " + number + "\n" + trim(piece.body) + "\n#endif");
  });
  const opening = first === null ? (numbers[0] === undefined ? 1 : numbers[0]) : first;
  const text =
    [
      header(name, group, numbers, opening, at),
      includes.map((inc) => inc.line).join("\n"),
      blocks.join("\n\n"),
    ]
      .filter(Boolean)
      .join("\n\n") + "\n";
  return { text, empty: empty, total: exercises.length };
}
