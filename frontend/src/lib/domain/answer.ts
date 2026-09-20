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

