import { pack, type Answer } from "../state/quiz.svelte";
import type { Verdict } from "../api/types";

export type Mark = "right" | "wrong";

/**
 * The mark each question wears after a run. A question is only marked while the field
 * still holds the answer that was graded: retyping clears its mark rather than leaving a
 * verdict that no longer describes it. The server grades the whole quiz, so a run started
 * from one page marks the questions of the others too.
 *
 * The import goes this way round on purpose: only the lazily loaded panel reads this
 * module, and the reverse direction would pull it into the anonymous bundle.
 */
export function marksFor(
  verdict: Verdict | null | undefined,
  submitted: Record<string, string>,
  answers: Record<string, Answer>,
): Record<string, Mark> {
  if (!verdict || verdict.kind !== "quiz" || verdict.status !== "ok") return {};
  const wrong = new Set((verdict.wrong ?? []).map((one) => one.id));
  const marks: Record<string, Mark> = {};
  for (const [id, sent] of Object.entries(submitted)) {
    if (pack(answers[id] ?? "") !== sent) continue;
    marks[id] = wrong.has(id) ? "wrong" : "right";
  }
  return marks;
}
