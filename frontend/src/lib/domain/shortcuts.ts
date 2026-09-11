// LA TABLE *EST* LE MATCHER, et c'est la seule façon que l'aide-mémoire ne mente
// jamais. Une table d'un côté et un `switch` écrit à la main de l'autre, ce sont
// deux sources avec un test entre les deux : celui qui dérive est celui qu'on
// oublie de relire. Ici la liaison est une DONNÉE et `matchShortcut()` est une
// boucle dessus, donc la dérive n'est pas rattrapée, elle est impossible.
//
// ⚠ LE CARACTÈRE PRODUIT, JAMAIS `event.code`. C'est le piège de cette
// fonctionnalité, et il est spécifique à cette cohorte. Sur un clavier
// CANADIEN-FRANÇAIS -- le défaut au Québec -- la touche physique `Slash`
// produit « é » : `/` s'y tape `Maj+3` et `?` se tape `Maj+6`. Une liaison sur
// `event.code === "Slash"` lierait donc « commenter la ligne » à la touche qui
// IMPRIME UN É pour une bonne partie du cours, et l'aide-mémoire afficherait un
// raccourci qui n'existe pas. (En canadien multilingue `/` et `?` restent sur
// `Slash` ; en AZERTY `Slash` produit `!`.) On compare donc ce que la touche
// ÉCRIT, et il n'y a pas un seul `event.code` dans ce fichier.
//
// CE QUI DÉCOULE DE CE CHOIX, et qui est la bonne surprise : `Ctrl+Maj+/` de
// CLion EST `Ctrl+?` sur un clavier US. Les deux commentaires n'ont jamais été
// séparés par le drapeau Maj, mais par le caractère -- donc ignorer Maj et
// discriminer sur `/` contre `?` rend la liaison IDENTIQUE sur toutes les
// dispositions, au lieu d'en exiger une par clavier.

/**
 * Une frappe. LES NOMS SONT CEUX DE `KeyboardEvent`, EXPRÈS : un vrai événement
 * est alors structurellement un `Chord`, donc les deux écouteurs passent le leur
 * tel quel. Aucun adaptateur à écrire en double, et surtout aucun type DOM
 * importé dans `domain/`, qui doit rester pur.
 */
export interface Chord {
  /** Ce que la touche ÉCRIT. Jamais `event.code` -- voir l'en-tête. */
  key: string;
  shiftKey: boolean;
  ctrlKey: boolean;
  /** ⌘ sur un Mac. Le matcher le replie sur `ctrlKey`. */
  metaKey: boolean;
  altKey: boolean;
}

export type ShortcutId =
  // Les transformations de texte, dans la surface d'édition.
  | "commentLine"
  | "commentBlock"
  | "duplicate"
  | "deleteLine"
  | "moveUp"
  | "moveDown"
  | "completeStatement"
  // La navigation, dans la surface d'édition aussi.
  | "nextIssue"
  | "gotoLine"
  // La page.
  | "save"
  | "run"
  | "help"
  | "catalog"
  | "escape";

interface Binding {
  id: ShortcutId;
  /** Les caractères produits, minuscules pour les lettres. */
  keys: string[];
  /** Ctrl **ou** ⌘. Absent veut dire : ni l'un ni l'autre. */
  ctrl?: boolean;
  /** Absent veut dire « Maj ne doit PAS être tenu ». `"any"` l'ignore. */
  shift?: boolean | "any";
  /** Absent veut dire « Alt ne doit PAS être tenu » -- voir la garde AltGr. */
  alt?: boolean;
}

/**
 * ⚠ `alt` ABSENT EST LA GARDE ALTGR, et ce n'est pas un détail de style. Sous
 * Windows, AltGr se rapporte comme `ctrlKey && altKey`. Sans exiger `alt` faux,
 * toute disposition où un caractère voulu passe par AltGr verrait sa frappe
 * avalée ici : l'étudiant taperait son caractère et la ligne se commenterait.
 */
const BINDINGS: Binding[] = [
  // Maj départage exactement, donc l'ordre ne tranche aucune ambiguïté -- il est
  // là pour se lire, pas pour décider.
  { id: "commentLine", keys: ["/"], ctrl: true, shift: "any" },
  { id: "commentBlock", keys: ["?"], ctrl: true, shift: "any" },
  { id: "duplicate", keys: ["d"], ctrl: true },
  // DEUX CHORDS POUR UN SEUL GESTE, et c'est Firefox qui l'impose : `Ctrl+Maj+K`
  // y ouvre la console web AU NIVEAU DU NAVIGATEUR, donc la page ne peut pas
  // l'intercepter. `Ctrl+Maj+D` passe partout. On garde le premier pour la
  // parité avec VS Code, et le second pour que le geste existe sous Firefox.
  { id: "deleteLine", keys: ["k", "d"], ctrl: true, shift: true },
  { id: "moveUp", keys: ["ArrowUp"], alt: true, shift: true },
  { id: "moveDown", keys: ["ArrowDown"], alt: true, shift: true },
  { id: "completeStatement", keys: ["Enter"], ctrl: true, shift: true },
  { id: "nextIssue", keys: ["F2"] },
  { id: "gotoLine", keys: ["g"], ctrl: true },
  { id: "save", keys: ["s"], ctrl: true },
  { id: "run", keys: ["Enter"], ctrl: true },
  { id: "help", keys: ["F1"] },
  { id: "catalog", keys: ["k"], ctrl: true },
  { id: "escape", keys: ["Escape"] },
];

/**
 * Ce que la surface d'édition réclame : elle `preventDefault()` sur ces
 * identifiants-là, et laisse tout le reste remonter jusqu'à la fenêtre.
 */
export const EDITOR_COMMANDS: ReadonlySet<ShortcutId> = new Set<ShortcutId>([
  "commentLine",
  "commentBlock",
  "duplicate",
  "deleteLine",
  "moveUp",
  "moveDown",
  "completeStatement",
  "nextIssue",
  "gotoLine",
]);

/**
 * Ceux qui transforment le TEXTE, par opposition à ceux qui ne font que
 * déplacer le curseur. C'est ce qui sépare les deux sur un document d'équipe
 * verrouillé : `F2` et `Ctrl+G` y marchent, les sept autres sont refusés.
 */
export const TEXT_COMMANDS: ReadonlySet<ShortcutId> = new Set<ShortcutId>([
  "commentLine",
  "commentBlock",
  "duplicate",
  "deleteLine",
  "moveUp",
  "moveDown",
  "completeStatement",
]);

/**
 * L'identifiant lié à cette frappe, ou `null` si elle n'est pas à nous -- et
 * « pas à nous » est le cas de loin le plus fréquent : tout ce que cette
 * fonction rend `null` reste au navigateur et à l'étudiant, Ctrl+Z en tête.
 */
export function matchShortcut(chord: Chord): ShortcutId | null {
  // MINUSCULE SUR LES LETTRES, et c'est un bogue réparé au passage : l'ancienne
  // condition écrite à la main comparait `event.key !== "k"`, donc `Ctrl+K`
  // n'ouvrait pas le catalogue quand Verr.Maj était actif.
  const key = chord.key.length === 1 ? chord.key.toLowerCase() : chord.key;
  const ctrl = chord.ctrlKey || chord.metaKey;
  for (const binding of BINDINGS) {
    if (!binding.keys.includes(key)) continue;
    if ((binding.ctrl ?? false) !== ctrl) continue;
    if ((binding.alt ?? false) !== chord.altKey) continue;
    const shift = binding.shift ?? false;
    if (shift !== "any" && shift !== chord.shiftKey) continue;
    return binding.id;
  }
  return null;
}

