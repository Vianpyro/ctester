import { i18n, t } from "../i18n.svelte";

let SKILL_LABELS: Record<string, string> = {};

/** The published catalogue carries a label per skill; an unnamed one shows its id. */
export function setSkillLabels(labels: Record<string, string>): void {
  SKILL_LABELS = labels;
}

export const skillLabel = (id: string): string => SKILL_LABELS[id] ?? id;

const MODES = ["quiz", "io", "unity"];

export const expectedOf = (mode: string): string =>
  MODES.includes(mode) ? t(`mode.${mode}.expected`) : "";

export const unitsOf = (mode: string): string =>
  t(`mode.${MODES.includes(mode) ? mode : "io"}.units`);

export const statusWord = (status: string): string =>
  status === "solved" || status === "attempted" ? t(`status.${status}`) : status;
export const STATUS_MARK: Record<string, string> = { solved: "✓", attempted: "•" };
export const STATUS_CLASS: Record<string, string> = { solved: "valid", attempted: "tryit" };

// A teammate who shows no name is "Teammate <n>", n from the handle the server gives (m1, m2…).
export const memberName = (member: { id: string; name: string }): string =>
  member.name || t("team.mate", { n: member.id.replace(/^m/, "") });

export const teamLabel = (number: number): string => t("team.label", { n: number });

export const groupNumber = (n: number | string): string =>
  t("group.number", { n: String(n).padStart(2, "0") });

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
  return d.toLocaleString(i18n.lang, { dateStyle: "short", timeStyle: "short" });
}
