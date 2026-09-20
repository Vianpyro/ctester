import type { Verdict } from "../api/types";
import { type Answer, answered, keyOf, pack } from "./answer";

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
  exercise: string,
): Record<string, Mark> {
  if (!verdict || verdict.kind !== "quiz" || verdict.status !== "ok") return {};
  // The judge answers in question ids; the page keys answers by exercise and question,
  // because two quizzes may both call a question "q1".
  const wrong = new Map((verdict.wrong ?? []).map((w) => [keyOf(exercise, w.id), w]));
  const marks: Record<string, Mark> = {};
  for (const [key, sent] of Object.entries(submitted)) {
    if (!key.startsWith(exercise + "/") || pack(answers[key]) !== sent) continue;
    const bad = wrong.get(key);
    marks[key] = bad ? { state: "wrong", hint: bad.hint } : { state: "right" };
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

/**
 * How many of the page's exercises fit, found the way a person would: put the first one
 * down, then try adding the next. `attempt(n)` renders the first n and answers whether
 * they still fit; it may leave n on screen, so the caller sets the final count itself.
 * The first exercise always stays, fit or not -- a page with nothing on it is worse than
 * one that scrolls.
 */
export async function fillPage(
  count: number,
  attempt: (n: number) => Promise<boolean>,
): Promise<number> {
  if (count <= 0) return 0;
  let kept = 1;
  await attempt(1);
  while (kept < count && (await attempt(kept + 1))) kept++;
  return kept;
}

/** Types that draw their own controls instead of a scalar field; mirrors the widget map. */
const RICH = new Set(["choice", "bool", "multi", "match", "order", "cloze"]);

/** The default when nobody fixed a length, in characters. */
export const DEFAULT_SLOTS = 12;

/**
 * One width for every field on screen: the widest the sheet needs. The placeholder still
 * shows each answer's own length, so a hex field says two characters while sitting in a box
 * sized for eight bits -- a row of boxes that step up and down reads as an accident.
 */
export function slotsOnScreen(questions: { type: string; width: number }[]): number {
  let widest = 0;
  for (const q of questions) {
    if (RICH.has(q.type)) continue;
    widest = Math.max(widest, q.width > 0 ? q.width : DEFAULT_SLOTS);
  }
  return widest || DEFAULT_SLOTS;
}
