#let palettes = (
  dark: (
    bg: rgb("#0b1828"), panel: rgb("#0f2033"), card: rgb("#152a41"),
    line: rgb("#22405f"),
    fg: rgb("#e3ecf5"), muted: rgb("#93aac2"),
    ink: rgb("#7cc8ee"),
    ink-fill: rgb("#3f86b8"), ink-wash: rgb("#13304a"),
    ok: rgb("#63d39b"), bad: rgb("#ff8f80"),
  ),
  light: (
    bg: rgb("#e9eee8"), panel: rgb("#f4f7f2"), card: rgb("#fbfcfa"),
    line: rgb("#cbd5cd"),
    fg: rgb("#18231e"), muted: rgb("#4f5e56"),
    ink: rgb("#1d4f94"),
    ink-fill: rgb("#3d6fb5"), ink-wash: rgb("#e1eaf6"),
    ok: rgb("#17733f"), bad: rgb("#b42318"),
  ),
)

#let theme-name = {
  let asked = sys.inputs.at("theme", default: "dark")
  if asked in palettes { asked } else { "dark" }
}

#let palette = palettes.at(theme-name)

#let page-width = 300pt

#let body-font = "DejaVu Sans"
#let mono-font = "DejaVu Sans Mono"
#let body-size = 10.5pt   // 14 px
#let mono-size = 9.75pt   // 13 px
