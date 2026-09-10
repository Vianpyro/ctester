// THE C HIGHLIGHTER, AND IT IS SHARED. The exercise editor and the Console both
// colour the same language, and a second copy of this grammar would be a second
// grammar to fix twice.
//
// A PURE FUNCTION: text in, ESCAPED HTML out. Its output is the only thing in
// this application allowed near `innerHTML` besides the sanitized forum markdown,
// and that is safe for exactly one reason -- every branch below runs its slice
// through `escapeHtml()` first.

const ESC: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;" };

export const escapeHtml = (s: string): string => s.replace(/[&<>]/g, (c) => ESC[c]!);

const KEYWORDS =
  "auto|break|case|char|const|continue|default|do|double|else|" +
  "enum|extern|float|for|goto|if|inline|int|long|register|restrict|return|" +
  "short|signed|sizeof|static|struct|switch|typedef|union|unsigned|void|" +
  "volatile|while|bool|true|false|NULL";

const C_RE = new RegExp(
  [
    "(\\/\\/[^\\n]*|\\/\\*[\\s\\S]*?\\*\\/)",
    "(\"(?:\\\\.|[^\"\\\\\\n])*\"|'(?:\\\\.|[^'\\\\\\n])*')",
    "(^[ \\t]*#[ \\t]*\\w+)",
    "\\b(" + KEYWORDS + ")\\b",
    "\\b(\\d[\\w.]*)",
    "([A-Za-z_]\\w*)(?=\\s*\\()",
    "\\b([A-Z][A-Z0-9_]{2,})\\b",
  ].join("|"),
  "gm",
);

/** comment, string, preprocessor, keyword, number, function, upper-case macro */
const CLASS = ["tc", "ts", "tp", "tk", "tn", "tf", "tu"];

export function highlight(src: string): string {
  let out = "";
  let last = 0;
  for (const m of src.matchAll(C_RE)) {
    out += escapeHtml(src.slice(last, m.index));
    const which = m.slice(1, CLASS.length + 1).findIndex((g) => g !== undefined);
    out += '<span class="' + CLASS[which] + '">' + escapeHtml(m[0]) + "</span>";
    last = m.index + m[0].length;
  }
  // The trailing newline keeps the overlay one line taller than the text, so the
  // last line's colours do not get clipped as one types into it.
  return out + escapeHtml(src.slice(last)) + "\n";
}
