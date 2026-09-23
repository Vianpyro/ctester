// gcc's own wording for the errors beginners hit most; each id is verdict.gcc.<id>.
const GCC_HINTS: [RegExp, string][] = [
  [/expected ';'/, "semicolon"],
  [/undeclared/, "undeclared"],
  [/implicit declaration of function/, "implicit_function"],
  [/expected declaration or statement at end of input/, "missing_brace"],
  [/conflicting types/, "conflicting_types"],
  [/too (few|many) arguments/, "arguments"],
  [/stray '\\/, "stray_char"],
  [/redefinition of/, "redefinition"],
  [/'else' without a previous 'if'/, "else_without_if"],
  [/lvalue required/, "lvalue"],
];

export interface GccError {
  file: string;
  line: number;
  hint: string | null;
}

export function explainGcc(output: string | undefined): GccError | null {
  for (const l of (output || "").split("\n")) {
    const m = /^(\S+\.[ch]):(\d+):\d+:\s*(error|erreur)\s*:\s*(.*)$/i.exec(l);
    if (!m) continue;
    const hint = GCC_HINTS.find(([re]) => re.test(m[4]!))?.[1] ?? null;
    return { file: m[1]!, line: Number(m[2]), hint };
  }
  return null;
}
