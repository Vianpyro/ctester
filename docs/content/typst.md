# Writing a statement in Typst

An exercise statement is either `statement.md` (Markdown) or `statement.typ` (Typst), never both.
Validation rejects an exercise that has both.

## When to use Typst

Markdown stays the default. It is rendered by the browser, so the text can be selected, copied,
searched and read aloud by a screen reader.

Use Typst when the layout is part of the explanation: tables (including computed ones), images,
Mermaid diagrams, formulas beyond simple `$...$`, or several pages.

A Typst statement is published as HTML, with SVG pages as a fallback. HTML text behaves like Markdown.
SVG text does not: it cannot be selected, copied, searched or read aloud.

## Layout

```text
exercises/tp2-ex3/
├── exercise.json
├── statement.typ
├── images/            optional figures
├── public/files.json
└── assessment/        never copied where the statement is compiled
```

A statement can only read files from its own exercise directory.

## A minimal statement

```typst
= Exercise title

Some text.
```

No preamble is needed: page layout, colors and C highlighting are applied by the build. Add the
import only when you use the helpers below. Without it, Typst fails with `unknown variable`.

```typst
#import "@local/ctester:1.0.0": *
```

## Markdown to Typst

| Markdown | Typst |
|---|---|
| `# Title` | `= Title` |
| `## Subtitle` | `== Subtitle` |
| `**bold**` | `*bold*` |
| `*italic*` | `_italic_` |
| `` `code` `` | `` `code` `` |
| `- item` | `- item` |
| `1. item` | `+ item` |
| `[text](url)` | `#link("url")[text]` |

Watch out: `*` is bold and `_` is italic in Typst.

## Content

C code uses a fenced block with the language, highlighted with the same colors as the editor.

````typst
```c
int main(void) { return 0; }
```
````

Math goes between dollar signs. `$O(n)$` stays inline; `$ ... $` with spaces is displayed on its own line.

```typst
$ sum_(i=1)^n i = (n(n+1))/2 $
```

Tables style their first row automatically. They can be computed from values:

```typst
#let values = (12, 42, 7)
#table(columns: 2, [Index], [Value],
  ..values.enumerate().map(((i, v)) => (str(i), str(v))).flatten())
```

Images:

```typst
#figure(image("images/memory.svg", width: 90%), caption: [The array after three iterations.])
```

Images are not re-themed: pick colors readable on both light and dark backgrounds, and leave the
background transparent.

Mermaid diagrams follow the theme. Avoid accents in node labels.

```typst
#mermaid(alt: "Submit, compile, then test", "graph TD
  A[Student] --> B[Compile]
  B --> C[Tests]")
```

## Helpers

```typst
#note[A useful detail.]
#attention[What costs a failed verdict.]
#example[Input: `5 12 42` — output: `42`.]
#signature(file: "buffer.h", "int maximum(const int v[], int n);")
#retype(```c
for (int i = 0; i < n; i++) printf("%d\n", t[i]);
```)
```

`note`, `attention` and `example` accept `title:`. `retype` marks code students must retype: it has
no Copy button and refuses selection. This discourages copying but does not prevent it.

`#pagebreak()` starts a new SVG page (at most 16). HTML ignores it.

## Previewing

Docker or a `typst` 0.15.1 binary (`CTESTER_TYPST_BIN`) is required.

```sh
python3 scripts/render_statement.py <content root>/exercises/<id> --out /tmp/preview --png
```

To see it in the real page, publish locally and start the API (see the README).

## When it breaks

A Typst error stops the whole publication: nothing is written, the active release stays in place, and
the error names the exercise, file and line. Other exercises are blocked too, so fix it right away. On
the server, the message shows up in `journalctl -u ctester-content -n 30`.

If an element cannot be exported to HTML, students get the SVG version. The publication log then
contains `rendu HTML incomplet`, naming the lost element.

Only `@local/ctester` and the vendored `@preview/merman` packages are available, since the build has no
network access. Fonts are DejaVu Sans and DejaVu Sans Mono.
