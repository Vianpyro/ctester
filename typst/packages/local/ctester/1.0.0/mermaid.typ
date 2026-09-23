#import "@preview/merman:0.3.0": mermaid as _mermaid
#import "theme.typ": palette, theme-name, body-font, body-size
#import "lang.typ": word

#let mermaid(source, alt: word("diagram"), ..args) = _mermaid(
  source,
  alt: alt,
  width: 100%,
  background: palette.bg.to-hex(),
  theme-name: if theme-name == "dark" { "dark" } else { "base" },
  theme: (
    background: palette.bg.to-hex(),
    primaryColor: palette.card.to-hex(),
    primaryTextColor: palette.fg.to-hex(),
    primaryBorderColor: palette.ink-fill.to-hex(),
    lineColor: palette.ink.to-hex(),
    secondaryColor: palette.panel.to-hex(),
    tertiaryColor: palette.ink-wash.to-hex(),
    fontFamily: body-font,
    fontSize: repr(body-size),
  ),
  ..args,
)
