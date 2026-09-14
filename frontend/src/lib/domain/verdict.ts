import { UNITS } from "./labels";
import type { FailedCase, Verdict } from "../api/types";

export type StepState = "ok" | "ko" | "";

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
  titre: string;
  suite: string;
}

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
  link_error: {
    etapes: ["ko", "", ""],
    titre: "Ton code ne s'assemble pas avec les tests",
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

export const AFTER_FAILURE: Record<string, string> = {
  io: "Ouvre le cas qui échoue : il montre ce que ton programme a reçu et ce qu'il a affiché.",
  unity: "Le nom de chaque vérification décrit le cas qu'elle teste.",
  quiz: "Corrige les réponses ci-dessus, puis relance le test.",
};

export const CONTRACT =
  "On lit les NOMBRES de ta sortie, dans l'ordre ; le texte autour " +
  "est libre. Par exemple, « Aire = 42 cm2 » et « 42 » sont lus de " +
  "la même façon.";

const DIAGNOSTIC = /(^|\s)(error|erreur|warning|attention|note)\s*:/i;

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

export function caseClass(reason: string | undefined): string {
  const r = reason || "";
  if (/n'a pas terminé|interrompu/.test(r)) return "n'a pas fini";
  if (/débordé de la mémoire/.test(r)) return "débordement mémoire";
  if (/terminé anormalement/.test(r)) return "a planté";
  return "mauvaise sortie";
}

export const showsContract = (c: FailedCase): boolean =>
  caseClass(c.reason) === "mauvaise sortie" && !/mot attendu|mentionne/.test(c.reason || "");

export const caseInputs = (stdin: string | undefined): string[] =>
  (stdin || "")
    .split("\n")
    .map((v) => v.trim())
    .filter((v) => v !== "");

export interface Scope {
  titre: string;
  ids: string[];
}

export function restrictToScope(r: Verdict, scope: Scope): Verdict {
  const wrong = (r.wrong ?? []).filter((w) => scope.ids.indexOf(w.id) >= 0);
  return { ...r, total: scope.ids.length, passed: scope.ids.length - wrong.length, wrong };
}

export function estimatedWait(sec: number | undefined): string {
  if (!(sec && sec > 0)) return "";
  if (sec < 60) return ` (environ ${Math.ceil(sec / 5) * 5} s)`;
  return ` (environ ${Math.ceil(sec / 60)} min)`;
}

export const isJudgeFailure = (r: Verdict): boolean =>
  r.status === "error" && /juge/.test(r.message || "");

export function verdictHeadline(r: Verdict, scope: Scope | null): string {
  if (r.status !== "ok") return (OUTCOMES[r.status] ?? OUTCOMES.error!).titre;
  const shown = scope && r.kind === "quiz" ? restrictToScope(r, scope) : r;
  const frame = scope && r.kind === "quiz" ? " — " + scope.titre : "";
  return `${shown.passed ?? 0} / ${shown.total ?? 0} ${UNITS[r.kind] ?? "réussis"}${frame}`;
}
