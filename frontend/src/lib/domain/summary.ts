import { UNITS } from "./labels";
import { restrictToScope, type Scope } from "./verdict";
import type { Verdict } from "../api/types";

/** One leg's line in the aggregate the screen reader is given. */
export function legLine(title: string, verdict: Verdict, scope: Scope | null): string {
  const r = scope && verdict.kind === "quiz" ? restrictToScope(verdict, scope) : verdict;
  const head =
    r.status === "ok"
      ? `${r.passed ?? 0} / ${r.total ?? 0} ${UNITS[r.kind] ?? "réussis"}`
      : (r.message ?? "échec");
  return title ? `${title} : ${head}` : head;
}
