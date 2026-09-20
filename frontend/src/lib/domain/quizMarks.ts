import type { Verdict } from "../api/types";
import { type Answer, answered, pack } from "./answer";

export type MarkState = "right" | "wrong" | "unknown";

export interface Mark {
  state: MarkState;
  hint?: string;
}

/**
 * The mark each question carries after a run. A question is only marked when the answer on
 * screen is still the one that was graded: retyping clears its mark rather than leaving a
 * verdict that no longer describes the field. The server always grades the whole quiz, so a
 * run started from one page marks the others too.
 */
export function marksFor(
  verdict: Verdict | null | undefined,
  submitted: Record<string, string>,
  answers: Record<string, Answer>,
): Record<string, Mark> {
  if (!verdict || verdict.kind !== "quiz" || verdict.status !== "ok") return {};
  const wrong = new Map((verdict.wrong ?? []).map((w) => [w.id, w]));
  const marks: Record<string, Mark> = {};
  for (const [id, sent] of Object.entries(submitted)) {
    if (pack(answers[id]) !== sent) continue;
    const bad = wrong.get(id);
    marks[id] = bad ? { state: "wrong", hint: bad.hint } : { state: "right" };
  }
  return marks;
}

export interface PageStatus {
  answered: number;
  total: number;
  state: MarkState;
}

/** The counts one section tile shows: how much is filled in, and how the section was graded. */
export function pageStatus(
  ids: string[],
  answers: Record<string, Answer>,
  marks: Record<string, Mark>,
): PageStatus {
  let filled = 0;
  let right = 0;
  let bad = false;
  for (const id of ids) {
    if (answered(answers[id])) filled++;
    const mark = marks[id];
    if (mark?.state === "wrong") bad = true;
    else if (mark?.state === "right") right++;
  }
  const state: MarkState = bad
    ? "wrong"
    : right === ids.length && ids.length > 0
      ? "right"
      : "unknown";
  return { answered: filled, total: ids.length, state };
}

/** A section tile is narrow: keep the heading's stem, drop the description after it. */
export function sectionLabel(title: string): string {
  const stem = title.split(/\s[:—–-]\s/)[0]?.trim() || title.trim();
  return stem.length > 22 ? stem.slice(0, 21) + "…" : stem;
}

/** The two fields that place a question in a cell; the publisher sets both or neither. */
export interface Celled {
  id: string;
  row: string;
  col: string;
}

export interface QuizTable<T extends Celled> {
  cols: string[];
  rows: { label: string; cells: (T | null)[] }[];
}

/**
 * The table a section draws, or null when it is a plain list. Headers keep the order the
 * author wrote, so the page reads like the sheet they typed. A group only becomes a table
 * when every one of its questions carries a cell: publication refuses a half-filled grid,
 * and a page built from an older release must still render as a list.
 */
export function tableFor<T extends Celled>(questions: T[]): QuizTable<T> | null {
  if (!questions.length || !questions.every((q) => q.row && q.col)) return null;
  const cols: string[] = [];
  const rows: string[] = [];
  for (const q of questions) {
    if (!cols.includes(q.col)) cols.push(q.col);
    if (!rows.includes(q.row)) rows.push(q.row);
  }
  // Two headers and a single cell is a list wearing a table's clothes.
  if (cols.length < 2 && rows.length < 2) return null;
  const at = new Map(questions.map((q) => [q.row + "\u0000" + q.col, q]));
  return {
    cols,
    rows: rows.map((label) => ({
      label,
      cells: cols.map((col) => at.get(label + "\u0000" + col) ?? null),
    })),
  };
}
