function normalizeEncoding(text: string): string {
  const sansBom = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
  return sansBom.includes("\r") ? sansBom.replace(/\r\n?/g, "\n") : sansBom;
}

// Lighter than canonicalize(): trailing blanks are kept so an imported file looks untouched.
export function decodeImported(text: string): string {
  return normalizeEncoding(text);
}

// Mirrors app/services/source.py; tests/fixtures/source.json holds both to the same cases.
export function canonicalize(text: string): string {
  const s = normalizeEncoding(text);
  if (!s.includes(" \n") && !s.includes("\t\n") && !/[ \t]$/.test(s)) return s;
  return s
    .split("\n")
    .map((line) => {
      const cut = line.replace(/[ \t]+$/, "");
      return cut !== line && cut.endsWith("\\") ? line : cut;
    })
    .join("\n");
}

export function canonicalizeFiles(files: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [name, text] of Object.entries(files)) out[name] = canonicalize(text);
  return out;
}
