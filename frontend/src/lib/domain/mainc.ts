// EXPORTING A LAB AS A SINGLE `main.c`, in the hand-in format: a
// `#define exercice N` at the top choosing the compiled exercise, one
// `#if exercice == N ... #endif` per exercise, and `#include` directives hoisted
// once above everything. This is the format the instructor hands out and expects
// back; CTester keeps one draft per exercise, and without this the student
// copy-pastes eight times by hand the night before the deadline.
//
// PURE, AND THAT IS WHY IT IS HERE. The produced TEXT is what matters and it is
// tested directly -- no click, no blob, no DOM.

import type { Exercise } from "./catalog";

/**
 * THE FILE SHIPS IN UTF-8 WITH ITS BYTE ORDER MARK. Without it, Visual Studio
 * reads a header-less file in the system code page (cp1252 on the lab's Windows
 * machines) and every accented character in the comments -- the student's own,
 * not ours -- turns to gibberish on open. gcc and CLion skip the mark silently.
 */
export const UTF8_BOM = "﻿";

const NUM_RE = /-ex(\d+)$/;
const INCLUDE_RE = /^[ \t]*#[ \t]*include\b/;
// THE INCLUDED HEADER, NOT THE WHOLE LINE. This is the deduplication key:
// `#include <stdio.h>  // pour printf` and `#include <stdio.h>` are the SAME
// include, and keeping both because a student commented theirs would defeat
// exactly what the button promises.
const HEADER_RE = /^[ \t]*#[ \t]*include[ \t]*(<[^>]*>|"[^"]*")/;
const OPEN_RE = /^[ \t]*#[ \t]*(if|ifdef|ifndef)\b/;
const CLOSE_RE = /^[ \t]*#[ \t]*endif\b/;
const CRT_RE = /^[ \t]*#[ \t]*define[ \t]+_CRT_SECURE_NO_WARNINGS\b/;

const NO_CODE =
  "    /* Aucun code enregistré pour cet exercice dans CTester :\n" +
  "       rien n'y a été écrit, ou le brouillon est resté sur un autre poste\n" +
  "       parce qu'il n'était pas connecté. */";

const twoDigits = (n: number) => String(n).padStart(2, "0");

/**
 * THE READER'S DATE, NOT UTC'S. `toISOString()` in the evening in Montreal dates
 * the file to the next day, and a hand-in dated one day ahead is exactly the kind
 * of detail that comes up out loud.
 */
export function today(at: Date = new Date()): string {
  return (
    at.getFullYear() + "-" + twoDigits(at.getMonth() + 1) + "-" + twoDigits(at.getDate())
  );
}

/**
 * THE NUMBER COMES FROM THE ID, not from the rank: `tp2-ex0` is the preamble and
 * it must stay the statement's 0, or the whole file shifts by one compared to
 * what the instructor reads. The rank is only a safety net for an id that would
 * not end in `-exN`.
 */
export function numberOf(ex: Exercise, rank: number): number {
  const found = NUM_RE.exec(ex.id);
  return found ? Number(found[1]) : rank;
}

export function labelForNumbers(numbers: number[]): string {
  if (!numbers.length) return "Aucun exercice";
  if (numbers.length === 1) return "Exercice " + numbers[0];
  const contiguous = numbers.every((n, i) => i === 0 || n === numbers[i - 1]! + 1);
  return contiguous
    ? "Exercices " + numbers[0] + " à " + numbers[numbers.length - 1]
    : "Exercices " + numbers.join(", ");
}

export interface Disassembled {
  includes: { cle: string; ligne: string }[];
  corps: string;
}

/**
 * SEPARATING WHAT GETS HOISTED FROM WHAT STAYS.
 *
 * ONLY AT THE TOP LEVEL, AND THAT IS THE SUBTLETY. A `#include` already inside a
 * student `#if` is there FOR that condition: hoisting it would make it
 * unconditional and change the meaning of their code. So conditional nesting
 * depth is counted instead of scanning the text blindly.
 *
 * `#define` directives STAY where they are: two exercises in the same lab
 * commonly define the same constants (`DIMANCHE`, `LUNDI`, ...) and it is
 * precisely the `#if` that keeps them from clashing. Only
 * `_CRT_SECURE_NO_WARNINGS` leaves, because the file already sets it at the top.
 */
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
      // The LINE is kept as-is -- its comment belongs to the student -- but it is
      // the header that identifies the duplicate.
      const found = HEADER_RE.exec(line);
      includes.push({ cle: found ? found[1]! : line.trim(), ligne: line.trim() });
      continue;
    }
    if (depth === 0 && CRT_RE.test(line)) continue;
    if (OPEN_RE.test(line)) depth += 1;
    lines.push(line);
  }
  return { includes, corps: lines.join("\n") };
}

/**
 * THE HOLE INCLUDES LEAVE BEHIND. Removing three lines from a header block leaves
 * three blank lines in their place, and the handed-in file opens on an accordion
 * of blanks. Runs of blank lines fold to one, along with leading and trailing.
 */
export const trim = (text: string): string =>
  text
    .replace(/^(?:[ \t]*\r?\n)+/, "")
    .replace(/\s+$/, "")
    .replace(/\n(?:[ \t]*\n){2,}/g, "\n\n");

/**
 * The code for ONE exercise, in its declared files' order. An "io" exercise fits
 * in a single file and that is the normal case; the day it has two, they get glued
 * back with their name as a comment rather than silently dropped.
 */
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
    "Fichier : main.c",
    "Auteur : " + name,
    "Date : " + today(at),
    "Description : " + labelForNumbers(numbers) + " — " + group + " — TCH009",
    "*/",
    "/* *******************************************************",
    "* Commande de preprocesseur",
    "******************************************************* */",
    "#define _CRT_SECURE_NO_WARNINGS",
    "/* Ce numéro choisit l'exercice qui sera compilé : change-le pour tester",
    "   un autre exercice de ce fichier. */",
    "#define exercice " + first,
  ].join("\n");
}

export interface Built {
  texte: string;
  /** The numbers of the exercises with no code at all. */
  vides: number[];
  total: number;
}

/** The whole file, from the catalog and the drafts. */
export function build(
  exercises: Exercise[],
  sources: Record<string, Record<string, string> | undefined>,
  name: string,
  group: string,
  at?: Date,
): Built {
  const includes: { cle: string; ligne: string }[] = [];
  const blocks: string[] = [];
  const numbers: number[] = [];
  const empty: number[] = [];
  // `null`, AND ESPECIALLY NOT `0`. Lab 2's preamble is exercise NUMBER 0: with a
  // counter starting at zero, `if (!first)` would take it for "nothing found
  // yet" and the file would open on the following block.
  let first: number | null = null;
  exercises.forEach((ex, rank) => {
    const number = numberOf(ex, rank + 1);
    numbers.push(number);
    const code = codeOf(ex, sources[ex.id]);
    const title = "/* Exercice " + number + " — " + (ex.short || ex.id) + " */";
    if (!code) {
      empty.push(number);
      blocks.push(title + "\n#if exercice == " + number + "\n" + NO_CODE + "\n#endif");
      return;
    }
    // THE FIRST EXERCISE THAT HAS CODE, not simply the first one: a file that
    // opens on an empty block does not compile, and the student concludes the
    // export is broken.
    if (first === null) first = number;
    const piece = disassemble(code);
    for (const inc of piece.includes) {
      if (!includes.some((seen) => seen.cle === inc.cle)) includes.push(inc);
    }
    blocks.push(title + "\n#if exercice == " + number + "\n" + trim(piece.corps) + "\n#endif");
  });
  const opening = first === null ? (numbers[0] === undefined ? 1 : numbers[0]) : first;
  const texte =
    [
      header(name, group, numbers, opening, at),
      includes.map((inc) => inc.ligne).join("\n"),
      blocks.join("\n\n"),
    ]
      .filter(Boolean)
      .join("\n\n") + "\n";
  return { texte, vides: empty, total: exercises.length };
}
