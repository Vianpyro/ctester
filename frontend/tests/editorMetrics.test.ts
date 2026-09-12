// LE CONTRAT MÉTRIQUE DE L'ÉDITEUR, ET C'EST LE SEUL ENDROIT QUI LE TIENT.
//
// `.hl` (la couche colorée) est posée SOUS `.codein` (le textarea au texte
// transparent), et `.gutter` aligne ses numéros sur les mêmes lignes. Les trois
// doivent partager leurs métriques AU PIXEL : tout ce qui décale le texte d'un
// pixel décale les couleurs, les numéros de ligne, le soulignement du correcteur
// et les curseurs des coéquipiers.
//
// ⚠ CE CONTRAT LIVRAIT AU VERT EN CASSANT À L'ŒIL. jsdom n'a pas de moteur de
// rendu : `getBoundingClientRect()` rend des zéros, donc `measure()`
// (`lib/collab/carets.ts`) rend `char: 0`, `usable` passe à faux, et les deux
// couches de superposition ne dessinent RIEN. `surface.test.ts` monte la surface
// et ne peut rien dire de son alignement ; `mount.test.ts` lit le contenu de la
// gouttière et pas sa géométrie. Un `13.5px` changé d'un seul côté passait donc
// toute la suite.
//
// D'OÙ UN TEST SUR LE TEXTE DU CSS, et pas sur le DOM. C'est la même technique de
// découpage à la chaîne que `test_ctester.py` applique déjà à ce fichier pour
// comparer les `--syn-*` aux deux `.tmTheme` -- et pour la même raison : la
// propriété à éprouver est dans la feuille, pas dans une page rendue.

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const CSS = readFileSync(join(import.meta.dirname, "..", "src", "app.css"), "utf8");

/**
 * Rend le corps de la première règle portant ce sélecteur, exactement comme
 * écrit. Le sélecteur est cherché en littéral (avec son `{`) : une règle
 * reformatée fait échouer en le disant, ce qui est le bon échec -- ce fichier
 * parle d'un contrat écrit à la main.
 */
function body(selector: string): string {
  const start = CSS.indexOf(selector + " {");
  expect(start, "règle introuvable dans app.css : " + selector).toBeGreaterThan(-1);
  const open = CSS.indexOf("{", start);
  const close = CSS.indexOf("}", open);
  expect(close, "règle non fermée : " + selector).toBeGreaterThan(open);
  return CSS.slice(open + 1, close);
}

/** La valeur d'une propriété dans un corps de règle, normalisée en espaces simples. */
function prop(ruleBody: string, name: string): string {
  const match = new RegExp("(?:^|;)\\s*" + name + "\\s*:\\s*([^;]+)").exec(ruleBody);
  expect(match, "propriété « " + name + " » absente de la règle").not.toBeNull();
  return match![1]!.trim().replace(/\s+/g, " ");
}

describe("le contrat métrique de l'éditeur", () => {
  const gutter = body(".gutter");
  const overlay = body(".hl, .codein");

  it("donne à la gouttière et à la superposition LE MÊME raccourci `font`", () => {
    // LA MÊME CHAÎNE, pas deux valeurs équivalentes : c'est ce qui garde les
    // numéros de ligne sur les lignes qu'ils numérotent.
    expect(prop(gutter, "font")).toBe(prop(overlay, "font"));
  });

  it("garde ce `font` en RACCOURCI, avec sa fente line-height et sa pile littérale", () => {
    // TROIS CHOSES TIENNENT DANS CETTE EXPRESSION, et chacune a coûté quelque chose :
    //
    // * LE RACCOURCI. La règle générique de `app.css` pose `font: inherit` sur tout
    //   `textarea` ; quatre propriétés séparées se laisseraient défaire une par une.
    //   Et `measure()` construit sa sonde avec `";font:" + style.font` -- il dépend
    //   donc de la sérialisation non vide du raccourci CALCULÉ, la seule valeur CSSOM
    //   qu'aucun test n'exerce. Pas de `var()` ici : la valeur ne vit qu'à deux
    //   endroits, donc un token n'achèterait rien contre ce risque-là.
    // * LE `/1.5`, un NOMBRE dans la fente line-height. `measure()` fait
    //   `parseFloat(style.lineHeight)` : `normal` y rendrait `NaN`, puis `0`, puis
    //   `usable` faux -- soulignements et curseurs distants disparaîtraient SANS un
    //   mot.
    // * LA PILE LITTÉRALE, et surtout pas `var(--mono)`, qui est une AUTRE pile :
    //   elle met « Cascadia Mono » avant Consolas, donc sur une machine de labo
    //   Windows une autre avance de caractère. Voir le commentaire de `#code` dans
    //   `app.css`.
    const attendu = /^400 \d+(?:\.\d+)?px\/1\.5 ui-monospace, SFMono-Regular, Consolas, monospace$/;
    expect(prop(overlay, "font")).toMatch(attendu);
    expect(prop(gutter, "font")).toMatch(attendu);
  });

  it("garde les deux couches superposables : même padding, même bordure, même boîte", () => {
    // `.hl` et `.codein` sont toutes deux `position: absolute; inset: 0` dans `.pane` :
    // leur texte ne se superpose que si la boîte intérieure est identique.
    expect(prop(overlay, "padding")).toBe(".5rem .7rem");
    expect(prop(overlay, "border")).toBe("1px solid transparent");
    expect(prop(overlay, "box-sizing")).toBe("border-box");
    expect(prop(overlay, "margin")).toBe("0");
    expect(prop(overlay, "white-space")).toBe("pre");
    expect(prop(overlay, "tab-size")).toBe("4");
  });

  it("aligne la gouttière VERTICALEMENT sur elles, sans exiger la même gouttière latérale", () => {
    // L'horizontal est libre -- la gouttière est en `text-align: right` et porte son
    // propre filet. Le VERTICAL ne l'est pas : un demi-rem de padding haut différent
    // décalerait tous les numéros d'une fraction de ligne, et l'écart grandirait à
    // mesure qu'on descend.
    const vert = (p: string) => p.split(" ")[0];
    expect(vert(prop(gutter, "padding"))).toBe(vert(prop(overlay, "padding")));
    expect(prop(gutter, "margin")).toBe("0");
    expect(prop(gutter, "white-space")).toBe("pre");
    // LA LARGEUR DE BORDURE EST CUITE DANS L'ORIGINE DE LA SUPERPOSITION :
    // `measure()` lit `paddingTop`/`paddingLeft` et PAS la bordure, donc le 1 px est
    // supposé partout. La changer décalerait les curseurs sans toucher au texte.
    expect(prop(gutter, "border")).toBe("1px solid transparent");
  });
});
