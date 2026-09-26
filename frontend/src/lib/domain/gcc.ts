// gcc's own wording for the errors beginners hit most; each id is verdict.gcc.<id>.
const GCC_HINTS: [RegExp, string][] = [
  [/expected ';'/, "semicolon"],
  [/expected '=', ',', ';', 'asm'/, "name_space"],
  [/expected declaration specifiers|expected identifier or '\('/, "outside_function"],
  [/invalid preprocessing directive/, "directive"],
  [/No such file or directory/, "header"],
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
  const lines = (output || "").split("\n");
  for (const l of lines) {
    const m = /^(\S+\.[ch]):(\d+):\d+:\s*(?:fatal )?(error|erreur)\s*:\s*(.*)$/i.exec(l);
    if (!m) continue;
    const hint = GCC_HINTS.find(([re]) => re.test(m[4]!))?.[1] ?? null;
    return { file: m[1]!, line: Number(m[2]), hint };
  }
  // The linker names no line: a missing main, or a function nobody defines.
  for (const l of lines) {
    const m = /undefined reference to [`'‘](\w+)['’]/.exec(l);
    if (m) return { file: "", line: 0, hint: m[1] === "main" ? "no_main" : "undefined_reference" };
  }
  return null;
}
