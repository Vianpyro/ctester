// WHAT A VERDICT MEANS FOR THE STUDENT. Pure functions and tables: where it
// broke, how to say so in one line, and what to do next. The components render
// this; none of them decides any of it.
//
// TWO CHANNELS, AND THEY MUST NEVER BE CONFUSED. The VERDICT talks about the
// student's code; the SYSTEM banner talks about the service. A single red box
// used to serve both -- "your file does not compile" and "the server is
// unreachable" looked identical, and a beginner concludes they broke something.
// Of the seventeen red messages this page once showed, four were a verdict.
// `lib/state/system.svelte.ts` is the other channel.

import { UNITS } from "./labels";
import type { FailedCase, Verdict } from "../api/types";

/** "ok" passed, "ko" failed, "" not reached. */
export type StepState = "ok" | "ko" | "";

/**
 * THE THREE STAGES A BEGINNER MUST LEARN TO TELL APART. The server always knows
 * which one broke, and the page used to throw that away. Naming the stage NOT
 * REACHED is what answers "did my program even run?".
 *
 * AGREEMENT FOLLOWS THE STAGE: "Tests pas atteinte" is gibberish. The first two
 * are feminine singular, the third masculine plural.
 */
export const STEPS: [string, "f" | "mp"][] = [
  ["Compilation", "f"],
  ["Exécution", "f"],
  ["Tests", "mp"],
];

export const STEP_STATE: Record<"f" | "mp", Record<string, string>> = {
  f: { ok: "réussie", ko: "échouée", "": "pas atteinte" },
  mp: { ok: "réussis", ko: "échoués", "": "pas atteints" },
};

export interface Outcome {
  etapes: [StepState, StepState, StepState];
  /** SHORT. It carries the colour and it is what gets announced. */
  titre: string;
  /** The next action. Always exactly one. */
  suite: string;
}

/**
 * THE EXPLANATION IS NOT HERE: that is the server's `message`, written for the
 * student. Copying it here would make two places to fix, one of which would go
 * stale silently.
 */
export const OUTCOMES: Record<string, Outcome> = {
  forbidden_include: {
    etapes: ["ko", "", ""],
    titre: "Un #include n'est pas autorisé",
    suite: "Retire cette ligne, puis relance le test.",
  },
  compile_error: {
    etapes: ["ko", "", ""],
    titre: "Ton fichier ne compile pas.",
    suite: "Corrige la PREMIÈRE erreur : les suivantes en découlent souvent.",
  },
  compile_timeout: {
    etapes: ["ko", "", ""],
    titre: "La compilation a été trop longue",
    suite: "Réessaie. Si ça recommence, préviens ton enseignant.",
  },
  // "Compilation failed" rather than a fourth "Linking" stage: gcc does both in
  // one command in this course, and adding a concept for a single state would
  // cost more than it earns.
  link_error: {
    etapes: ["ko", "", ""],
    titre: "Ton code ne s'assemble pas avec les tests",
    // THE ACTION ADDS, IT DOES NOT REPEAT. The server's message says what to
    // check; what a beginner lacks is HOW to go about it.
    suite: "Compare ta signature avec celle de l’énoncé, caractère par caractère.",
  },
  memory_error: {
    etapes: ["ok", "ko", ""],
    titre: "Ton programme sort de la mémoire qu'il a réservée",
    suite: "Revois tes conditions de boucle (< et non <=) et la taille que tu réserves.",
  },
  timeout: {
    etapes: ["ok", "ko", ""],
    titre: "Ton programme ne s'est pas arrêté",
    suite: "Vérifie tes conditions de boucle et le nombre de valeurs que tu lis.",
  },
  error: {
    etapes: ["ok", "ko", ""],
    titre: "Ton programme s'est arrêté avant la fin",
    suite:
      "Plantage probable : indice hors des bornes, pointeur invalide, ou chaîne sans son terminateur.",
  },
};

/**
 * WHAT IS SAID AFTER A TEST FAILURE, by mode. The judge ran the program: what is
 * left is no longer making it run, it is reading what it produced.
 */
export const AFTER_FAILURE: Record<string, string> = {
  io: "Ouvre le cas qui échoue : il montre ce que ton programme a reçu et ce qu'il a affiché.",
  unity: "Le nom de chaque vérification décrit le cas qu'elle teste.",
  quiz: "Corrige les réponses ci-dessus, puis relance le test.",
};

/**
 * THE GRADING CONTRACT, WRITTEN OUT. The judge is MUCH more permissive than the
 * student thinks -- any text around the expected values is accepted -- and
 * nobody told them, so they spent time guessing a format that was never imposed.
 *
 * This reveals no answer: it says HOW the comparison works, not WHAT it compares
 * against. THE EXAMPLE IS ALWAYS THE SAME across every exercise, and carries a
 * value that is nobody's actual answer -- one that varied with the exercise would
 * read as a hint.
 */
export const CONTRACT =
  "On lit les NOMBRES de ta sortie, dans l'ordre ; le texte autour " +
  "est libre. Par exemple, « Aire = 42 cm2 » et « 42 » sont lus de " +
  "la même façon.";

const DIAGNOSTIC = /(^|\s)(error|erreur|warning|attention|note)\s*:/i;

/**
 * THE FIRST ERROR, NOT THE LAST. In C, errors cascade: one missing `;` produces
 * six, five of which do not really exist. The raw output scrolls, and what a
 * beginner reads is the BOTTOM -- so the most derived one, which matches nothing
 * in their code.
 *
 * What FOLLOWS the error line up to the next diagnostic is kept: that is the
 * source excerpt and the `^` cursor, which show the exact spot.
 */
export function firstError(output: string | undefined): string | null {
  const lines = (output || "").split("\n");
  const start = lines.findIndex((l) => /(^|\s)(error|erreur)\s*:/i.test(l));
  if (start < 0) return null;
  let end = start + 1;
  while (end < lines.length && !DIAGNOSTIC.test(lines[end]!)) end++;
  return lines
    .slice(start, end)
    .join("\n")
    .replace(/\s+$/, "");
}

/**
 * THE ERROR CLASS, drawn from the reason the server wrote. A summary that
 * repeated the whole sentence did not scan: with three cases folded, one could
 * not tell at a glance whether the program had crashed or simply miscalculated.
 */
export function caseClass(reason: string | undefined): string {
  const r = reason || "";
  if (/n'a pas terminé|interrompu/.test(r)) return "n'a pas fini";
  if (/débordé de la mémoire/.test(r)) return "débordement mémoire";
  if (/terminé anormalement/.test(r)) return "a planté";
  return "mauvaise sortie";
}

/**
 * The contract only makes sense for a VALUE comparison: a program that crashed,
 * or a case looking for a word, is not fixed by reformatting its output.
 */
export const showsContract = (c: FailedCase): boolean =>
  caseClass(c.reason) === "mauvaise sortie" && !/mot attendu|mentionne/.test(c.reason || "");

/**
 * The INPUTS as the program receives them, one per line. "stdin" means nothing
 * to a beginner; "ton programme reçoit 12 puis 7" describes exactly what its two
 * scanf calls do.
 */
export const caseInputs = (stdin: string | undefined): string[] =>
  (stdin || "")
    .split("\n")
    .map((v) => v.trim())
    .filter((v) => v !== "");

/** The ids of one displayed quiz page, or null for the whole lab. */
export interface Scope {
  titre: string;
  ids: string[];
}

/**
 * "Tester l'exercice" changes NOTHING about grading: the judge keeps the
 * reference solution and grades the whole quiz, and it is from that COMPLETE
 * verdict that the API derives "solved". Only the READING is restricted -- other
 * exercises' questions leave the count and the list. A correct exercise therefore
 * cannot validate a half-filled lab.
 */
export function restrictToScope(r: Verdict, scope: Scope): Verdict {
  const wrong = (r.wrong ?? []).filter((w) => scope.ids.indexOf(w.id) >= 0);
  return { ...r, total: scope.ids.length, passed: scope.ids.length - wrong.length, wrong };
}

/**
 * THE ETA COMES FROM THE SERVER (`eta`, in seconds): only it knows what each
 * exercise costs and what is ahead of it. This only puts it into French. An
 * older API, or an `eta` of 0, returns nothing rather than inventing a number.
 */
export function estimatedWait(sec: number | undefined): string {
  if (!(sec && sec > 0)) return "";
  if (sec < 60) return ` (environ ${Math.ceil(sec / 5) * 5} s)`;
  return ` (environ ${Math.ceil(sec / 60)} min)`;
}

/**
 * A JUDGE FAILURE IS NOT A VERDICT. `error` covers two very different things
 * server-side: a student program crashing (steps to show) and an internal error
 * ("Erreur interne du juge"), which is not about the code and has no business in
 * the verdict channel.
 */
export const isJudgeFailure = (r: Verdict): boolean =>
  r.status === "error" && /juge/.test(r.message || "");

/**
 * THE HEADLINE A VERDICT GETS. One function, two callers: the component that
 * renders it, and the state that keeps it to recall at the top of a discussion
 * thread. Two copies would eventually quote a different sentence than the one on
 * screen.
 *
 * THE COUNT KEEPS THE LARGE TYPE, a state's title no longer has it: "3 / 4" reads
 * at a glance and deserves it, where a two-hundred-character sentence at 2.1rem
 * used to crush the whole result area.
 */
export function verdictHeadline(r: Verdict, scope: Scope | null): string {
  if (r.status !== "ok") return (OUTCOMES[r.status] ?? OUTCOMES.error!).titre;
  const shown = scope && r.kind === "quiz" ? restrictToScope(r, scope) : r;
  const frame = scope && r.kind === "quiz" ? " — " + scope.titre : "";
  return `${shown.passed ?? 0} / ${shown.total ?? 0} ${UNITS[r.kind] ?? "réussis"}${frame}`;
}
