#import "theme.typ": palette, mono-font, mono-size

#let _cadre(classe, accent, titre, corps) = context if target() == "html" {
  html.elem("aside", attrs: (class: "typ-" + classe), {
    if titre != none { html.elem("strong", titre) }
    corps
  })
} else {
  block(
    width: 100%,
    fill: palette.panel,
    stroke: (left: 2pt + accent, rest: 0.5pt + palette.line),
    inset: (x: 7pt, y: 6pt),
    radius: 0pt,           // `--coin: 0` dans app.css : la page est à coins carrés.
    spacing: 8pt,
    {
      if titre != none {
        block(spacing: 4pt, text(size: 0.85em, weight: 600, fill: accent,
                                 tracking: 0.3pt, upper(titre)))
      }
      corps
    },
  )
}

#let note(corps, titre: "Note") = _cadre("note", palette.ink, titre, corps)

#let attention(corps, titre: "Attention") = _cadre("attention", palette.bad, titre, corps)

#let exemple(corps, titre: "Exemple") = _cadre("exemple", palette.ok, titre, corps)

#let _code(source, fichier, fond, classe) = context {
let code = if type(source) == str { source } else { source.text }
if target() == "html" {
  html.elem("div", attrs: (class: classe), {
    if fichier != none { html.elem("small", fichier) }
    raw(code, lang: "c", block: true)
  })
} else {
  block(
    width: 100%,
    fill: fond,
    stroke: (left: 2pt + palette.ink-fill, rest: 0.5pt + palette.line),
    inset: (x: 7pt, y: 6pt),
    spacing: 8pt,
    {
      if fichier != none {
        block(spacing: 4pt,
              text(size: 0.8em, fill: palette.muted, font: mono-font, fichier))
      }
      text(font: mono-font, size: mono-size, fill: palette.fg,
           [#raw(code, lang: "c", block: true) <ctester-encadre>])
    },
  )
}
}

#let signature(code, fichier: none) = _code(code, fichier, palette.ink-wash, "typ-signature")

#let recopier(code, fichier: none) = _code(code, fichier, palette.panel, "typ-recopier")
