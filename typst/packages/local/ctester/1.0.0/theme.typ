// LES COULEURS DE LA PAGE, RECOPIÉES DEPUIS `frontend/src/app.css`.
//
// Elles sont recopiées et pas dérivées : le SVG est rendu au build, la feuille
// de style vit dans le navigateur, et rien ne peut les lire toutes les deux au
// même instant. Ce qui empêche la dérive est un TEST --
// `test_le_theme_typst_porte_les_couleurs_de_la_page` lit `app.css` et ce
// fichier, et compare. Même dessin que `test_csp_du_document` pour les deux
// copies de la CSP.
//
// LE THÈME VIENT DE `--input theme=`, pas d'une variable de compilation : le
// même document est compilé DEUX FOIS, une fois par thème, et la page choisit
// le SVG selon ce que l'étudiant a réglé. Un SVG est peint une fois pour
// toutes -- il ne peut pas suivre `prefers-color-scheme` tout seul.

#let palettes = (
  dark: (
    bg: rgb("#14171d"), panel: rgb("#1a1e26"), card: rgb("#21262f"),
    line: rgb("#2c323d"), line-2: rgb("#3a424f"),
    fg: rgb("#dfe3ea"), muted: rgb("#8b94a3"),
    ink: rgb("#8fb6dc"), ink-fg: rgb("#10202e"),
    ink-fill: rgb("#597ea3"), ink-wash: rgb("#1d2c3a"),
    ok: rgb("#6cc48a"), bad: rgb("#f2837c"), wait: rgb("#d8bb6a"),
  ),
  light: (
    bg: rgb("#f2f2f3"), panel: rgb("#f5f5f8"), card: rgb("#ffffff"),
    line: rgb("#d4d4d7"), line-2: rgb("#b7b7ba"),
    fg: rgb("#1d1f20"), muted: rgb("#5d5d60"),
    ink: rgb("#416180"), ink-fg: rgb("#f5f5f8"),
    ink-fill: rgb("#597ea3"), ink-wash: rgb("#eef6ff"),
    ok: rgb("#1f7a3d"), bad: rgb("#b3261e"), wait: rgb("#8a6d1f"),
  ),
)

/// Le thème demandé au compilateur, `dark` par défaut -- celui de la page.
#let theme-name = {
  let asked = sys.inputs.at("theme", default: "dark")
  if asked in palettes { asked } else { "dark" }
}

#let palette = palettes.at(theme-name)

// LA LARGEUR EST CELLE DE LA COLONNE, pas celle d'une feuille. `#consigne` fait
// `minmax(19rem, 25rem)` dans `app.css` et le SVG est posé en `width: 100%` :
// c'est donc le RAPPORT entre cette largeur et le corps du texte qui décide de
// la taille lue à l'écran. À 320 pt pour 11,5 pt de corps, le texte est rendu
// entre 10,9 px (colonne à 19 rem) et 14,4 px (colonne à 25 rem) -- de part et
// d'autre des 13,5 px du Markdown, qui est la référence.
#let page-width = 320pt

// Le corps en Libertinus Serif et le code en DejaVu Sans Mono : ce sont DEUX DES
// QUATRE FAMILLES EMBARQUÉES dans le binaire typst. Avec `--ignore-system-fonts`
// (voir typst_build.py) le rendu ne dépend donc d'aucune fonte installée, et il
// n'y a pas une seule fonte à vendorer.
#let body-font = "Libertinus Serif"
#let mono-font = "DejaVu Sans Mono"
#let body-size = 11.5pt
#let mono-size = 9.5pt
