// LE POINT D'ENTRÉE DE LA BIBLIOTHÈQUE DES ÉNONCÉS.
//
// UN ENSEIGNANT N'ÉCRIT PAS DE PRÉAMBULE. `typst_build.py` compile un
// `main.typ` généré qui fait `#show: enonce` puis `#include` le `statement.typ`
// de l'exercice : la mise en page, la palette, la coloration et la largeur de
// colonne sont donc posées SANS que l'auteur ait rien à recopier. Un
// `statement.typ` réduit à
//
//     = Titre
//     Du texte.
//
// est déjà stylé.
//
// LA LIGNE D'IMPORT NE SERT QU'AUX HELPERS. Les portées de Typst sont par
// FICHIER : un `#import` dans le `main.typ` généré ne rend pas `#note` visible
// dans `statement.typ`. L'auteur qui veut `#note`, `#mermaid` ou `#signature`
// écrit donc
//
//     #import "@local/ctester:1.0.0": *
//
// en tête, et celui qui n'en veut pas n'écrit rien du tout et garde le style.

#import "theme.typ": palette, page-width, body-font, mono-font, body-size, mono-size, theme-name
#import "blocks.typ": attention, exemple, note, signature
#import "mermaid.typ": mermaid

/// Le gabarit d'un énoncé. Appliqué par le `main.typ` que le build écrit.
#let enonce(corps) = {
  // HAUTEUR AUTOMATIQUE, SAUF PAGINATION EXPLICITE. Un énoncé n'est pas une
  // feuille : il est posé dans une colonne qui défile. `auto` donne donc UNE
  // page aussi haute qu'il faut, et un `#pagebreak()` volontaire de l'auteur en
  // donne deux -- c'est le seul moyen d'en avoir plusieurs, et c'est voulu.
  set page(width: page-width, height: auto, margin: 4pt, fill: palette.bg)
  set text(font: body-font, size: body-size, fill: palette.fg, lang: "fr")
  set par(justify: false, leading: 0.65em, spacing: 0.9em)

  // LES TITRES SONT CEUX DE `app.css` : petites capitales grises, à peine plus
  // grosses que le corps. Dans une colonne de 25 rem, un vrai titre de page
  // mangerait le tiers de l'écran.
  show heading: it => block(
    above: 1.1em, below: 0.5em,
    text(size: 1em, weight: 600, tracking: 0.4pt, fill: palette.muted,
         upper(it.body)),
  )

  // LE `#set text(fill:)` CI-DESSOUS N'EST PAS DÉCORATIF. Un `.tmTheme` ne
  // colore que les jetons scopés ; les identifiants nus prennent le `fill` du
  // texte environnant. Sans cette ligne ils sortent en noir -- illisibles sur
  // le fond sombre. Mesuré.
  show raw: set text(font: mono-font, size: mono-size, fill: palette.fg)
  set raw(theme: "themes/ctester-" + theme-name + ".tmTheme")

  // Un bloc de code : le fond `--panel` et le filet `--line` de `#consignetexte.md pre`.
  show raw.where(block: true): it => block(
    width: 100%, fill: palette.panel, stroke: 0.5pt + palette.line,
    inset: (x: 6pt, y: 5pt), spacing: 0.9em, radius: 0pt, it,
  )
  // Un code inline : le même fond, sans le bloc.
  show raw.where(block: false): it => box(
    fill: palette.panel, stroke: 0.5pt + palette.line,
    inset: (x: 2pt, y: 0pt), outset: (y: 2.5pt), radius: 0pt, it,
  )

  show link: set text(fill: palette.ink)
  show table.cell.where(y: 0): strong
  set table(stroke: 0.5pt + palette.line, inset: (x: 5pt, y: 3.5pt),
            fill: (_, y) => if y == 0 { palette.panel })

  corps
}
