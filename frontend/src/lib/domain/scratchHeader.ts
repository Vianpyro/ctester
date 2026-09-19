// The Console's optional header. Same rule as HEADER_RE in app/services/scratch.py and
// gate::valid_header_name in the judge.
const HEADER_NAME = /^[A-Za-z0-9_]{1,32}\.h$/;

export const HEADER_NAME_HINT =
  "Nom invalide : lettres, chiffres ou _, puis .h (32 caractères au plus), par exemple pile.h.";

export function validHeaderName(name: string): boolean {
  return HEADER_NAME.test(name);
}

export function headerTemplate(name: string): string {
  let guard = name.slice(0, -2).toUpperCase() + "_H";
  if (/^[0-9]/.test(guard)) guard = "H_" + guard;
  return (
    `#ifndef ${guard}\n#define ${guard}\n\n` +
    "/* Déclare ici tes constantes, tes types et tes prototypes. */\n\n" +
    `#endif /* ${guard} */\n`
  );
}

export interface ConsoleFiles {
  code: string;
  headerName: string;
  header: string;
}

const MAIN_STUB =
  "\n#include <stdio.h>\n\n" +
  "/* Ajouté pour la Console : appelle ici tes fonctions avec tes propres valeurs. */\n" +
  "int main(void)\n{\n\n    return 0;\n}\n";

// The Console holds main.c and at most one header, so every .c file is joined into main.c.
export function consoleFiles(
  files: { name: string }[],
  sources: Record<string, string>,
): ConsoleFiles | string {
  const list = files.length ? files : [{ name: "submission.c" }];
  const headers = list.filter((f) => f.name.endsWith(".h"));
  if (headers.length > 1) {
    return "La Console n'accepte qu'un seul en-tête .h : copie ton code à la main.";
  }
  const headerName = headers[0]?.name ?? "";
  if (headerName && !validHeaderName(headerName)) return HEADER_NAME_HINT;
  const sourcesC = list.filter((f) => !f.name.endsWith(".h"));
  let code = sourcesC
    .map((f) => {
      const text = (sources[f.name] ?? "").replace(/\s+$/, "");
      return sourcesC.length > 1 ? "/* " + f.name + " */\n" + text : text;
    })
    .join("\n\n");
  if (!code.trim()) return "Il n'y a encore rien à copier : écris ton code d'abord.";
  if (!/\bmain\s*\(/.test(code)) code += "\n" + MAIN_STUB;
  else code += "\n";
  return { code, headerName, header: headerName ? (sources[headerName] ?? "") : "" };
}
