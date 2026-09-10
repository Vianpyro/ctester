// THE WORDS, IN ONE PLACE. Skill ids, contexts and difficulties come from the
// test repository as identifiers; the French the student reads is here. Two
// tables would drift, and the one that drifted would be the one on screen.

export const SKILL_LABELS: Record<string, string> = {
  "number-systems": "systèmes de nombres",
  "binary-hexadecimal": "binaire et hexadécimal",
  compilation: "compilation",
  main: "main()",
  libraries: "bibliothèques",
  printf: "printf",
  scanf: "scanf",
  variables: "variables",
  types: "types",
  "arithmetic-operators": "opérateurs",
  "boolean-logic": "logique booléenne",
  "bitwise-operations": "opérations binaires",
  conditions: "conditions",
  switch: "switch",
  while: "boucles while",
  "do-while": "boucles do/while",
  for: "boucles for",
  functions: "fonctions",
  parameters: "paramètres",
  "return-values": "retours",
  pointers: "pointeurs",
  "arrays-1d": "tableaux",
  "arrays-2d": "tableaux 2D",
  strings: "chaînes",
  "algorithm-design": "algorithmes",
  complexity: "complexité",
};

export const skillLabel = (id: string): string => SKILL_LABELS[id] ?? id;

export const CONTEXT_LABELS: Record<string, string> = {
  mechanical: "mécanique",
  electrical: "électrique",
  "automated-production": "production automatisée",
  aerospace: "aérospatial",
  logistics: "logistique",
  computing: "informatique",
  "general-engineering": "ingénierie",
};

export const DIFFICULTY_LABELS: Record<string, string> = {
  intro: "découverte",
  foundation: "fondations",
  intermediate: "intermédiaire",
  advanced: "avancé",
};

/**
 * WHAT IS EXPECTED AS A SUBMISSION, by mode. All THREE modes, and not "quiz or
 * the rest": a unity exercise expects a module with NO main(), and promising the
 * opposite sends 42 of the 72 exercises straight into a linking error the
 * student has no way to connect to the badge that asked for it.
 */
export const EXPECTED: Record<string, string> = {
  quiz: "réponses à saisir",
  io: "programme complet, avec son main()",
  unity: "module seul, sans main()",
};

/** What the count in a verdict counts, by mode. */
export const UNITS: Record<string, string> = {
  quiz: "réponses justes",
  io: "cas réussis",
  unity: "tests réussis",
};

/**
 * ONE WORD PER STATE, ACROSS THE WHOLE PAGE. The strip, the menu and "Mes
 * progrès" all say "réussi" -- never "validé". Two words for one state is a
 * student wondering whether they are two things.
 */
export const STATUS_WORD: Record<string, string> = { solved: "réussi", attempted: "essayé" };
export const STATUS_MARK: Record<string, string> = { solved: "✓", attempted: "•" };
/** The stylesheet's selectors were left untouched, so the wire values translate. */
export const STATUS_CLASS: Record<string, string> = { solved: "valide", attempted: "essaye" };

export const plural = (n: number, word: string): string => n + " " + word + (n > 1 ? "s" : "");

/** Two digits, like on a course outline: "7" reads as "07". */
export const groupNumber = (n: number | string): string =>
  "groupe " + String(n).padStart(2, "0");

/** At most two letters, from a name someone CHOSE. Never from a `sub`. */
export function initialsOf(name: string): string {
  const words = String(name || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  return words
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join("");
}

const twoDigits = (n: number) => String(n).padStart(2, "0");

/** The wall clock, for the draft indicator. */
export function clockNow(at: Date = new Date()): string {
  return twoDigits(at.getHours()) + ":" + twoDigits(at.getMinutes());
}

/**
 * THE READER'S TIME, NOT THE SERVER'S. The server sends the instant in UTC;
 * only the browser knows which zone to read it in. A value that cannot be parsed
 * displays as-is -- an old message beats an "Invalid Date".
 */
export function localTime(instant: string): string {
  const d = new Date(instant);
  if (isNaN(d.getTime())) return String(instant);
  return d.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
}
