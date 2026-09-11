// L'AIDE-MÉMOIRE : LE TEXTE, ET RIEN QUE LE TEXTE.
//
// POURQUOI CE FICHIER EST SÉPARÉ DE `shortcuts.ts`, alors que « une seule
// source » est justement la règle de ce lot : `shortcuts.ts` doit être dans le
// paquet de départ, puisque le matcher tourne à chaque frappe. Les LIBELLÉS,
// eux, ne servent qu'à quelqu'un qui a pressé F1 -- et ils pèsent plus que la
// table elle-même. Les garder ensemble ferait payer deux kilo-octets de prose
// française à un anonyme qui n'ouvrira jamais le panneau, sur un paquet dont le
// budget est compté (`bundle.test.ts`).
//
// ET LA DÉRIVE RESTE IMPOSSIBLE, PAR LE TYPE : `HELP` est un
// `Record<ShortcutId, …>`, donc OUBLIER UN RACCOURCI LIÉ EST UNE ERREUR DE
// COMPILATION, pas un test qui rougit plus tard. C'est plus fort que la table
// unique qu'on visait au départ : le compilateur tient ce qu'une assertion
// aurait dû surveiller.

import type { ShortcutId } from "./shortcuts";

export interface HelpRow {
  /** Une touche par case : chacune devient un `<kbd>`. */
  caps: string[];
  label: string;
  /** La nuance qu'il faut lire AVANT d'essayer. */
  note?: string;
}

/** Les raccourcis que cette page ajoute. Un par identifiant lié, sans exception. */
export const HELP: Record<ShortcutId, HelpRow> = {
  commentLine: {
    caps: ["Ctrl", "/"],
    label: "Commenter ou décommenter la ligne",
    note: "Sur un clavier canadien-français, « / » se tape Maj+3 : Ctrl+Maj+3.",
  },
  commentBlock: {
    caps: ["Ctrl", "Maj", "/"],
    label: "Commentaire de bloc /* … */",
    note: "Canadien-français : Ctrl+Maj+6.",
  },
  duplicate: { caps: ["Ctrl", "D"], label: "Dupliquer la ligne ou la sélection" },
  deleteLine: {
    caps: ["Ctrl", "Maj", "K"],
    label: "Supprimer la ligne",
    note: "Ctrl+Maj+D fait la même chose — et c'est celui à utiliser sous Firefox, où Ctrl+Maj+K est pris par le navigateur.",
  },
  moveUp: { caps: ["Alt", "Maj", "↑"], label: "Déplacer la ligne vers le haut" },
  moveDown: { caps: ["Alt", "Maj", "↓"], label: "Déplacer la ligne vers le bas" },
  completeStatement: {
    caps: ["Ctrl", "Maj", "Entrée"],
    label: "Terminer l'instruction (« ; » et ligne suivante)",
  },
  nextIssue: { caps: ["F2"], label: "Aller à la faute suivante" },
  gotoLine: { caps: ["Ctrl", "G"], label: "Aller à la ligne…" },
  save: {
    caps: ["Ctrl", "S"],
    label: "Rien à faire : ton code est enregistré tout seul",
    note: "Le raccourci le confirme et force l'enregistrement tout de suite, au lieu d'attendre.",
  },
  run: { caps: ["Ctrl", "Entrée"], label: "Tester l'exercice" },
  help: { caps: ["F1"], label: "Ouvrir et fermer cet aide-mémoire" },
  catalog: { caps: ["Ctrl", "K"], label: "Chercher un exercice" },
  escape: { caps: ["Échap"], label: "Fermer un panneau, sinon revenir au code" },
};

/** L'ordre d'affichage, groupé comme on en parle -- pas comme la table est écrite. */
export const GROUPS: { title: string; ids: ShortcutId[] }[] = [
  {
    title: "Écrire du code",
    ids: [
      "commentLine",
      "commentBlock",
      "duplicate",
      "deleteLine",
      "moveUp",
      "moveDown",
      "completeStatement",
    ],
  },
  { title: "Se déplacer", ids: ["nextIssue", "gotoLine", "catalog", "escape"] },
  { title: "Agir", ids: ["save", "run", "help"] },
];

/**
 * CE QUE LE NAVIGATEUR FAIT DÉJÀ, ET QU'ON NE LUI PREND PAS.
 *
 * Ça a l'air d'être du remplissage ; c'en est le contraire. La question que se
 * pose quelqu'un devant un éditeur dans une page web, c'est « est-ce que Ctrl+Z
 * marche ici ? » -- et la seule réponse rassurante est de l'écrire. C'est aussi
 * ce qui explique pourquoi Ctrl+F n'ouvre pas un champ à nous : la recherche du
 * navigateur trouve déjà le code, puisqu'il est peint dans la couche colorée.
 */
export const NATIVE: HelpRow[] = [
  { caps: ["Ctrl", "Z"], label: "Annuler" },
  { caps: ["Ctrl", "Maj", "Z"], label: "Refaire", note: "Ctrl+Y marche aussi." },
  { caps: ["Ctrl", "F"], label: "Rechercher dans la page" },
  { caps: ["Ctrl", "C"], label: "Copier, coller, couper, tout sélectionner" },
  { caps: ["Ctrl", "←"], label: "Se déplacer d'un mot" },
];

/** Ce qui marchait déjà dans l'éditeur, et que personne n'avait écrit nulle part. */
export const ALREADY: HelpRow[] = [
  { caps: ["Tab"], label: "Indenter la ligne ou le bloc sélectionné" },
  { caps: ["Maj", "Tab"], label: "Désindenter" },
  {
    caps: ["(", "[", "{", "\""],
    label: "Se ferment toutes seules",
    note: "Taper le caractère fermant le survole au lieu d'en écrire un second.",
  },
  {
    caps: ["Échap", "puis", "Tab"],
    label: "Sortir du champ de code au clavier",
    note: "Tab indente : sans ce geste, on ne pourrait plus quitter l'éditeur sans la souris.",
  },
];
