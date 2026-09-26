import { INDENT, type Edit } from "./keys";

// ponytail: leading and trailing whitespace only, by brace depth; a brace-less if body or a line
// continuing an open "(" stays at its block's level. A tokenizer-level formatter is the upgrade.
export function reindent(value: string): string {
  let depth = 0;
  let inComment = false;
  return value
    .split("\n")
    .map((raw) => {
      const line = raw.replace(/\s+$/, "");
      const body = line.trim();
      const kept = inComment;
      const closers = /^[}\s]*/.exec(body)![0].replace(/\s/g, "").length;
      const level = body.startsWith("#") ? 0 : Math.max(depth - closers, 0);
      for (let i = 0; i < body.length; i++) {
        const c = body[i];
        if (inComment) {
          if (c === "*" && body[i + 1] === "/") {
            inComment = false;
            i++;
          }
        } else if (c === "/" && body[i + 1] === "/") {
          break;
        } else if (c === "/" && body[i + 1] === "*") {
          inComment = true;
          i++;
        } else if (c === '"' || c === "'") {
          for (i++; i < body.length && body[i] !== c; i++) if (body[i] === "\\") i++;
        } else if (c === "{") {
          depth++;
        } else if (c === "}") {
          depth = Math.max(depth - 1, 0);
        }
      }
      // Inside a block comment, the student's own layout is the text.
      if (kept) return line;
      return body ? " ".repeat(INDENT * level) + body : "";
    })
    .join("\n");
}

// Same line count before and after, so a caret keeps its row and its place in the text.
function caretAfter(before: string[], after: string[], pos: number): number {
  let row = 0;
  let from = 0;
  let to = 0;
  while (row < before.length - 1 && pos > from + before[row]!.length) {
    from += before[row]!.length + 1;
    to += after[row]!.length + 1;
    row++;
  }
  const indent = (line: string) => line.length - line.trimStart().length;
  const now = after[row]!;
  const column = pos - from + indent(now) - indent(before[row]!);
  return to + Math.min(Math.max(column, indent(now)), now.length);
}

export function formatEdit(value: string, start: number, end: number): Edit | null {
  const next = reindent(value);
  if (next === value) return null;
  let head = 0;
  while (value[head] === next[head]) head++;
  let tail = 0;
  while (
    tail < value.length - head &&
    tail < next.length - head &&
    value[value.length - 1 - tail] === next[next.length - 1 - tail]
  ) {
    tail++;
  }
  const before = value.split("\n");
  const after = next.split("\n");
  return {
    from: head,
    to: value.length - tail,
    insert: next.slice(head, next.length - tail),
    caret: caretAfter(before, after, start),
    caretEnd: start === end ? undefined : caretAfter(before, after, end),
  };
}
