let SKILL_LABELS: Record<string, string> = {};

/** The published catalogue carries a label per skill; an unnamed one shows its id. */
export function setSkillLabels(labels: Record<string, string>): void {
  SKILL_LABELS = labels;
}

export const skillLabel = (id: string): string => SKILL_LABELS[id] ?? id;

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
