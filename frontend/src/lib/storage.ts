// BROWSER STORAGE, WRAPPED ONCE. Every read and write is guarded: a private
// window, cleared site data, or a browser set to refuse site data makes the
// accessor itself throw, and none of those is worth taking the page down for.
//
// THE TWO STORES MEAN DIFFERENT THINGS, and the split is load-bearing:
//
//   sessionStorage  dies with the tab. The PKCE verifier, the session key from
//                   Moodle's link, the presence id. On a shared lab machine,
//                   anything here that outlived the tab would be handed to the
//                   next student.
//   localStorage    the device's memory. Drafts, the theme (read by
//                   `public/theme.js` before the first paint), the station id,
//                   whether the chat dock was open -- AND, since the weekly-lab
//                   requirement, the session credentials: see `auth/keys.ts`
//                   for why the tab stopped being an acceptable bound and what
//                   replaced it.

export function sessionGet(name: string): string {
  try {
    return sessionStorage.getItem(name) || "";
  } catch {
    return "";
  }
}

export function sessionSet(name: string, value: string): void {
  try {
    sessionStorage.setItem(name, value);
  } catch {
    // Nothing to do and nothing to say: a session that cannot be remembered
    // still works for as long as the tab is open.
  }
}

export function sessionDrop(name: string): void {
  try {
    sessionStorage.removeItem(name);
  } catch {
    /* see above */
  }
}

export function localGet(name: string): string {
  try {
    return localStorage.getItem(name) || "";
  } catch {
    return "";
  }
}

/** False when the write did not happen -- the draft indicator has to say so. */
export function localSet(name: string, value: string): boolean {
  try {
    localStorage.setItem(name, value);
    return true;
  } catch {
    return false;
  }
}

export function localDrop(name: string): void {
  try {
    localStorage.removeItem(name);
  } catch {
    /* see above */
  }
}

/**
 * A random id kept for the life of the tab, or of the device.
 *
 * Used for the presence counter (per tab: two tabs really are two windows) and
 * for the anonymous submission quota (per device: in the first labs, eighty
 * stations leave through one NATed IP). Both are falsifiable and neither proves
 * anything -- one is a displayed number, the other a rate limiter's bucket.
 */
export function randomId(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return String(Math.random()).slice(2) + Date.now();
}
