import { t } from "../i18n.svelte";

// The Console's optional header. Same rule as HEADER_RE in app/services/scratch.py and
// gate::valid_header_name in the judge.
const HEADER_NAME = /^[A-Za-z0-9_]{1,32}\.h$/;

export const headerNameHint = (): string => t("console.header_hint");

export function validHeaderName(name: string): boolean {
  return HEADER_NAME.test(name);
}

export function headerTemplate(name: string): string {
  let guard = name.slice(0, -2).toUpperCase() + "_H";
  if (/^[0-9]/.test(guard)) guard = "H_" + guard;
  return (
    `#ifndef ${guard}\n#define ${guard}\n\n` +
    t("console.header_template") + "\n\n" +
    `#endif /* ${guard} */\n`
  );
}

export interface ConsoleFiles {
  code: string;
  headerName: string;
  header: string;
}

const mainStub = (): string =>
  "\n#include <stdio.h>\n\n" +
  t("console.main_stub") +
  "\nint main(void)\n{\n\n    return 0;\n}\n";

// The Console holds main.c and at most one header, so every .c file is joined into main.c.
export function consoleFiles(
  files: { name: string }[],
  sources: Record<string, string>,
): ConsoleFiles | string {
  const list = files.length ? files : [{ name: "submission.c" }];
  const headers = list.filter((f) => f.name.endsWith(".h"));
  if (headers.length > 1) {
    return t("console.one_header");
  }
  const headerName = headers[0]?.name ?? "";
  if (headerName && !validHeaderName(headerName)) return headerNameHint();
  const sourcesC = list.filter((f) => !f.name.endsWith(".h"));
  let code = sourcesC
    .map((f) => {
      const text = (sources[f.name] ?? "").replace(/\s+$/, "");
      return sourcesC.length > 1 ? "/* " + f.name + " */\n" + text : text;
    })
    .join("\n\n");
  if (!code.trim()) return t("console.nothing_to_copy");
  if (!/\bmain\s*\(/.test(code)) code += "\n" + mainStub();
  else code += "\n";
  return { code, headerName, header: headerName ? (sources[headerName] ?? "") : "" };
}
