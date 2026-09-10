// THE SESSION'S STORAGE KEYS, IN ONE PLACE. They are read from both halves of
// the split -- the core (`session.svelte.ts`, and the callback cleanup in
// `main.ts`) and the lazily loaded `oidc.ts` -- and a key name spelled twice is
// a key name that eventually differs by one character, with a session that
// silently stops being remembered as the symptom.
//
// ALL FOUR ARE `sessionStorage`: they die with the tab. On a shared lab machine,
// renewal material that outlived the tab would be a session offered to the next
// student who sits down.

export const TOKEN_KEY = "ctester.token";
export const REFRESH_KEY = "ctester.refresh";
export const EXPIRY_KEY = "ctester.expire";
export const PKCE_KEY = "ctester.pkce";
/** The query string the OIDC callback strips, to put back with `replaceState`. */
export const RETURN_KEY = "ctester.retour";
