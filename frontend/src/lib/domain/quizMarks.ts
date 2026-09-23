import { pack, type Answer } from "../state/quiz.svelte";
import type { Verdict } from "../api/types";

export type Mark = "right" | "wrong";

/**
 * The mark each question wears after a run, only while its field still holds the graded
 * answer. Only the lazy quiz panel imports this; importing it from quiz.svelte.ts would
 * pull it into the anonymous bundle.
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
