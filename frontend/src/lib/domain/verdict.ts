import { unitsOf } from "./labels";
import { i18n, t, type Params } from "../i18n.svelte";
import type { FailedCase, Verdict } from "../api/types";

export type StepState = "ok" | "ko" | "";

// Each language agrees the state with its own step noun: verdict.step.<id>.<state>.
export const STEPS = ["compile", "run", "tests"] as const;

export const stepLabel = (i: number): string => t(`verdict.step.${STEPS[i]}`);
export const stepState = (i: number, state: StepState): string =>
  t(`verdict.step.${STEPS[i]}.${state || "none"}`);

export interface Outcome {
  steps: [StepState, StepState, StepState];
}

// The title and next step of each are verdict.<status>.title and verdict.<status>.next.
export const OUTCOMES: Record<string, Outcome> = {
  forbidden_include: {
    steps: ["ko", "", ""],
  },
  compile_error: {
    steps: ["ko", "", ""],
  },
  compile_timeout: {
    steps: ["ko", "", ""],
  },
  link_error: {
    steps: ["ko", "", ""],
  },
  memory_error: {
    steps: ["ok", "ko", ""],
  },
  timeout: {
    steps: ["ok", "ko", ""],
  },
  error: {
    steps: ["ok", "ko", ""],
  },
};

const outcomeOf = (status: string): string => (status in OUTCOMES ? status : "error");
export const outcomeTitle = (status: string): string => t(`verdict.${outcomeOf(status)}.title`);
export const outcomeNext = (status: string): string => t(`verdict.${outcomeOf(status)}.next`);

export const AFTER_FAILURE = ["io", "unity", "quiz"];
export const afterFailure = (kind: string): string =>
  AFTER_FAILURE.includes(kind) ? t(`verdict.after.${kind}`) : "";

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

export type CaseClass = "unfinished" | "memory" | "crashed" | "wrong";

const CASE_CLASS: Record<string, CaseClass> = {
  unfinished: "unfinished",
  interrupted: "unfinished",
  memory: "memory",
  crashed: "crashed",
};

export const caseClass = (reason: string | undefined): CaseClass =>
  CASE_CLASS[reason ?? ""] ?? "wrong";

// The numbers contract explains value comparisons, not word checks.
export const showsContract = (c: FailedCase): boolean =>
  caseClass(c.reason) === "wrong" && c.reason !== "missing_word" && c.reason !== "forbidden_word";

// A key this page knows is worded; anything else is shown as sent.
const worded = (key: string, raw: string, params?: Params | null): string =>
  i18n.has(key) || i18n.has(key + "_other") ? t(key, params ?? {}) : raw;

export const caseReason = (c: FailedCase): string =>
  worded(`verdict.reason.${c.reason}`, c.reason, c.params);

export const quizHint = (hint: string): string => worded(`verdict.hint.${hint}`, hint);

// The longer explanation under a verdict's title: the judge's code if it gave one,
// otherwise its status's own text, otherwise whatever an older judge wrote.
export function verdictExplain(r: Verdict): string {
  if (r.code) return worded(`verdict.code.${r.code}`, r.message ?? r.code);
  const key = `verdict.${r.status}.explain`;
  return i18n.has(key) ? t(key, r.params ?? {}) : (r.message ?? "");
}

export const caseNumbers = (c: FailedCase): (string | number)[] | undefined =>
  c.numbers ?? c.nombres;

export const caseInputs = (stdin: string | undefined): string[] =>
  (stdin || "")
    .split("\n")
    .map((v) => v.trim())
    .filter((v) => v !== "");

export interface Scope {
  title: string;
  ids: string[];
}

export function restrictToScope(r: Verdict, scope: Scope): Verdict {
  const wrong = (r.wrong ?? []).filter((w) => scope.ids.indexOf(w.id) >= 0);
  return { ...r, total: scope.ids.length, passed: scope.ids.length - wrong.length, wrong };
}

export function estimatedWait(sec: number | undefined): string {
  if (!(sec && sec > 0)) return "";
  if (sec < 60) return t("verdict.wait_seconds", { n: Math.ceil(sec / 5) * 5 });
  return t("verdict.wait_minutes", { n: Math.ceil(sec / 60) });
}

const JUDGE_FAILURES = ["judge_internal", "judge_interrupted"];

export const isJudgeFailure = (r: Verdict): boolean =>
  r.status === "error" && JUDGE_FAILURES.includes(r.code ?? "");

export function verdictHeadline(r: Verdict, scope: Scope | null): string {
  if (r.status !== "ok") return outcomeTitle(r.status);
  const shown = scope && r.kind === "quiz" ? restrictToScope(r, scope) : r;
  const frame = scope && r.kind === "quiz" ? " — " + scope.title : "";
  return verdictCount(shown.passed ?? 0, shown.total ?? 0, r.kind) + frame;
}

export function verdictCount(passed: number, total: number, kind: string): string {
  return t("verdict.count", { passed, total, units: unitsOf(kind) });
}
