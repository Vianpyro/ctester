// THE SESSION KEY FROM MOODLE'S LINK, AND IT SURVIVES A RELOAD WITHOUT ITS QUERY
// STRING.
//
// It arrives as `?k=…`. A student who types the address from memory, follows a shared
// link without the key, or comes back through a bookmark used to end up without it --
// and only found out after writing their code.
//
// `sessionStorage` AND NOT `localStorage`, deliberately: the key dies with the tab. On
// a shared lab machine, leaving it behind would hand it to the next student who sits
// down.

import { sessionGet, sessionSet } from "../storage";

const KEY_STORAGE = "ctester.cle";

let cached: string | null = null;

/** Read the key out of the URL once, and remember it for the tab. */
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

/**
 * SAID AT LOAD TIME, NOT ON THE FIRST SUBMISSION. Without this a student would write
 * their whole exercise before learning they could not test it -- and they would learn
 * it through "clé de session invalide ou expirée", which means nothing to them and
 * does not say what to do. NON-BLOCKING: writing and saving work perfectly fine
 * without a key.
 */
export const MISSING_KEY_MESSAGE =
  "Il manque ta clé d'accès. Rouvre le lien de CTester depuis Moodle pour pouvoir " +
  "tester ton code. Tu peux écrire en attendant : ton brouillon est enregistré.";
