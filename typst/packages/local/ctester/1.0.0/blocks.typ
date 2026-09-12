// LES QUATRE ENCADRÉS PÉDAGOGIQUES, ET IL Y EN A QUATRE.
//
// Chacun existe parce qu'un énoncé du cours en a besoin AUJOURD'HUI, pas parce
// qu'un système de blocs générique en voudrait un. Ajouter le cinquième est une
// ligne ; inventer un `#encadre(type: "...")` paramétrable aurait été une API à
// documenter pour quatre appels.

#import "theme.typ": palette, mono-font, mono-size

#let _cadre(accent, titre, corps) = block(
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

/// Une précision utile, jamais une contrainte. `--ink` est l'accent acier.
#let note(corps, titre: "Note") = _cadre(palette.ink, titre, corps)

/// Ce qui coûte un verdict rouge si on le rate. `--bad`, la couleur de l'échec.
#let attention(corps, titre: "Attention") = _cadre(palette.bad, titre, corps)

/// Une exécution montrée : entrée, sortie. `--ok`, la couleur du verdict qui passe.
#let exemple(corps, titre: "Exemple") = _cadre(palette.ok, titre, corps)

/// LE PROTOTYPE ATTENDU, et il mérite son propre bloc parce que c'est la seule
/// chose d'un énoncé que l'étudiant doit recopier À L'OCTET PRÈS. Un nom de
/// fonction mal lu, c'est une erreur d'édition de liens et un aller-retour.
#let signature(code, fichier: none) = block(
  width: 100%,
  fill: palette.ink-wash,
  stroke: (left: 2pt + palette.ink-fill, rest: 0.5pt + palette.line),
  inset: (x: 7pt, y: 6pt),
  spacing: 8pt,
  {
    if fichier != none {
      block(spacing: 4pt,
            text(size: 0.8em, fill: palette.muted, font: mono-font, fichier))
    }
    // LA RÈGLE DE BLOC EST NEUTRALISÉE ICI, et c'est tout ce que ce bloc a de
    // particulier. `enonce` (lib.typ) pose un fond et un filet sur tout
    // `raw.where(block: true)` ; à l'intérieur d'un encadré qui en a déjà, ça
    // dessine une seconde boîte. Vu au premier rendu de la fixture. La règle
    // interne gagne parce qu'elle est plus proche du contenu.
    {
      show raw.where(block: true): it => it
      text(font: mono-font, size: mono-size, fill: palette.fg,
           raw(code, lang: "c", block: true))
    }
  },
)
