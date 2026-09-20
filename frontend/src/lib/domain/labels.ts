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

export const EXPECTED: Record<string, string> = {
  quiz: "réponses à saisir",
  io: "programme complet, avec son main()",
  unity: "module seul, sans main()",
};

export const UNITS: Record<string, string> = {
  quiz: "réponses justes",
  io: "cas réussis",
  unity: "tests réussis",
};

export const STATUS_WORD: Record<string, string> = { solved: "réussi", attempted: "essayé" };
export const STATUS_MARK: Record<string, string> = { solved: "✓", attempted: "•" };
export const STATUS_CLASS: Record<string, string> = { solved: "valid", attempted: "tryit" };

export const plural = (n: number, word: string): string => n + " " + word + (n > 1 ? "s" : "");

export const groupNumber = (n: number | string): string =>
  "groupe " + String(n).padStart(2, "0");

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

export function clockNow(at: Date = new Date()): string {
  return twoDigits(at.getHours()) + ":" + twoDigits(at.getMinutes());
}

export function localTime(instant: string): string {
  const d = new Date(instant);
  if (isNaN(d.getTime())) return String(instant);
  return d.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
}

/** "Ex.3 IEEE 754" -> "3". Same shape the exercise strip reads. */
const numberOf = (title: string): string => title.match(/^ex\.?\s*(\d+)/i)?.[1] ?? "";

/**
 * What the test button promises. A page can hold several exercises and tests them
 * together, so the button has to name them -- "Tester l'exercice" would be a half-truth.
 */
export function testLabel(titles: string[]): string {
  const numbers = titles.map(numberOf).filter(Boolean);
  if (numbers.length !== titles.length || !numbers.length) {
    return titles.length > 1 ? "Tester les exercices" : "Tester l'exercice";
  }
  if (numbers.length === 1) return "Tester l'exercice " + numbers[0];
  return (
    "Tester les exercices " +
    numbers.slice(0, -1).join(", ") +
    " et " +
    numbers[numbers.length - 1]
  );
}
