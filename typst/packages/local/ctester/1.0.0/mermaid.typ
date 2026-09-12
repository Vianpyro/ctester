// LA SEULE PORTE VERS MERMAID, ET C'EST VOULU.
//
// `@preview/merman` est vendoré dans `typst/packages/preview/` (3 Mo, dont
// 7,6 Mo de WebAssembly décompressé). CE FICHIER EST LE SEUL DU DÉPÔT QUI
// L'IMPORTE, et un test le vérifie -- même dessin que
// `test_forum_bibliotheques_epinglees` pour marked/DOMPurify/Yjs : une
// bibliothèque tierce a UN point d'entrée nommé, sinon la mise à jour se fait à
// six endroits dont un qu'on oublie.
//
// LA VERSION EST EXACTE (`0.3.0`), jamais un intervalle. Le paquet étant
// vendoré, la résolution ne touche pas le réseau : `TYPST_PACKAGE_PATH` pointe
// sur `typst/packages`, et `typst_build.py` compile avec `--network=none` dans
// le conteneur. Un commit donné rend donc toujours le même diagramme.

#import "@preview/merman:0.3.0": mermaid as _mermaid
#import "theme.typ": palette, theme-name, body-font, body-size

/// Un diagramme Mermaid, aux couleurs de la page.
///
/// `alt` EST OBLIGATOIRE EN PRATIQUE et le défaut le dit : le SVG rendu par
/// Typst vectorise ses glyphes, donc le texte du diagramme n'est lisible par
/// aucun lecteur d'écran. Ce texte de remplacement ne rattrape pas
/// l'accessibilité du rendu -- voir `docs/content/typst.md` -- il donne juste
/// à Typst de quoi ne pas rester muet.
#let mermaid(source, alt: "Diagramme", ..args) = _mermaid(
  source,
  alt: alt,
  width: 100%,
  // LE FOND DU DIAGRAMME EST CELUI DE LA PAGE, ET IL SE DIT ICI, PAS DANS
  // `theme`. Mermaid peint un fond BLANC à l'intérieur de son propre SVG :
  // sans cette ligne, un diagramme est un rectangle blanc au milieu d'un
  // énoncé sombre. Vu au premier rendu de la fixture.
  background: palette.bg.to-hex(),
  // `theme-name` est le thème de MERMAID (« dark » / « base »), distinct du
  // thème de ctester qui le choisit. Les variables ci-dessous reprennent la
  // palette de `app.css` pour que le diagramme ne soit pas la seule chose de
  // l'énoncé à ne pas suivre le thème.
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
