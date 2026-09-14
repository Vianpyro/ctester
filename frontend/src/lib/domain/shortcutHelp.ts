import type { ShortcutId } from "./shortcuts";

export interface HelpRow {
  caps: string[];
  label: string;
  note?: string;
}

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

export const NATIVE: HelpRow[] = [
  { caps: ["Ctrl", "Z"], label: "Annuler" },
  { caps: ["Ctrl", "Maj", "Z"], label: "Refaire", note: "Ctrl+Y marche aussi." },
  { caps: ["Ctrl", "F"], label: "Rechercher dans la page" },
  { caps: ["Ctrl", "C"], label: "Copier, coller, couper, tout sélectionner" },
  { caps: ["Ctrl", "←"], label: "Se déplacer d'un mot" },
];

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
