#let palettes = (
  dark: (
    bg: rgb("#14171d"), panel: rgb("#1a1e26"), card: rgb("#21262f"),
    line: rgb("#2c323d"),
    fg: rgb("#dfe3ea"), muted: rgb("#8b94a3"),
    ink: rgb("#8fb6dc"),
    ink-fill: rgb("#597ea3"), ink-wash: rgb("#1d2c3a"),
    ok: rgb("#6cc48a"), bad: rgb("#f2837c"),
  ),
  light: (
    bg: rgb("#f2f2f3"), panel: rgb("#f5f5f8"), card: rgb("#ffffff"),
    line: rgb("#d4d4d7"),
    fg: rgb("#1d1f20"), muted: rgb("#5d5d60"),
    ink: rgb("#416180"),
    ink-fill: rgb("#597ea3"), ink-wash: rgb("#eef6ff"),
    ok: rgb("#1f7a3d"), bad: rgb("#b3261e"),
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
