// THE STATEMENT'S MARKDOWN, AND IT IS DELIBERATELY NOT `marked`.
//
// The 77 statements of the course use FOUR constructs: an indented code block (56
// files), inline code (8), a bullet list (5), a heading (1). Nothing else -- no
// bold, no link, no blockquote, no table. `marked` + DOMPurify weigh 74 KB and
// live in the forum chunk, fetched on a click; the statement sits on the ANONYMOUS
// path, so wiring them here would hand 74 KB to a student with no account the
// moment they open an exercise -- exactly the promise `bundle.test.ts` exists to
// keep. `highlight()` is already in the eager chunk (it colours the editor), and
// its classes are global, so a code block here costs nothing at all.
//
// EMPHASIS IS FLANKED, AND THAT IS THE WHOLE OF THE RULE. `*` is C's dereference
// and multiplication operator, and `marked` EATS the asterisks out of
// `mets *quotient et *reste a 0` and out of `(23*m/9 + d + 4) % 7 ... (23*m/9`. So
// a `*` opens emphasis only when it FOLLOWS the start of the line, a space or a
// `(` AND is followed by a non-space; it closes only before a space, a closing
// punctuation mark or the end of the line. That is stricter than CommonMark, which
// allows an intraword `*` and therefore still eats `23*m/9`.
//
// No `**bold**` and no `_underscore_`: nothing in the content uses either, and a
// literal `**gras**` left on screen is a VISIBLE failure rather than a silent one.
//
// NO SANITIZER BECAUSE THERE IS NOTHING TO SANITIZE. Every slice of the source
// goes through `escapeHtml()` before it is placed between tags THIS file writes.
// That is the same contract `highlight()` already holds, and the reason its output
// is allowed near `innerHTML`.

import { escapeHtml, highlight } from "./highlight";

const FENCE = /^\s*```/;
/** A tab or four spaces: Markdown's indented code block. */
const INDENT = /^(\t| {4})/;
/** A bullet OR a number, at ANY indentation -- see the list branch for why it wins
 *  over INDENT. */
const MARKER = /^\s*(?:[-*+]|\d+\.) +(?=\S)/;
const ORDERED = /^\s*\d+\. /;
const ATX = /^(#{1,6}) +(.*)$/;
/** The underline of a setext heading. Checked on the NEXT line, never on its own. */
const SETEXT = /^(-{3,}|={3,})\s*$/;

/**
 * `*italique*`, and only where BOTH asterisks are flanked -- see the header. The
 * content may not itself hold a `*`, which is what also spares `A = pi * r^2` and
 * `0,5 * rho * pi`: every asterisk there is followed by a space, so none opens.
 */
const emphasis = (s: string): string =>
  s.replace(/(^|[\s(])\*([^\s*][^*\n]*[^\s*]|[^\s*])\*(?=$|[\s).,;:!?])/g, "$1<em>$2</em>");

/**
 * INLINE CODE FIRST, EMPHASIS SECOND, AND NEVER INSIDE A CODE SPAN. `split` with a
 * capture group puts the captures at the odd indices, so only the halves BETWEEN
 * the backticks are read for emphasis -- which is why `` `P = F * v` `` keeps its
 * asterisk. Both halves are escaped, so a backtick-less source is escaped text.
 */
const inline = (s: string): string =>
  s
    .split(/`([^`\n]+)`/)
    .map((part, i) =>
      i % 2 ? "<code>" + escapeHtml(part) + "</code>" : emphasis(escapeHtml(part)),
    )
    .join("");

/**
 * The common indentation, removed. Counted in CHARACTERS, which is right for both
 * conventions in the content (tabs in some files, four spaces in others) because a
 * block never mixes them. Tabs INSIDE a line are untouched: `tp2-ex8` uses them to
 * line up its arrows, and `tab-size` on the `<pre>` is what renders that.
 */
function dedent(lines: string[]): string {
  let min = Infinity;
  for (const line of lines) {
    if (line.trim()) min = Math.min(min, /^[\t ]*/.exec(line)![0].length);
  }
  return lines.map((line) => line.slice(Number.isFinite(min) ? min : 0)).join("\n");
}

/** `highlight()` ends with a newline -- it keeps the editor's overlay one line
 *  taller than the text. A `<pre>` here would render it as a blank last line. */
const codeBlock = (lines: string[]): string =>
  "<pre><code>" + highlight(dedent(lines)).replace(/\n$/, "") + "</code></pre>";

/** ESCAPED HTML for a statement. Pure: no DOM, no fetch, no library. */
export function renderStatement(source: string): string {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const out: string[] = [];
  let i = 0;

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
      i++; // the closing fence, or the end of the file
      out.push(codeBlock(body));
      continue;
    }

    // A LIST IS CHECKED BEFORE AN INDENTED BLOCK, and that order is the point:
    // `tp9-ex6` indents its bullets by four spaces and `tp2-ex0` its numbers by a
    // tab, which Markdown would both read as code -- and a code block here means
    // `highlight()`, which colours a pair of French apostrophes ("l'annee ... de
    // l'usager") as a character literal. A continuation line -- indented further,
    // not itself a marker -- folds into the item above it, which is how every list
    // in the content is written.
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

    // A PARAGRAPH REFLOWS: its lines are joined by a SPACE, not by a `<br>`. The
    // statements are hard-wrapped at about sixty columns, which is wider than the
    // 25 rem column they are read in -- honouring those newlines would break every
    // line twice, in the middle of sentences. This is where the forum's
    // `breaks: true` would have been exactly wrong.
    const para: string[] = [];
    while (
      i < lines.length &&
      lines[i]!.trim() &&
      !FENCE.test(lines[i]!) &&
      !MARKER.test(lines[i]!) &&
      !INDENT.test(lines[i]!) &&
      !ATX.test(lines[i]!) &&
      !(lines[i + 1] !== undefined && SETEXT.test(lines[i + 1]!))
    ) {
      para.push(lines[i++]!.trim());
    }
    // A line that stopped the loop without any text before it is prose that looks
    // like a marker; take it literally rather than spinning.
    if (!para.length) para.push(lines[i++]!.trim());
    out.push("<p>" + inline(para.join(" ")) + "</p>");
  }

  return out.join("\n");
}
