#import "theme.typ": palette, page-width, body-font, mono-font, body-size, mono-size, theme-name
#import "blocks.typ": attention, example, note, retype, signature
#import "mermaid.typ": mermaid
#import "lang.typ": lang

#let statement(body) = context if target() == "html" { body } else {
  set page(width: page-width, height: auto, margin: 5.5pt, fill: palette.bg)
  set text(font: body-font, size: body-size, fill: palette.fg, lang: lang)
  set par(justify: false, leading: 0.65em, spacing: 0.9em)

  show heading: it => block(
    above: 1.1em, below: 0.5em,
    text(size: 1em, weight: 600, tracking: 0.4pt, fill: palette.muted,
         upper(it.body)),
  )

  show raw: set text(font: mono-font, size: mono-size, fill: palette.fg)
  set raw(theme: "themes/ctester-" + theme-name + ".tmTheme")

  show raw.where(block: true): it => if it.at("label", default: none) == <ctester-framed> {
    it
  } else {
    block(
      width: 100%, fill: palette.panel, stroke: 0.5pt + palette.line,
      inset: (x: 6pt, y: 5pt), spacing: 0.9em, radius: 0pt, it,
    )
  }
  show raw.where(block: false): it => box(
    fill: palette.panel, stroke: 0.5pt + palette.line,
    inset: (x: 2pt, y: 0pt), outset: (y: 2.5pt), radius: 0pt, it,
  )

  show link: set text(fill: palette.ink)
  show table.cell.where(y: 0): strong
  set table(stroke: 0.5pt + palette.line, inset: (x: 5pt, y: 3.5pt),
            fill: (_, y) => if y == 0 { palette.panel })

  body
}
