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
