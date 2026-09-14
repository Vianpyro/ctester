// LES ENCADRÉS PÉDAGOGIQUES, ET IL Y EN A CINQ.
//
// Chacun existe parce qu'un énoncé du cours en a besoin AUJOURD'HUI, pas parce
// qu'un système de blocs générique en voudrait un. Ajouter le suivant est une
// ligne ; inventer un `#encadre(type: "...")` paramétrable aurait été une API à
// documenter pour quatre appels.
//
// DEUX CIBLES. En SVG (paginé), chaque bloc se dessine lui-même. En HTML, il
// devient un élément portant une CLASSE, et c'est `app.css` qui le dessine avec
// les variables du thème : un HTML n'a pas besoin d'être rendu deux fois.

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

/// Une précision utile, jamais une contrainte. `--ink` est l'accent acier.
#let note(corps, titre: "Note") = _cadre("note", palette.ink, titre, corps)

/// Ce qui coûte un verdict rouge si on le rate. `--bad`, la couleur de l'échec.
#let attention(corps, titre: "Attention") = _cadre("attention", palette.bad, titre, corps)

/// Une exécution montrée : entrée, sortie. `--ok`, la couleur du verdict qui passe.
#let exemple(corps, titre: "Exemple") = _cadre("exemple", palette.ok, titre, corps)

// `code` est une chaîne OU un bloc brut (```c ... ```) : le bloc brut évite
// d'échapper les `"` et les `\n` d'un vrai programme C.
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
      // LA RÈGLE DE BLOC EST NEUTRALISÉE ICI. `enonce` (lib.typ) pose un fond
      // et un filet sur tout `raw.where(block: true)` ; à l'intérieur d'un
      // encadré qui en a déjà, ça dessine une seconde boîte. Vu au premier
      // rendu de la fixture.
      {
        show raw.where(block: true): it => it
        text(font: mono-font, size: mono-size, fill: palette.fg,
             raw(code, lang: "c", block: true))
      }
    },
  )
}
}

/// LE PROTOTYPE ATTENDU, et il mérite son propre bloc parce que c'est la seule
/// chose d'un énoncé que l'étudiant doit recopier À L'OCTET PRÈS. Un nom de
/// fonction mal lu, c'est une erreur d'édition de liens et un aller-retour.
#let signature(code, fichier: none) = _code(code, fichier, palette.ink-wash, "typ-signature")

/// UN CODE À RETAPER À LA MAIN. En HTML, la page refuse de le sélectionner et
/// de le copier (`.typ-recopier`) ; en SVG rien n'est copiable de toute façon.
/// C'est une DISSUASION, pas une protection : le texte reste dans le document.
#let recopier(code, fichier: none) = _code(code, fichier, palette.panel, "typ-recopier")
