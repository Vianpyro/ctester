#import "lang.typ": word
#import "theme.typ": palette, mono-font, mono-size

#let _frame(cls, accent, title, body) = context if target() == "html" {
  html.elem("aside", attrs: (class: "typ-" + cls), {
    if title != none { html.elem("strong", title) }
    body
  })
} else {
  block(
    width: 100%,
    fill: palette.panel,
    stroke: (left: 2pt + accent, rest: 0.5pt + palette.line),
    inset: (x: 7pt, y: 6pt),
    radius: 0pt,           // `--coin: 0` in app.css: the page has square corners.
    spacing: 8pt,
    {
      if title != none {
        block(spacing: 4pt, text(size: 0.85em, weight: 600, fill: accent,
                                 tracking: 0.3pt, upper(title)))
      }
      body
    },
  )
}

#let note(body, title: word("note")) = _frame("note", palette.ink, title, body)

#let attention(body, title: word("attention")) = _frame("attention", palette.bad, title, body)

#let example(body, title: word("example")) = _frame("example", palette.ok, title, body)

#let _code(source, file, fill, cls) = context {
let code = if type(source) == str { source } else { source.text }
if target() == "html" {
  html.elem("div", attrs: (class: cls), {
    if file != none { html.elem("small", file) }
    raw(code, lang: "c", block: true)
  })
} else {
  block(
    width: 100%,
    fill: fill,
    stroke: (left: 2pt + palette.ink-fill, rest: 0.5pt + palette.line),
    inset: (x: 7pt, y: 6pt),
    spacing: 8pt,
    {
      if file != none {
        block(spacing: 4pt,
              text(size: 0.8em, fill: palette.muted, font: mono-font, file))
      }
      text(font: mono-font, size: mono-size, fill: palette.fg,
           [#raw(code, lang: "c", block: true) <ctester-framed>])
    },
  )
}
}

#let signature(code, file: none) = _code(code, file, palette.ink-wash, "typ-signature")

#let retype(code, file: none) = _code(code, file, palette.panel, "typ-retype")
