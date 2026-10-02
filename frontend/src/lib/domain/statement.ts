import { escapeHtml, highlight } from "./highlight";
import { renderMath } from "./math";

const FENCE = /^\s*```/;
const INDENT = /^(\t| {4})/;
const MARKER = /^\s*(?:[-*+]|\d+\.) +(?=\S)/;
const ORDERED = /^\s*\d+\. /;
const ATX = /^(#{1,6}) +(.*)$/;
const SETEXT = /^(-{3,}|={3,})\s*$/;
// Alignment colons are accepted and ignored: every column is left-aligned.
const DELIMITER = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;

// Stricter than CommonMark: "*" is also a pointer and a multiplication in C, so emphasis
// needs flanking. "_" is never emphasis, because course text is full of snake_case.
// An apostrophe may open it too, for French elision: "l'**appelle**".
const flanked = (run: string): RegExp =>
  new RegExp(`(^|[\\s('’])${run}([^\\s*][^*\\n]*[^\\s*]|[^\\s*])${run}(?=$|[\\s).,;:!?])`, "g");

const STRONG_EM = flanked("\\*\\*\\*");
const STRONG = flanked("\\*\\*");
const EM = flanked("\\*");

const emphasis = (s: string): string =>
  s
    .replace(STRONG_EM, "$1<strong><em>$2</em></strong>")
    .replace(STRONG, "$1<strong>$2</strong>")
    .replace(EM, "$1<em>$2</em>");

const TOKEN = /(`[^`\n]+`|\$[^$\n]+\$)/;

const inline = (s: string): string =>
  s
    .split(TOKEN)
    .map((part, i) => {
      if (i % 2 === 0) return emphasis(escapeHtml(part));
      const body = part.slice(1, -1);
      // Math is opt-in: an unmarked "z/4" is C integer division, not a fraction.
      if (part[0] === "$") return renderMath(body) ?? "<code>" + escapeHtml(body) + "</code>";
      return "<code>" + escapeHtml(body) + "</code>";
    })
    .join("");

// A "|" inside a code span is C's "or", not a column break.
function cells(row: string): string[] {
  const out = [""];
  row
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split(TOKEN)
    .forEach((part, i) => {
      const [first, ...rest] = i % 2 === 0 ? part.split("|") : [part];
      out[out.length - 1] += first;
      out.push(...rest);
    });
  return out.map((cell) => inline(cell.trim()));
}

const row = (tag: string, line: string): string =>
  "<tr>" + cells(line).map((c) => "<" + tag + ">" + c + "</" + tag + ">").join("") + "</tr>";

function dedent(lines: string[]): string {
  let min = Infinity;
  for (const line of lines) {
    if (line.trim()) min = Math.min(min, /^[\t ]*/.exec(line)![0].length);
  }
  return lines.map((line) => line.slice(Number.isFinite(min) ? min : 0)).join("\n");
}

const codeBlock = (lines: string[]): string =>
  "<pre><code>" + highlight(dedent(lines)).replace(/\n$/, "") + "</code></pre>";

export function renderStatement(source: string): string {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const out: string[] = [];
  let i = 0;
  const isTable = (at: number): boolean =>
    lines[at]!.includes("|") && lines[at + 1] !== undefined && DELIMITER.test(lines[at + 1]!);

  while (i < lines.length) {
    const line = lines[i]!;

    if (!line.trim()) {
      i++;
      continue;
    }

    if (FENCE.test(line)) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !FENCE.test(lines[i]!)) body.push(lines[i++]!);
      i++;
      out.push(codeBlock(body));
      continue;
    }

    if (MARKER.test(line)) {
      const tag = ORDERED.test(line) ? "ol" : "ul";
      const items: string[] = [];
      while (i < lines.length && lines[i]!.trim()) {
        const marker = MARKER.exec(lines[i]!);
        if (marker) items.push(lines[i++]!.slice(marker[0].length));
        else if (items.length) items[items.length - 1] += " " + lines[i++]!.trim();
        else break;
      }
      const body = items.map((t) => "<li>" + inline(t.trim()) + "</li>").join("");
      out.push("<" + tag + ">" + body + "</" + tag + ">");
      continue;
    }

    if (INDENT.test(line)) {
      const body: string[] = [];
      while (i < lines.length && (INDENT.test(lines[i]!) || !lines[i]!.trim())) body.push(lines[i++]!);
      while (body.length && !body[body.length - 1]!.trim()) body.pop();
      out.push(codeBlock(body));
      continue;
    }

    if (isTable(i)) {
      const head = row("th", line);
      const body: string[] = [];
      i += 2;
      while (i < lines.length && lines[i]!.includes("|")) body.push(row("td", lines[i++]!));
      out.push("<table><thead>" + head + "</thead><tbody>" + body.join("") + "</tbody></table>");
      continue;
    }

    const atx = ATX.exec(line);
    if (atx) {
      const level = atx[1]!.length;
      out.push("<h" + level + ">" + inline(atx[2]!.trim()) + "</h" + level + ">");
      i++;
      continue;
    }

    if (lines[i + 1] !== undefined && SETEXT.test(lines[i + 1]!)) {
      const level = lines[i + 1]!.startsWith("=") ? 1 : 2;
      out.push("<h" + level + ">" + inline(line.trim()) + "</h" + level + ">");
      i += 2;
      continue;
    }

    const para: string[] = [];
    while (
      i < lines.length &&
      lines[i]!.trim() &&
      !FENCE.test(lines[i]!) &&
      !MARKER.test(lines[i]!) &&
      !INDENT.test(lines[i]!) &&
      !ATX.test(lines[i]!) &&
      !isTable(i) &&
      !(lines[i + 1] !== undefined && SETEXT.test(lines[i + 1]!))
    ) {
      para.push(lines[i++]!.trim());
    }
    if (!para.length) para.push(lines[i++]!.trim());
    out.push("<p>" + inline(para.join(" ")) + "</p>");
  }

  return out.join("\n");
}
