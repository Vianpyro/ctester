// THE SESSION'S STORAGE KEYS, IN ONE PLACE. They are read from both halves of
// the split -- the core (`session.svelte.ts`, and the callback cleanup in
// `main.ts`) and the lazily loaded `oidc.ts` -- and a key name spelled twice is
// a key name that eventually differs by one character, with a session that
// silently stops being remembered as the symptom.
//
// --- WHICH STORE, AND WHY IT CHANGED -----------------------------------------
//
// THE CREDENTIALS ARE IN `localStorage`, AND THAT IS A DELIBERATE REVERSAL.
// They were in `sessionStorage`, which dies with the tab -- safe on a lab
// machine, and structurally unable to deliver what this course actually needs.
// The labs are WEEKLY: the student closes the browser on Tuesday evening and
// comes back the following Tuesday. No amount of refresh-token machinery
// survives that, because the refresh token itself left with the tab. The
// renewal looked broken when it was simply never asked.
//
// SO THE BOUND IS A DEADLINE INSTEAD OF A TAB. `ctester.until` caps a session
// at `SESSION_MAX_DAYS` of INACTIVITY, and it is what replaces the protection
// the tab used to give: a session abandoned on a shared station stops working
// on its own rather than never. The residual risk is real and is the price of
// the requirement -- someone who walks away without signing out leaves a
// working session behind until that deadline.
//
// THE PKCE VERIFIER AND THE RETURN QUERY STAY IN `sessionStorage`. They live
// for the few seconds of one redirect, in one tab, and they come back in that
// same tab -- so `sessionStorage` covers them exactly, and giving them a longer
// life would only widen what a stale one could be replayed against.

export const TOKEN_KEY = "ctester.token";
export const REFRESH_KEY = "ctester.refresh";
export const EXPIRY_KEY = "ctester.expire";
/** When this session stops being renewable, whatever the issuer still allows. */
export const DEADLINE_KEY = "ctester.until";
export const PKCE_KEY = "ctester.pkce";
/** The query string the OIDC callback strips, to put back with `replaceState`. */
export const RETURN_KEY = "ctester.retour";

/**
 * How long a session survives without being used, in days.
 *
 * TEN DAYS IS THE COURSE'S CALENDAR, NOT A ROUND NUMBER: the labs are a week
 * apart, plus three days for whoever finishes late. A student must never be
 * asked to sign in again between two labs -- that is the whole point of the
 * change that moved these keys to `localStorage`.
 *
 * IT MUST MATCH `refresh_token_lifetime` IN RAUTHY'S CONFIG (which is in HOURS,
 * so 240), and that is not a coincidence to tidy away: if the issuer gives up
 * first, the page keeps a token it can no longer renew and the student is
 * signed out by a failed request instead of by this clock. Rauthy's default is
 * 48 hours -- two days -- so leaving it alone caps everything here at two days
 * no matter what this file says.
 */
export const SESSION_MAX_DAYS = 10;
