/** What a student sends for one question: a text, a list, or a map of prompt to choice. */
export type Answer = string | string[] | Record<string, string>;

/** Shape-aware emptiness, mirroring what the server calls a blank answer. */
export function answered(value: Answer | undefined): boolean {
  if (value === undefined) return false;
  if (typeof value === "string") return !!value.trim();
  const entries = Array.isArray(value) ? value : Object.values(value);
  return entries.some((one) => !!one.trim());
}

/** Answers travel and are held as text; a structured one travels as JSON. */
export const pack = (value: Answer | undefined): string =>
  value === undefined
    ? ""
    : typeof value === "string"
      ? value
      : JSON.stringify(value);

export const packAll = (
  answers: Record<string, Answer>,
): Record<string, string> => {
  const flat: Record<string, string> = {};
  for (const [id, value] of Object.entries(answers)) flat[id] = pack(value);
  return flat;
};

/**
 * A page can hold several exercises, and question ids are only unique inside one quiz, so
 * every answer on the page is keyed by both. The judge never sees this key: it reads the
 * question id alone. The separator is "/" so the key is also usable as a DOM id: neither
 * an exercise id nor a question id may contain one.
 */
export const keyOf = (exercise: string, question: string): string =>
  exercise + "/" + question;

export function splitKey(key: string): [string, string] {
  const cut = key.indexOf("/");
  return cut < 0 ? ["", key] : [key.slice(0, cut), key.slice(cut + 1)];
}
