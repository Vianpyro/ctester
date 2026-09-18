import { sessionGet, sessionSet } from "../storage";

const KEY_STORAGE = "ctester.key";

let cached: string | null = null;

export function captureAccessKey(search: string): string {
  const fromLink = new URLSearchParams(search).get("k") || "";
  if (fromLink) sessionSet(KEY_STORAGE, fromLink);
  cached = fromLink || sessionGet(KEY_STORAGE);
  return cached;
}

export function sessionKey(): string {
  if (cached === null) cached = sessionGet(KEY_STORAGE);
  return cached;
}

export const MISSING_KEY_MESSAGE =
  "Il manque ta clé d'accès. Rouvre le lien de CTester depuis Moodle pour pouvoir " +
  "tester ton code. Tu peux écrire en attendant : ton brouillon est enregistré.";
